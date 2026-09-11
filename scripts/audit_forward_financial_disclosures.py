#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def read_gz(path: Path) -> list[dict]:
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f: return list(csv.DictReader(f))
def evidence_has_source_sha(raw: str) -> bool:
    try: arr=json.loads(raw or "[]")
    except Exception: return False
    return any(isinstance(x,dict) and bool(x.get("sha256")) for x in arr)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--source-root",required=True); ap.add_argument("--versions",required=True); ap.add_argument("--extract-root",required=True); ap.add_argument("--out",required=True); args=ap.parse_args()
    src=Path(args.source_root); ext=Path(args.extract_root); errors=[]
    smp=src/"forward_disclosure_source_manifest.json"; sm=json.loads(smp.read_text(encoding="utf-8"))
    if sm.get("pass") is not True or sm.get("errors"): errors.append("source ledger gate not clean PASS")
    annp=src/"forward_announcement_ledger.csv.gz"; filp=src/"forward_periodic_filing_ledger.csv.gz"
    if sha(annp.read_bytes()) != sm.get("announcement_sha256"): errors.append("announcement ledger hash mismatch")
    if sha(filp.read_bytes()) != sm.get("filing_sha256"): errors.append("filing ledger hash mismatch")
    anns=read_gz(annp); filings=read_gz(filp); versions=read_gz(Path(args.versions))
    for r in anns:
        if not r.get("announcement_id") or not r.get("query_response_sha256"): errors.append(f"announcement identity/hash missing {r.get('announcement_id')}")
        if r.get("effective_session") and r["effective_session"] <= r.get("source_published_date",""): errors.append(f"same-day announcement leakage {r.get('announcement_id')}")
    for r in filings:
        if r.get("effective_session") and r["effective_session"] <= r.get("source_published_at",""): errors.append(f"same-day filing leakage {r.get('announcement_id')}")
    manifests=sorted(ext.rglob("financial_extract_shard*.manifest.json")); docs_files=sorted(ext.rglob("financial_documents_shard*.csv.gz")); numeric_files=sorted(ext.rglob("financial_values_shard*.csv.gz"))
    if len(manifests)!=8: errors.append(f"expected 8 extractor manifests got {len(manifests)}")
    if len(docs_files)!=8: errors.append(f"expected 8 document files got {len(docs_files)}")
    if len(numeric_files)!=8: errors.append(f"expected 8 numeric files got {len(numeric_files)}")
    selected_total=document_total=numeric_total=retained_errors=0; docs=[]; numeric=[]
    for mp in manifests:
        m=json.loads(mp.read_text(encoding="utf-8"))
        if m.get("gate")!="S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_30": errors.append(f"wrong extractor gate {mp.name}:{m.get('gate')}")
        if m.get("runtime_generation")!="V17.30": errors.append(f"wrong runtime generation {mp.name}:{m.get('runtime_generation')}")
        selected_total+=int(m.get("selected_versions",0)); document_total+=int(m.get("document_rows",0)); numeric_total+=int(m.get("numeric_rows",0)); retained_errors+=int(m.get("error_count",0))
    for p in docs_files: docs.extend(read_gz(p))
    for p in numeric_files: numeric.extend(read_gz(p))
    if selected_total!=len(versions): errors.append(f"selected versions mismatch manifests={selected_total} versions={len(versions)}")
    if document_total!=len(versions) or len(docs)!=len(versions): errors.append(f"document completeness mismatch manifest={document_total} docs={len(docs)} versions={len(versions)}")
    version_ids=[r.get("canonical_announcement_id","") for r in versions]; doc_ids=[r.get("announcement_id","") for r in docs]
    if sorted(version_ids)!=sorted(doc_ids): errors.append("document announcement-id population differs from selected versions")
    if len(doc_ids)!=len(set(doc_ids)): errors.append("duplicate financial document announcement id")
    parser_missing=[]; source_missing=[]
    for d in docs:
        status=d.get("document_status")
        if status=="PASS":
            if not d.get("selected_source_sha256") or not d.get("selected_source_url"): source_missing.append(str(d.get("announcement_id")))
        elif status=="ERROR":
            if not d.get("document_error"): parser_missing.append(str(d.get("announcement_id")))
            if not evidence_has_source_sha(d.get("candidate_evidence_json","")): source_missing.append(str(d.get("announcement_id")))
        else: parser_missing.append(str(d.get("announcement_id")))
    if parser_missing: errors.append(f"financial docs missing explicit PASS/retained ERROR state: {parser_missing[:30]} count={len(parser_missing)}")
    if source_missing: errors.append(f"financial docs without original PDF source SHA: {source_missing[:30]} count={len(source_missing)}")
    for n in numeric:
        if n.get("extraction_method")!="CNINFO_ORIGINAL_PDF_PYMUPDF_V20_V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION": errors.append(f"numeric row wrong extraction method aid={n.get('announcement_id')}"); break
        if n.get("methodology_version")!="V3.3.14-V17.30": errors.append(f"numeric row wrong methodology aid={n.get('announcement_id')}"); break
        if not n.get("source_sha256"): errors.append(f"numeric row missing source sha aid={n.get('announcement_id')}"); break
    result={"gate":"FORWARD_FINANCIAL_AND_ANNOUNCEMENT_FEATURE_FRESHNESS","pass":not errors,"frozen_coverage_end":sm.get("frozen_coverage_end"),"coverage_start":sm.get("coverage_start"),"coverage_end":sm.get("coverage_end"),"announcement_rows":len(anns),"filing_rows":len(filings),"selected_financial_versions":len(versions),"financial_document_rows":len(docs),"financial_numeric_rows":len(numeric),"retained_financial_document_errors":retained_errors,"all_selected_reports_have_original_pdf_source_sha":not source_missing,"retained_errors_are_missing_not_numeric_truth":True,"announcement_metadata_only_no_title_scalar_inference":True,"v17_30_runtime_generation_verified":not any("runtime generation" in e or "extractor gate" in e for e in errors),"errors":errors,"authoritative":False}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if not errors else 2
if __name__ == "__main__": raise SystemExit(main())
