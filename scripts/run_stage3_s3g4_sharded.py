#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import fitz
import requests

from stage3_earnings_forecast_parser import parse_parent_net_profit_forecast, compare_actual

EXPECTED_FORECAST_COUNT = 51732
SHARD_COUNT = 64
ANNOUNCEMENT_LEDGER_SHA256 = "0eb139572865628283f86c981990e59e076d5ef2a978a5967aace90d553e30dd"
PARSER_BLOB = "4e22de08c5094b64374c03fe646c61d6ca26ad0b"
METHOD = "V3.3.15_S3G4_OFFICIAL_GUIDANCE_SHARDED_EXACT_ISSUER_PIT"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"

INPUT_FIELDS = [
    "exchange","source_code","effective_code","org_id","announcement_id","announcement_title",
    "source_published_at","available_at","source_url","query_response_sha256",
]
SHARD_FIELDS = INPUT_FIELDS + [
    "source_sha256","source_bytes","pdf_pages","fetch_status","fetch_error",
    "parser_status","economic_date","forecast_low_cny","forecast_high_cny","forecast_midpoint_cny",
    "forecast_unit","forecast_sign_inference","matched_label","matched_text",
]
SURPRISE_FIELDS = [
    "exchange","effective_code","issuer_org_id","economic_date","actual_report_family",
    "actual_announcement_id","actual_available_at","actual_source_sha256","actual_parent_net_profit_cny",
    "forecast_announcement_id","forecast_available_at","forecast_source_url","forecast_source_sha256",
    "forecast_low_cny","forecast_high_cny","forecast_midpoint_cny","forecast_status","forecast_sign_inference",
    "surprise_cny","range_position","surprise_direction","expectation_is_strictly_prior","identity_match_mode",
    "expectation_source","actual_source","analyst_consensus_used","methodology_version",
]
_tls = threading.local()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def write_det_gzip(path: Path, fields: list[str], rows: list[dict]) -> None:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=9, mtime=0) as gz:
        txt = io.TextIOWrapper(gz, encoding="utf-8", newline="", write_through=True)
        w = csv.DictWriter(txt, fieldnames=fields, lineterminator="\n")
        w.writeheader(); w.writerows(rows); txt.flush()
    path.write_bytes(buf.getvalue())


def dump_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Referer": "https://www.cninfo.com.cn/"})
        _tls.session = s
    return s


def get_pdf(url: str, attempts: int = 8) -> bytes:
    last = None
    for i in range(attempts):
        try:
            r = session().get(url, timeout=(20, 90))
            r.raise_for_status()
            b = r.content
            if not b.startswith(b"%PDF"):
                raise ValueError(f"not_pdf content_type={r.headers.get('Content-Type')}")
            if len(b) > 40_000_000:
                raise ValueError(f"pdf_too_large bytes={len(b)}")
            return b
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(min(0.5 * (2 ** i), 12.0))
    raise RuntimeError(repr(last))


def shard_of(announcement_id: str) -> int:
    return int(hashlib.sha256(announcement_id.encode("ascii")).hexdigest()[:16], 16) % SHARD_COUNT


