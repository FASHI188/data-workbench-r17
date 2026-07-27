#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from stage3_financial_pdf_parser import parse_pdf_bytes

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
METHOD = "CNINFO_ORIGINAL_PDF_PYMUPDF_V1"
NUMERIC_FIELDS = [
    "exchange","source_code","effective_code","issuer_org_id","report_family","economic_date",
    "announcement_id","revision_sequence","source_published_at","effective_session","available_at",
    "concept","raw_value","normalized_cny_value","unit","unit_multiplier","source_url","source_sha256",
    "source_format","extraction_method","methodology_version","page","matched_alias","confidence"
]
DOC_FIELDS = [
    "exchange","source_code","effective_code","issuer_org_id","report_family","economic_date",
    "announcement_id","revision_sequence","source_published_at","effective_session","available_at",
    "canonical_title","canonical_source_url","selected_source_url","selected_source_sha256","selected_source_bytes",
    "tie_candidate_count","tie_resolution","candidate_evidence_json","tier1_found","tier2_found","numeric_observations",
    "document_status","document_error"
]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_shard(announcement_id: str, shards: int) -> int:
    return int(hashlib.sha256(announcement_id.encode()).hexdigest()[:16], 16) % shards


def read_versions(path: Path) -> list[dict]:
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def get_pdf(s: requests.Session, url: str, attempts: int = 6) -> bytes:
    last=None
    for i in range(attempts):
        try:
            r=s.get(url,headers={"User-Agent":UA,"Referer":"https://www.cninfo.com.cn/"},timeout=90)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"not PDF content-type={r.headers.get('Content-Type')} bytes={len(r.content)}")
            return r.content
        except Exception as exc:
            last=exc
            if i+1<attempts: time.sleep(min(0.8*(2**i),10))
    raise RuntimeError(repr(last))


def dec(v: str | None) -> Decimal | None:
    if v in (None,""): return None
    try:return Decimal(str(v))
    except InvalidOperation:return None


def same_value(a: Decimal, b: Decimal) -> bool:
    return abs(a-b)/max(abs(a),abs(b),Decimal("1")) <= Decimal("0.000000001")


def candidate_list(r: dict) -> list[dict]:
    try:
        ids=json.loads(r.get("same_day_tied_top_ids") or "[]")
        titles=json.loads(r.get("same_day_tied_top_titles") or "[]")
        urls=json.loads(r.get("same_day_tied_top_urls") or "[]")
    except Exception:
        ids=titles=urls=[]
    if len(ids)>1 and len(ids)==len(urls):
        return [{"id":str(ids[i]),"title":str(titles[i]) if i<len(titles) else "","url":str(urls[i])} for i in range(len(ids))]
    return [{"id":r["canonical_announcement_id"],"title":r["canonical_title"],"url":r["canonical_source_url"]}]


