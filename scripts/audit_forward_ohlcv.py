#!/usr/bin/env python3
"""Fail-closed audit for the forward-only official OHLCV freshness delta."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/current_master/cn_main_a.csv"
MASTER_MANIFEST = ROOT / "data/current_master/manifest.json"
STAGE2_FINAL = ROOT / "data/stage2_final/manifest.json"
FIELDS = ["exchange", "code", "trade_date", "open", "high", "low", "close", "volume_shares", "amount_cny"]


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_date(value: str) -> date:
    s=(value or "").strip()
    if re.fullmatch(r"\d{8}",s): s=f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return date.fromisoformat(s)


def dec(value: str) -> Decimal:
    try: return Decimal(str(value))
    except InvalidOperation as exc: raise ValueError(f"invalid decimal {value!r}") from exc


def current_master() -> dict[tuple[str,str],date]:
    out={}
    with MASTER.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f):
            key=(r["exchange"],r["code"])
            if key in out: raise ValueError(f"duplicate current identity {key}")
            out[key]=norm_date(r["listing_date"])
    if not out: raise ValueError("fresh current master empty")
    return out


def boundaries() -> tuple[date,date]:
    s2=read_json(STAGE2_FINAL); mm=read_json(MASTER_MANIFEST)
    frozen=date.fromisoformat(str((s2.get("fingerprint_basis") or {}).get("coverage_end") or ""))
    end=date.fromisoformat(str((mm.get("szse") or {}).get("as_of") or ""))
    if end <= frozen: raise ValueError(f"not forward: {frozen}->{end}")
    return frozen,end


def expected_weekdays(start: date,end: date) -> list[date]:
    out=[]; d=start
    while d<=end:
        if d.weekday()<5: out.append(d)
        d+=timedelta(days=1)
    return out


def validate_rows(path: Path, identities: dict[tuple[str,str],date], frozen: date, end: date,
                  global_seen: set[tuple[str,str,str]], errors: list[str]) -> tuple[int,set[str],set[str]]:
    rows=0; days=set(); codes=set()
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames != FIELDS: errors.append(f"bad schema {path.name}: {reader.fieldnames}")
        for n,r in enumerate(reader,start=2):
            rows+=1
            try:
                ex=r["exchange"]; code=r["code"]; ds=r["trade_date"]; d=date.fromisoformat(ds)
                key=(ex,code)
                if key not in identities: errors.append(f"row outside fresh universe {path.name}:{n} {key}")
                else:
                    if d < identities[key]: errors.append(f"row before listing {path.name}:{n} {key} {d} < {identities[key]}")
                if not (frozen < d <= end): errors.append(f"row outside forward window {path.name}:{n} {d}")
                sk=(ex,code,ds)
                if sk in global_seen: errors.append(f"duplicate row across artifacts {sk}")
                global_seen.add(sk); days.add(ds); codes.add(code)
                o,h,l,c=(dec(r[x]) for x in ("open","high","low","close"))
                if min(o,h,l,c)<0 or h<max(o,l,c) or l>min(o,h,c): errors.append(f"OHLC invariant {path.name}:{n}")
                v=dec(r["volume_shares"]); a=dec(r["amount_cny"])
                if v<0 or a<0 or v!=v.to_integral_value() or a!=a.to_integral_value(): errors.append(f"bad volume/amount {path.name}:{n}")
            except Exception as exc:
                errors.append(f"row parse error {path.name}:{n}: {exc}")
    return rows,days,codes


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="build/freshness-phase2"); ap.add_argument("--sse-shards",type=int,default=8); ap.add_argument("--out",default="build/freshness-phase2/forward_ohlcv_audit.json")
    args=ap.parse_args(); root=Path(args.root); errors=[]
    try: identities=current_master(); frozen,end=boundaries()
    except Exception as exc:
        report={"gate":"FORWARD_OHLCV","pass":False,"errors":[str(exc)]}; print(json.dumps(report,ensure_ascii=False,indent=2)); return 2

    sse_ids={k:v for k,v in identities.items() if k[0]=="SSE"}; szse_ids={k:v for k,v in identities.items() if k[0]=="SZSE"}
    global_seen=set(); sse_rows=0; szse_rows=0; sse_days=set(); szse_days=set(); sse_codes=set(); szse_codes=set(); source_requests=0

    seen_shards=set()
    for shard in range(args.sse_shards):
        meta_path=root/"sse"/f"sse_forward_shard{shard:02d}_sources.json"
        if not meta_path.exists(): errors.append(f"missing SSE shard meta {shard}"); continue
        try:
            meta=read_json(meta_path)
            if int(meta.get("shard",-1))!=shard or int(meta.get("shards",-1))!=args.sse_shards: errors.append(f"SSE shard identity mismatch {shard}")
            seen_shards.add(shard)
            if meta.get("frozen_coverage_end")!=frozen.isoformat() or meta.get("coverage_end")!=end.isoformat(): errors.append(f"SSE boundary mismatch shard {shard}")
            if int(meta.get("source_requests",-1))!=int(meta.get("securities_queried",-2)): errors.append(f"SSE source/request mismatch shard {shard}")
            source_requests += int(meta.get("source_requests") or 0)
            sources=meta.get("sources") or []
            if len(sources)!=int(meta.get("source_requests") or -1): errors.append(f"SSE source metadata count mismatch shard {shard}")
            source_codes=[str(x.get("code")) for x in sources if isinstance(x,dict)]
            if len(source_codes)!=len(set(source_codes)): errors.append(f"duplicate SSE source code shard {shard}")
            for src in sources:
                if not isinstance(src,dict) or len(str(src.get("sha256") or ""))!=64 or int(src.get("bytes") or 0)<=0: errors.append(f"bad SSE source evidence shard {shard}")
            data_path=root/"sse"/str(meta.get("data_file") or "")
            if not data_path.exists(): errors.append(f"missing SSE data shard {shard}"); continue
            if sha256_file(data_path)!=meta.get("data_sha256"): errors.append(f"SSE data hash mismatch shard {shard}")
            n,days,codes=validate_rows(data_path,identities,frozen,end,global_seen,errors)
            if n!=int(meta.get("rows") or -1): errors.append(f"SSE row-count mismatch shard {shard}")
            sse_rows+=n; sse_days|=days; sse_codes|=codes
        except Exception as exc: errors.append(f"SSE shard {shard} audit error: {exc}")
    if seen_shards != set(range(args.sse_shards)): errors.append(f"SSE shard set incomplete {sorted(seen_shards)}")
    if source_requests != len(sse_ids): errors.append(f"SSE identity coverage {source_requests} != {len(sse_ids)}")

    sz_meta_path=root/"szse"/"szse_forward_sources.json"
    if not sz_meta_path.exists(): errors.append("missing SZSE forward meta")
    else:
        try:
            meta=read_json(sz_meta_path)
            if meta.get("frozen_coverage_end")!=frozen.isoformat() or meta.get("coverage_end")!=end.isoformat(): errors.append("SZSE boundary mismatch")
            if int(meta.get("current_securities",-1))!=len(szse_ids): errors.append("SZSE current identity count mismatch")
            sources=meta.get("sources") or []
            expected=expected_weekdays(frozen+timedelta(days=1),end)
            if len(sources)!=len(expected): errors.append(f"SZSE weekday source requests {len(sources)} != {len(expected)}")
            source_days=[str(x.get("day")) for x in sources if isinstance(x,dict)]
            if source_days != [d.isoformat() for d in expected]: errors.append("SZSE source-day sequence mismatch")
            for src in sources:
                if not isinstance(src,dict) or len(str(src.get("sha256") or ""))!=64 or int(src.get("bytes") or 0)<=0: errors.append("bad SZSE source evidence")
            data_path=root/"szse"/str(meta.get("data_file") or "")
            if not data_path.exists(): errors.append("missing SZSE data")
            else:
                if sha256_file(data_path)!=meta.get("data_sha256"): errors.append("SZSE data hash mismatch")
                n,days,codes=validate_rows(data_path,identities,frozen,end,global_seen,errors)
                if n!=int(meta.get("rows") or -1): errors.append("SZSE row-count mismatch")
                szse_rows=n; szse_days=days; szse_codes=codes
        except Exception as exc: errors.append(f"SZSE audit error: {exc}")

    # Both exchanges share the same trading calendar. Empty weekend/holiday source files are allowed,
    # but normalized nonempty trading-day sets must agree and end on the current completed session.
    if sse_days != szse_days: errors.append(f"exchange trading-day mismatch SSE={sorted(sse_days)} SZSE={sorted(szse_days)}")
    if not sse_days or max(sse_days)!=end.isoformat(): errors.append(f"latest normalized session is not {end.isoformat()}")

    # Explicit post-freeze listings must be represented on or after listing if the exchange traded.
    for ex,code in (("SSE","603468"),("SZSE","001232")):
        if (ex,code) in identities:
            observed = code in (sse_codes if ex=="SSE" else szse_codes)
            if not observed: errors.append(f"post-freeze listing has no OHLCV evidence {ex}:{code}")

    report={
        "gate":"FORWARD_OHLCV","pass":not errors,"frozen_coverage_end":frozen.isoformat(),"coverage_end":end.isoformat(),
        "sse_current_identities":len(sse_ids),"szse_current_identities":len(szse_ids),"sse_source_requests":source_requests,
        "sse_rows":sse_rows,"szse_rows":szse_rows,"trading_days":len(sse_days),"first_trading_day":min(sse_days) if sse_days else None,
        "last_trading_day":max(sse_days) if sse_days else None,"unique_rows":len(global_seen),"errors":errors,
        "historical_basis":"Stage2 frozen fingerprint through 2026-07-24; this artifact contains forward delta only","authoritative":False,
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if not errors else 2


if __name__=="__main__": sys.exit(main())