def prepare(args) -> int:
    src = Path(args.announcements); out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if sha_file(src) != ANNOUNCEMENT_LEDGER_SHA256:
        raise SystemExit("announcement ledger SHA drift")
    rows = []
    ids = set(); errors = []
    for r in read_gz(src):
        try: cats = json.loads(r["event_categories"])
        except Exception: cats = []
        if "EARNINGS_FORECAST" not in cats or r.get("usable_in_stage2") != "1":
            continue
        aid = r["announcement_id"]
        if aid in ids: errors.append(f"duplicate announcement_id {aid}")
        ids.add(aid)
        url = r["source_url"]
        if not (url.startswith("https://static.cninfo.com.cn/finalpage/") and url.lower().endswith(".pdf")):
            errors.append(f"noncanonical source_url {aid} {url}")
        rows.append({k: r.get(k, "") for k in INPUT_FIELDS})
    rows.sort(key=lambda x: x["announcement_id"])
    if len(rows) != EXPECTED_FORECAST_COUNT:
        errors.append(f"forecast population {len(rows)} != {EXPECTED_FORECAST_COUNT}")
    dist = Counter(shard_of(r["announcement_id"]) for r in rows)
    if set(dist) != set(range(SHARD_COUNT)):
        errors.append(f"shard coverage drift {sorted(dist)}")
    p = out / "stage3_s3g4_frozen_forecast_input.csv.gz"
    write_det_gzip(p, INPUT_FIELDS, rows)
    manifest = {
        "gate":"S3G4_FROZEN_OFFICIAL_FORECAST_INPUT","pass":not errors,"forecast_count":len(rows),
        "announcement_ledger_sha256":ANNOUNCEMENT_LEDGER_SHA256,"shard_count":SHARD_COUNT,
        "shard_population":{str(k):dist[k] for k in range(SHARD_COUNT)},"input_sha256":sha_file(p),
        "source_policy":"CNINFO_OFFICIAL_PDF_ONLY","analyst_consensus_used":False,"errors":errors,
    }
    dump_json(out / "stage3_s3g4_frozen_forecast_input.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2)); return 0 if not errors else 2


def parse_one(r: dict) -> dict:
    base = {k:r.get(k,"") for k in INPUT_FIELDS}
    try:
        raw = get_pdf(r["source_url"])
        digest = sha_bytes(raw)
        with fitz.open(stream=raw, filetype="pdf") as doc:
            pages = doc.page_count
            text = "\n".join(doc[i].get_text("text") or "" for i in range(doc.page_count))
        p = parse_parent_net_profit_forecast(text)
        if p.get("status") not in {"FOUND","FOUND_POINT_ESTIMATE","NOT_FOUND"}:
            raise ValueError(f"unexpected parser status {p.get('status')}")
        return {**base,"source_sha256":digest,"source_bytes":str(len(raw)),"pdf_pages":str(pages),
            "fetch_status":"OK","fetch_error":"","parser_status":p.get("status") or "",
            "economic_date":p.get("economic_date") or "","forecast_low_cny":p.get("low_cny") or "",
            "forecast_high_cny":p.get("high_cny") or "","forecast_midpoint_cny":p.get("midpoint_cny") or "",
            "forecast_unit":p.get("unit") or "","forecast_sign_inference":p.get("sign_inference") or "",
            "matched_label":p.get("matched_label") or "","matched_text":p.get("matched_text") or ""}
    except Exception as exc:
        return {**base,"source_sha256":"","source_bytes":"","pdf_pages":"","fetch_status":"ERROR","fetch_error":repr(exc),
            "parser_status":"ERROR","economic_date":"","forecast_low_cny":"","forecast_high_cny":"","forecast_midpoint_cny":"",
            "forecast_unit":"","forecast_sign_inference":"","matched_label":"","matched_text":""}


def shard(args) -> int:
    idx = int(args.shard_index); count = int(args.shard_count)
    if count != SHARD_COUNT or not (0 <= idx < count): raise SystemExit("invalid shard identity")
    all_rows = list(read_gz(Path(args.input)))
    selected = [r for r in all_rows if shard_of(r["announcement_id"]) == idx]
    selected.sort(key=lambda x:x["announcement_id"])
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    results = []
    workers = max(1, min(int(args.workers), 8))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(parse_one, r):r["announcement_id"] for r in selected}
        for n,fut in enumerate(as_completed(futs),1):
            results.append(fut.result())
            if n % 100 == 0: print(f"shard {idx}: {n}/{len(selected)}", flush=True)
    results.sort(key=lambda x:x["announcement_id"])
    errors = [r for r in results if r["fetch_status"] != "OK" or r["parser_status"] == "ERROR"]
    status_counts = Counter(r["parser_status"] for r in results)
    ledger = out / f"stage3_s3g4_forecast_shard_{idx:02d}.csv.gz"
    write_det_gzip(ledger, SHARD_FIELDS, results)
    manifest = {"gate":"S3G4_OFFICIAL_FORECAST_SHARD","pass":not errors,"shard_index":idx,"shard_count":count,
        "selected_count":len(selected),"output_count":len(results),"parser_status_counts":dict(status_counts),
        "hard_error_count":len(errors),"hard_error_samples":[{"announcement_id":r["announcement_id"],"error":r["fetch_error"]} for r in errors[:20]],
        "parser_blob":PARSER_BLOB,"source_policy":"CNINFO_OFFICIAL_PDF_ONLY","analyst_consensus_used":False,
        "ledger_sha256":sha_file(ledger)}
    dump_json(out / f"stage3_s3g4_forecast_shard_{idx:02d}.json", manifest)
    hashes = {p.name:sha_file(p) for p in sorted(out.iterdir()) if p.is_file()}
    dump_json(out / f"stage3_s3g4_forecast_shard_{idx:02d}_sha256.json", hashes)
    print(json.dumps(manifest, ensure_ascii=False, indent=2)); return 0 if not errors else 2


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def finalize(args) -> int:
    root=Path(args.shards); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    manifests=[]; rows=[]; errors=[]
    for i in range(SHARD_COUNT):
        mp=list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}.json"))
        lp=list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}.csv.gz"))
        hp=list(root.rglob(f"stage3_s3g4_forecast_shard_{i:02d}_sha256.json"))
        if len(mp)!=1 or len(lp)!=1 or len(hp)!=1:
            errors.append(f"shard {i} artifact cardinality manifest={len(mp)} ledger={len(lp)} hashes={len(hp)}");continue
        m=json.loads(mp[0].read_text(encoding="utf-8")); h=json.loads(hp[0].read_text(encoding="utf-8"))
        if m.get("pass") is not True or m.get("shard_index")!=i or m.get("shard_count")!=SHARD_COUNT or m.get("parser_blob")!=PARSER_BLOB:
            errors.append(f"shard {i} manifest contract drift")
        if h.get(lp[0].name)!=sha_file(lp[0]): errors.append(f"shard {i} ledger hash mismatch")
        manifests.append(m); rows.extend(read_gz(lp[0]))
    rows.sort(key=lambda x:x["announcement_id"])
    ids=[r["announcement_id"] for r in rows]
    if len(rows)!=EXPECTED_FORECAST_COUNT:errors.append(f"combined forecast rows {len(rows)} != {EXPECTED_FORECAST_COUNT}")
    if len(set(ids))!=len(ids):errors.append("combined forecast duplicate announcement_id")
    if any(r["fetch_status"]!="OK" or r["parser_status"]=="ERROR" for r in rows):errors.append("hard source/parser errors survived shard gate")
    parsed=[r for r in rows if r["parser_status"] in {"FOUND","FOUND_POINT_ESTIMATE"} and r["economic_date"]]
    by_period=defaultdict(list)
    for f in parsed: by_period[(f["org_id"],f["economic_date"])].append(f)
    for fs in by_period.values(): fs.sort(key=lambda x:(parse_dt(x["available_at"]),x["announcement_id"]))
    docs={r["announcement_id"]:r for r in read_gz(Path(args.financial_documents))}
    actuals=[]
    for r in read_gz(Path(args.financial_values)):
        if r["concept"]!="NET_PROFIT_ATTRIBUTABLE_TO_PARENT":continue
        d=docs.get(r["announcement_id"])
        if not d or d.get("document_status")!="PASS":errors.append(f"actual document missing/not PASS {r['announcement_id']}");continue
        if d.get("issuer_org_id")!=r["issuer_org_id"] or d.get("economic_date")!=r["economic_date"] or d.get("available_at")!=r["available_at"]:
            errors.append(f"actual document/value identity mismatch {r['announcement_id']}");continue
        actuals.append(r)
    output=[]; no_prior=[]
    for r in actuals:
        fs=[f for f in by_period.get((r["issuer_org_id"],r["economic_date"]),[]) if parse_dt(f["available_at"]) < parse_dt(r["available_at"])]
        if not fs:
            no_prior.append((r["announcement_id"],r["issuer_org_id"],r["economic_date"]));continue
        f=fs[-1]
        forecast={"status":f["parser_status"],"low_cny":f["forecast_low_cny"],"high_cny":f["forecast_high_cny"],"midpoint_cny":f["forecast_midpoint_cny"]}
        cmp=compare_actual(forecast,r["normalized_cny_value"])
        output.append({
            "exchange":r["exchange"],"effective_code":r["effective_code"],"issuer_org_id":r["issuer_org_id"],"economic_date":r["economic_date"],"actual_report_family":r["report_family"],
            "actual_announcement_id":r["announcement_id"],"actual_available_at":r["available_at"],"actual_source_sha256":r["source_sha256"],"actual_parent_net_profit_cny":r["normalized_cny_value"],
            "forecast_announcement_id":f["announcement_id"],"forecast_available_at":f["available_at"],"forecast_source_url":f["source_url"],"forecast_source_sha256":f["source_sha256"],
            "forecast_low_cny":f["forecast_low_cny"],"forecast_high_cny":f["forecast_high_cny"],"forecast_midpoint_cny":f["forecast_midpoint_cny"],"forecast_status":f["parser_status"],"forecast_sign_inference":f["forecast_sign_inference"],
            "surprise_cny":cmp["surprise_cny"],"range_position":cmp["range_position"] or "","surprise_direction":cmp["surprise_direction"],"expectation_is_strictly_prior":"1","identity_match_mode":"EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE",
            "expectation_source":"OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF","actual_source":"ORIGINAL_PERIODIC_FILING_PDF","analyst_consensus_used":"0","methodology_version":METHOD})
    output.sort(key=lambda r:(r["actual_available_at"],r["exchange"],r["effective_code"],r["actual_announcement_id"]))
    ledger=out/"stage3_earnings_surprise.csv.gz"; write_det_gzip(ledger,SURPRISE_FIELDS,output)
    forecast_archive=out/"stage3_earnings_forecast_parse_ledger.csv.gz"; write_det_gzip(forecast_archive,SHARD_FIELDS,rows)
    status=Counter(r["parser_status"] for r in rows); identity_orgs={r["org_id"] for r in parsed}; actual_orgs={r["issuer_org_id"] for r in actuals}
    if not output:errors.append("zero surprise observations")
    if any(r["expectation_is_strictly_prior"]!="1" for r in output):errors.append("non-prior expectation output")
    report={"gate":"S3G4_OFFICIAL_EARNINGS_GUIDANCE_SURPRISE_FINAL","pass":not errors,
        "forecast_population":len(rows),"forecast_parser_status_counts":dict(status),"numeric_forecast_versions":len(parsed),
        "numeric_forecast_org_count":len(identity_orgs),"financial_actual_observations":len(actuals),"financial_actual_org_count":len(actual_orgs),
        "surprise_observations":len(output),"actuals_without_prior_numeric_forecast":len(no_prior),"actuals_without_prior_samples":no_prior[:50],
        "forecast_parse_ledger_sha256":sha_file(forecast_archive),"surprise_ledger_sha256":sha_file(ledger),
        "identity_match_mode":"EXACT_ISSUER_ORG_ID_AND_ECONOMIC_DATE","expectation_is_strictly_prior":True,
        "expectation_source":"OFFICIAL_COMPANY_EARNINGS_FORECAST_PDF","actual_source":"ORIGINAL_PERIODIC_FILING_PDF","analyst_consensus_used":False,
        "source_pdf_fetch_completeness":sum(1 for r in rows if r["fetch_status"]=="OK")/EXPECTED_FORECAST_COUNT,
        "parser_blob":PARSER_BLOB,"methodology_version":METHOD,"stage4_alpha_live_locked":True,"errors":errors}
    dump_json(out/"stage3_earnings_surprise_audit.json",report)
    hashes={p.name:sha_file(p) for p in sorted(out.iterdir()) if p.is_file()};dump_json(out/"output_sha256.json",hashes)
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2


def main() -> int:
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("prepare");p.add_argument("--announcements",required=True);p.add_argument("--out",required=True);p.set_defaults(fn=prepare)
    p=sub.add_parser("shard");p.add_argument("--input",required=True);p.add_argument("--shard-index",required=True);p.add_argument("--shard-count",default=str(SHARD_COUNT));p.add_argument("--workers",default="4");p.add_argument("--out",required=True);p.set_defaults(fn=shard)
    p=sub.add_parser("finalize");p.add_argument("--shards",required=True);p.add_argument("--financial-values",required=True);p.add_argument("--financial-documents",required=True);p.add_argument("--out",required=True);p.set_defaults(fn=finalize)
    args=ap.parse_args();return args.fn(args)
if __name__=="__main__":raise SystemExit(main())