def resolve_candidates(parsed: list[dict], canonical_id: str) -> tuple[dict | None,str,str | None]:
    if not parsed:return None,"NO_CANDIDATE","no parsed candidate"
    if len(parsed)==1:return parsed[0],"SINGLE_CANONICAL",None
    if any(x.get("error") for x in parsed):
        return None,"TIE_SOURCE_INCOMPLETE","one or more tied candidate PDFs failed"
    shas={x["sha256"] for x in parsed}
    if len(shas)==1:
        chosen=next((x for x in parsed if x["id"]==canonical_id),parsed[-1])
        return chosen,"TIE_IDENTICAL_PDF_SHA",None
    # Different bytes are acceptable only when every overlapping extracted concept agrees.
    conflicts=[]
    concepts=set()
    for x in parsed: concepts.update(x["parsed"]["observations"].keys())
    for c in concepts:
        vals=[]
        for x in parsed:
            o=x["parsed"]["observations"].get(c) or {}
            if o.get("status")=="FOUND":
                v=dec(o.get("normalized_cny_value"))
                if v is not None: vals.append((x["id"],v))
        if len(vals)>1:
            base=vals[0][1]
            if any(not same_value(base,v) for _,v in vals[1:]):
                conflicts.append({"concept":c,"values":[[i,str(v)] for i,v in vals]})
    if conflicts:
        return None,"TIE_VALUE_CONFLICT",json.dumps(conflicts,ensure_ascii=False)
    parsed.sort(key=lambda x:(x["parsed"]["tier1_found"],x["parsed"]["tier2_found"],x["id"]==canonical_id,x["id"]))
    return parsed[-1],"TIE_DIFFERENT_BYTES_VALUES_COMPATIBLE_RICHEST_DOCUMENT",None


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--versions",required=True);ap.add_argument("--shard",type=int,required=True);ap.add_argument("--shards",type=int,required=True);ap.add_argument("--out",required=True);a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[r for r in read_versions(Path(a.versions)) if stable_shard(r["canonical_announcement_id"],a.shards)==a.shard]
    s=requests.Session();numeric=[];docs=[];errors=[];download_bytes=0;tie_counts={}
    for idx,r in enumerate(rows,1):
        candidates=candidate_list(r);parsed_candidates=[]
        for c in candidates:
            ev={"id":c["id"],"title":c["title"],"url":c["url"]}
            try:
                raw=get_pdf(s,c["url"]);download_bytes+=len(raw);p=parse_pdf_bytes(raw)
                ev.update({"sha256":sha(raw),"bytes":len(raw),"parsed":p})
            except Exception as exc:
                ev["error"]=repr(exc)
            parsed_candidates.append(ev)
        chosen,resolution,resolution_error=resolve_candidates(parsed_candidates,r["canonical_announcement_id"])
        tie_counts[resolution]=tie_counts.get(resolution,0)+1
        base={
            "exchange":r["exchange"],"source_code":r["source_code"],"effective_code":r["effective_code"],"issuer_org_id":r["org_id"],
            "report_family":r["report_family"],"economic_date":r["economic_date"],"announcement_id":r["canonical_announcement_id"],
            "revision_sequence":r["revision_sequence"],"source_published_at":r["source_published_at"],"effective_session":r["effective_session"],"available_at":r["available_at"]
        }
        if chosen is None:
            err=resolution_error or resolution
            errors.append(f"{r['canonical_announcement_id']} {resolution}: {err}")
            docs.append({**base,"canonical_title":r["canonical_title"],"canonical_source_url":r["canonical_source_url"],"selected_source_url":"","selected_source_sha256":"","selected_source_bytes":"","tie_candidate_count":str(len(candidates)),"tie_resolution":resolution,"candidate_evidence_json":json.dumps(parsed_candidates,ensure_ascii=False,default=str),"tier1_found":"0","tier2_found":"0","numeric_observations":"0","document_status":"ERROR","document_error":err})
            continue
        p=chosen["parsed"]
        found=0
        for concept,o in p["observations"].items():
            if o.get("status")!="FOUND":continue
            found+=1
            numeric.append({**base,"concept":concept,"raw_value":o.get("raw_value") or "","normalized_cny_value":o.get("normalized_cny_value") or "","unit":o.get("unit") or "","unit_multiplier":o.get("unit_multiplier") or "","source_url":chosen["url"],"source_sha256":chosen["sha256"],"source_format":"PDF","extraction_method":METHOD,"methodology_version":"V3.3.1","page":o.get("page") or "","matched_alias":o.get("matched_alias") or "","confidence":o.get("confidence") or ""})
        slim=[]
        for x in parsed_candidates:
            y={k:x.get(k) for k in ("id","title","url","sha256","bytes","error") if x.get(k) not in (None,"")}
            if x.get("parsed"):
                y.update({"tier1_found":x["parsed"]["tier1_found"],"tier2_found":x["parsed"]["tier2_found"]})
            slim.append(y)
        docs.append({**base,"canonical_title":r["canonical_title"],"canonical_source_url":r["canonical_source_url"],"selected_source_url":chosen["url"],"selected_source_sha256":chosen["sha256"],"selected_source_bytes":str(chosen["bytes"]),"tie_candidate_count":str(len(candidates)),"tie_resolution":resolution,"candidate_evidence_json":json.dumps(slim,ensure_ascii=False),"tier1_found":str(p["tier1_found"]),"tier2_found":str(p["tier2_found"]),"numeric_observations":str(found),"document_status":"PASS","document_error":""})
        if idx%50==0:print(f"shard {a.shard}/{a.shards} {idx}/{len(rows)} docs bytes={download_bytes}",flush=True)
        time.sleep(0.03)
    np=out/f"financial_values_shard{a.shard:02d}.csv.gz";dp=out/f"financial_documents_shard{a.shard:02d}.csv.gz"
    with gzip.open(np,"wt",encoding="utf-8",newline="",compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=NUMERIC_FIELDS);w.writeheader();w.writerows(numeric)
    with gzip.open(dp,"wt",encoding="utf-8",newline="",compresslevel=9) as f:w=csv.DictWriter(f,fieldnames=DOC_FIELDS);w.writeheader();w.writerows(docs)
    manifest={"gate":"S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD","shard":a.shard,"shards":a.shards,"selected_versions":len(rows),"document_rows":len(docs),"numeric_rows":len(numeric),"download_bytes":download_bytes,"tie_resolution_counts":tie_counts,"error_count":len(errors),"errors":errors[:200],"numeric_file":np.name,"numeric_sha256":sha(np.read_bytes()),"documents_file":dp.name,"documents_sha256":sha(dp.read_bytes())}
    (out/f"financial_extract_shard{a.shard:02d}.manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:manifest[k] for k in ("shard","selected_versions","numeric_rows","download_bytes","tie_resolution_counts","error_count")},ensure_ascii=False))
    return 0 if not errors else 2

if __name__=="__main__":raise SystemExit(main())
