#!/usr/bin/env python3
"""Build forward-only official OHLCV evidence after the frozen Stage2 coverage end.

Historical rows <= Stage2 coverage_end remain frozen and are not rebuilt. This builder only
collects the delta through the fresh current-master as_of date, preserving the production G3
parsers and invariants.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

import build_g3_ohlcv as g3

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/current_master/cn_main_a.csv"
MASTER_MANIFEST = ROOT / "data/current_master/manifest.json"
STAGE2_FINAL = ROOT / "data/stage2_final/manifest.json"

_sessions: dict[str, requests.Session] = {}
_last: dict[str, float] = {}


def paced_request(url: str, referer: str, attempts: int = 5) -> bytes:
    host = "SSE" if "sse.com.cn" in url else "SZSE"
    minimum = 0.55 if host == "SSE" else 0.25
    s = _sessions.get(host)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": g3.UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": referer, "Connection": "keep-alive",
        })
        try: s.get(referer, timeout=15)
        except requests.RequestException: pass
        _sessions[host] = s
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        delay = minimum - (time.monotonic() - _last.get(host, 0.0))
        if delay > 0: time.sleep(delay)
        try:
            r = s.get(url, timeout=45)
            r.raise_for_status()
            if not r.content: raise RuntimeError(f"empty response: {url}")
            return r.content
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts: time.sleep(min(0.8 * (2 ** (attempt - 1)), 8.0))
        finally:
            _last[host] = time.monotonic()
    assert last_error is not None
    raise last_error


def norm_date(value: str) -> date:
    s=(value or "").strip()
    if len(s)==8 and s.isdigit(): s=f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return date.fromisoformat(s)


def boundaries() -> tuple[date,date]:
    stage2=json.loads(STAGE2_FINAL.read_text(encoding="utf-8"))
    frozen=date.fromisoformat(str((stage2.get("fingerprint_basis") or {}).get("coverage_end")))
    manifest=json.loads(MASTER_MANIFEST.read_text(encoding="utf-8"))
    end=date.fromisoformat(str((manifest.get("szse") or {}).get("as_of")))
    if end <= frozen: raise ValueError(f"non-forward window: {frozen} -> {end}")
    return frozen,end


def current_intervals(exchange: str) -> dict[str, tuple[date,date|None]]:
    out={}
    with MASTER.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f):
            if r.get("exchange") != exchange: continue
            code=r["code"]
            if code in out: raise ValueError(f"duplicate current identity {exchange}:{code}")
            out[code]=(norm_date(r["listing_date"]),None)
    if not out: raise ValueError(f"empty current master for {exchange}")
    return out


def sse_recent_url(code: str, recent_rows: int = 80) -> str:
    return (
        f"https://yunhq.sse.com.cn:32042/v1/sh1/dayk/{code}?" +
        urlencode({"select":"date,open,high,low,close,volume,amount","begin":str(-recent_rows),"end":"-1"})
    )


def build_sse_shard(shard: int, shards: int, outdir: Path) -> None:
    frozen,end=boundaries(); intervals=current_intervals("SSE")
    codes=sorted(c for c,iv in intervals.items() if iv[0] <= end)
    selected=[c for i,c in enumerate(codes) if i % shards == shard]
    rows=[]; sources=[]
    for idx,code in enumerate(selected,1):
        url=sse_recent_url(code)
        raw=paced_request(url,g3.SSE_REFERER)
        parsed,diag=g3.parse_sse_dayk(raw,code,intervals[code],end)
        delta=[r for r in parsed if date.fromisoformat(r["trade_date"]) > frozen]
        rows.extend(delta)
        diag.update({"url":url,"sha256":g3.sha256(raw),"bytes":len(raw),"delta_rows":len(delta)})
        sources.append(diag)
        if idx % 100 == 0: print(f"SSE forward shard {shard}/{shards}: {idx}/{len(selected)}",flush=True)
    outdir.mkdir(parents=True,exist_ok=True)
    data_file=outdir/f"sse_forward_shard{shard:02d}.csv.gz"
    n,digest=g3.write_gzip_csv(data_file,rows)
    trading=sorted({r["trade_date"] for r in rows})
    meta={
        "exchange":"SSE","shard":shard,"shards":shards,"frozen_coverage_end":frozen.isoformat(),
        "coverage_end":end.isoformat(),"securities_queried":len(selected),"source_requests":len(sources),
        "rows":n,"first_trading_day":trading[0] if trading else None,"last_trading_day":trading[-1] if trading else None,
        "data_file":data_file.name,"data_sha256":digest,"sources":sources,
    }
    (outdir/f"sse_forward_shard{shard:02d}_sources.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")


def build_szse_delta(outdir: Path) -> None:
    frozen,end=boundaries(); intervals=current_intervals("SZSE")
    day=frozen+timedelta(days=1); rows=[]; sources=[]
    while day <= end:
        if day.weekday() < 5:
            url=g3.szse_url(day)
            raw=paced_request(url,g3.SZSE_REFERER)
            parsed,diag=g3.parse_szse_day(raw,day,intervals)
            diag.update({"day":day.isoformat(),"url":url,"sha256":g3.sha256(raw),"bytes":len(raw)})
            sources.append(diag); rows.extend(parsed)
        day += timedelta(days=1)
    outdir.mkdir(parents=True,exist_ok=True)
    data_file=outdir/"szse_forward.csv.gz"
    n,digest=g3.write_gzip_csv(data_file,rows)
    trading=sorted({r["trade_date"] for r in rows})
    meta={
        "exchange":"SZSE","frozen_coverage_end":frozen.isoformat(),"coverage_end":end.isoformat(),
        "current_securities":len(intervals),"source_requests":len(sources),"rows":n,
        "first_trading_day":trading[0] if trading else None,"last_trading_day":trading[-1] if trading else None,
        "trading_days":len(trading),"data_file":data_file.name,"data_sha256":digest,"sources":sources,
    }
    (outdir/"szse_forward_sources.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")


def main() -> int:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("sse-shard"); s.add_argument("--shard",type=int,required=True); s.add_argument("--shards",type=int,default=8); s.add_argument("--out",default="build/freshness-phase2/sse")
    z=sub.add_parser("szse-delta"); z.add_argument("--out",default="build/freshness-phase2/szse")
    a=ap.parse_args()
    if a.cmd=="sse-shard":
        if not 0 <= a.shard < a.shards: raise ValueError("invalid shard")
        build_sse_shard(a.shard,a.shards,Path(a.out))
    else: build_szse_delta(Path(a.out))
    return 0


if __name__=="__main__": sys.exit(main())
