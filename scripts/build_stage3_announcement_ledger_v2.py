#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
from datetime import date
from pathlib import Path

import requests

import build_stage3_announcement_ledger as base

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "exchange","query_code","code","org_id","event_category","announcement_id",
    "announcement_title","source_published_date","announcement_time_raw","source_url",
    "query_page","query_response_sha256"
]


def load_transitions() -> list[dict]:
    return json.loads((ROOT / "config/security_code_transitions.json").read_text(encoding="utf-8"))


def registered_transition_alias(
    exchange: str,
    query_code: str,
    returned_code: str,
    published_date: str,
    transitions: list[dict],
) -> dict | None:
    if query_code == returned_code:
        return None
    if not published_date:
        return None
    try:
        pub = date.fromisoformat(published_date)
    except ValueError:
        return None
    for t in transitions:
        if (
            str(t.get("exchange")) == exchange
            and str(t.get("new_code")) == query_code
            and str(t.get("old_code")) == returned_code
        ):
            eff = date.fromisoformat(str(t["effective_date"]))
            # The successor-code query window starts at the effective date.  A
            # returned predecessor code is therefore admissible only at/after
            # the independently frozen transition boundary.  No generic aliasing.
            if pub >= eff:
                return t
    return None


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--shard",type=int,required=True)
    ap.add_argument("--shards",type=int,default=16)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    if not (0 <= a.shard < a.shards):
        raise ValueError("invalid shard")
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    transitions=load_transitions()
    secs=[r for r in base.intervals() if base.stable_shard(r["exchange"],r["code"],a.shards)==a.shard]
    s=requests.Session()
    smr=s.get(base.STOCKMAP,headers={"User-Agent":base.UA,"Referer":"https://www.cninfo.com.cn/"},timeout=60)
    smr.raise_for_status()
    sl=smr.json().get("stockList") or []
    sm={str(x.get("code")):str(x.get("orgId")) for x in sl if x.get("code") and x.get("orgId")}
    rows=[];req=[];errors=[];totals={k:0 for k in base.CATEGORIES}
    alias_rows=[]

    for i,sec in enumerate(secs,1):
        query_code=sec["code"];org=sm.get(query_code);wa,wb=base.window(sec)
        if not org:
            errors.append(f"missing orgId {sec['exchange']}:{query_code}")
            continue
        for label,cat in base.CATEGORIES.items():
            try:
                raw,obj=base.post(s,base.payload(query_code,org,cat,wa,wb,1))
                total=int(obj.get("totalAnnouncement") or 0)
                pages=max(1,math.ceil(total/base.PAGE))
                packs=[(1,raw,obj)]
                for pn in range(2,pages+1):
                    packs.append((pn,*base.post(s,base.payload(query_code,org,cat,wa,wb,pn))))
                seen=set()
                for pn,rb,ob in packs:
                    anns=ob.get("announcements") or []
                    req.append({
                        "exchange":sec["exchange"],"code":query_code,"category":label,
                        "page":pn,"total":total,"rows":len(anns),"sha256":base.sha(rb)
                    })
                    for x in anns:
                        aid=str(x.get("announcementId") or "")
                        returned_code=str(x.get("secCode") or "")
                        if not aid:
                            errors.append(f"missing aid {query_code} {label}")
                            continue
                        pub=base.pubdate(x)
                        transition=None
                        if returned_code != query_code:
                            transition=registered_transition_alias(
                                sec["exchange"],query_code,returned_code,pub,transitions
                            )
                            if transition is None:
                                errors.append(
                                    f"unregistered code mismatch {sec['exchange']}:{query_code}->{returned_code} "
                                    f"aid={aid} pub={pub}"
                                )
                                continue
                        k=(returned_code,aid,label)
                        if k in seen:
                            continue
                        seen.add(k)
                        u=str(x.get("adjunctUrl") or "").lstrip("/")
                        rows.append({
                            "exchange":sec["exchange"],
                            "query_code":query_code,
                            "code":returned_code,
                            "org_id":org,
                            "event_category":label,
                            "announcement_id":aid,
                            "announcement_title":str(x.get("announcementTitle") or ""),
                            "source_published_date":pub,
                            "announcement_time_raw":str(x.get("announcementTime") or ""),
                            "source_url":base.STATIC+u if u else "",
                            "query_page":str(pn),
                            "query_response_sha256":base.sha(rb),
                        })
                        if transition is not None:
                            alias_rows.append({
                                "exchange":sec["exchange"],"query_code":query_code,
                                "returned_code":returned_code,"announcement_id":aid,
                                "publication_date":pub,"effective_date":transition["effective_date"],
                                "transition_source_sha256":transition.get("source_sha256"),
                            })
                totals[label]+=total
            except Exception as exc:
                errors.append(f"{sec['exchange']}:{query_code} {label}: {exc!r}")
            time.sleep(.02)
        if i%30==0:
            print(f"shard {a.shard}/{a.shards} {i}/{len(secs)}",flush=True)

    rows.sort(key=lambda r:(r["source_published_date"],r["exchange"],r["code"],r["announcement_id"],r["event_category"]))
    p=out/f"announcement_ledger_shard{a.shard:02d}.csv.gz"
    with gzip.open(p,"wt",encoding="utf-8",newline="",compresslevel=9) as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    m={
        "gate":"S3G2_ANNOUNCEMENT_LEDGER_SHARD_V2",
        "shard":a.shard,"shards":a.shards,"security_identities":len(secs),
        "rows":len(rows),"query_pages":len(req),"category_totals":totals,
        "stock_map_sha256":base.sha(smr.content),"data_sha256":base.sha(p.read_bytes()),
        "registered_transition_alias_rows":len(alias_rows),
        "registered_transition_alias_samples":alias_rows[:100],
        "errors":errors,
    }
    (out/f"announcement_ledger_shard{a.shard:02d}.manifest.json").write_text(
        json.dumps(m,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print(json.dumps({
        "shard":a.shard,"securities":len(secs),"rows":len(rows),"pages":len(req),
        "transition_alias_rows":len(alias_rows),"errors":len(errors)
    },ensure_ascii=False))
    return 0 if not errors else 2


if __name__=="__main__":
    raise SystemExit(main())
