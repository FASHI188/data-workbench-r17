#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

from stage3_financial_pdf_parser import parse_pdf_bytes, TIER1_ALIASES

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
CORE = list(TIER1_ALIASES)


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get_pdf(s: requests.Session, url: str, attempts: int = 5) -> bytes:
    last = None
    for i in range(attempts):
        try:
            r=s.get(url,headers={"User-Agent":UA,"Referer":"https://www.cninfo.com.cn/"},timeout=90)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"not PDF type={r.headers.get('Content-Type')} bytes={len(r.content)}")
            return r.content
        except Exception as exc:
            last=exc
            if i+1<attempts:
                time.sleep(min(0.8*(2**i),8))
    raise RuntimeError(repr(last))


def stable_sample(groups: dict, per_cell: int, seed: int) -> list[dict]:
    out=[]
    for key in sorted(groups):
        vals=sorted(groups[key],key=lambda r:r["canonical_announcement_id"])
        rng=random.Random(f"{seed}|{key}")
        if len(vals)<=per_cell:
            take=vals
        else:
            take=rng.sample(vals,per_cell)
        out.extend(take)
    return out


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--versions",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--per-cell",type=int,default=2)
    ap.add_argument("--seed",type=int,default=20260727)
    a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=read_versions(Path(a.versions))
    groups=defaultdict(list)
    for r in rows:
        year=r["economic_date"][:4]
        groups[(year,r["report_family"],r["exchange"])].append(r)
    sample=stable_sample(groups,a.per_cell,a.seed)
    s=requests.Session();results=[];errors=[];coverage=Counter();cell_stats=defaultdict(lambda:Counter())
    total_bytes=0
    for idx,r in enumerate(sample,1):
        key=(r["economic_date"][:4],r["report_family"],r["exchange"])
        rec={k:r.get(k) for k in ("exchange","source_code","effective_code","org_id","report_family","economic_date","canonical_announcement_id","canonical_title","canonical_source_url")}
        try:
            raw=get_pdf(s,r["canonical_source_url"])
            total_bytes+=len(raw)
            parsed=parse_pdf_bytes(raw)
            found=[k for k in CORE if parsed["observations"][k]["status"]=="FOUND"]
            for k in found:coverage[k]+=1
            cell_stats[key]["docs"]+=1
            cell_stats[key]["tier1_found_sum"]+=len(found)
            rec.update({"status":"PASS","bytes":len(raw),"sha256":sha(raw),"tier1_found":len(found),"found_concepts":found,"observations":parsed["observations"]})
        except Exception as exc:
            errors.append(f"{r['canonical_announcement_id']}: {exc!r}")
            cell_stats[key]["errors"]+=1
            rec.update({"status":"ERROR","error":repr(exc)})
        results.append(rec)
        if idx%25==0: print(f"probe {idx}/{len(sample)}",flush=True)
        time.sleep(0.04)

    ok=sum(x["status"]=="PASS" for x in results)
    core_rates={k:(coverage[k]/ok if ok else 0) for k in CORE}
    cell_rows=[];bad_cells=[]
    for key,st in sorted(cell_stats.items()):
        docs=st["docs"];avg=(st["tier1_found_sum"]/(docs*len(CORE)) if docs else 0)
        row={"year":key[0],"family":key[1],"exchange":key[2],"docs":docs,"errors":st["errors"],"mean_tier1_coverage":avg}
        cell_rows.append(row)
        if docs and avg < 0.50:bad_cells.append(row)
    # This probe is intentionally permissive on concept applicability (banks do not
    # expose all industrial concepts), but it must reject source/download failure or
    # a systematic cell where fewer than half of the six core metrics are extractable.
    fatal=[]
    if len(errors)>max(2,int(len(sample)*0.01)):
        fatal.append(f"download/parse errors {len(errors)} exceed 1%/2-doc allowance")
    if bad_cells:
        fatal.append(f"cells below 50% core coverage: {bad_cells[:20]} count={len(bad_cells)}")
    report={
        "gate":"S3G1I_STRATIFIED_ORIGINAL_PDF_POPULATION_PROBE",
        "pass":not fatal,
        "versions_total":len(rows),"strata":len(groups),"sample_docs":len(sample),"successful_docs":ok,
        "total_download_bytes":total_bytes,"core_concept_rates":core_rates,"cell_stats":cell_rows,
        "bad_cells":bad_cells,"sample_results":results,"nonfatal_document_errors":errors,"errors":fatal
    }
    (out/"stage3_financial_pdf_population_probe.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("gate","pass","versions_total","strata","sample_docs","successful_docs","total_download_bytes","core_concept_rates","bad_cells","errors")},ensure_ascii=False,indent=2))
    return 0 if not fatal else 2

if __name__=="__main__": raise SystemExit(main())
