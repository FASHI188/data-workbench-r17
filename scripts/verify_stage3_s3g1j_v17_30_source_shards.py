#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_GATE="S3G1J_FINANCIAL_PDF_EXTRACTION_SHARD_V17_30"
EXPECTED_RUNTIME="V17.30"
EXPECTED_METHOD="CNINFO_ORIGINAL_PDF_PYMUPDF_V20_V17_30_EXACT_SOURCE_CROSS_PAGE_GROUP_EQUITY_PRODUCTION"
EXPECTED_METHODOLOGY="V3.3.14-V17.30"
EXPECTED_SHARDS=64
EXPECTED_DOCUMENTS=121354
EXPECTED_NUMERIC=1051826
EXPECTED_ERRORS=1362


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def parse_hash_ledger(path: Path) -> dict[str,str]:
    rows={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw=raw.strip()
        if not raw:
            continue
        parts=raw.split(maxsplit=1)
        if len(parts)!=2:
            raise ValueError(f"invalid hash-ledger line {path}: {raw}")
        digest,name=parts
        name=name.lstrip(" *")
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise ValueError(f"invalid digest in {path}: {digest}")
        if name in rows:
            raise ValueError(f"duplicate hash-ledger path {path}: {name}")
        rows[name]=digest.lower()
    if not rows:
        raise ValueError(f"empty hash ledger {path}")
    return rows


def verify(root: Path) -> dict:
    manifests=sorted(root.rglob("financial_extract_shard*.manifest.json"))
    if len(manifests)!=EXPECTED_SHARDS:
        raise ValueError(f"manifest count expected={EXPECTED_SHARDS} actual={len(manifests)}")
    seen=set()
    total_docs=total_numeric=total_errors=0
    shard_rows=[]
    for manifest_path in manifests:
        artifact_dir=manifest_path.parent
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        shard=int(manifest.get("shard",-1))
        if shard in seen:
            raise ValueError(f"duplicate shard {shard}")
        seen.add(shard)
        if int(manifest.get("shards",-1))!=EXPECTED_SHARDS:
            raise ValueError(f"shard {shard}: shard-count drift")
        if manifest.get("gate")!=EXPECTED_GATE:
            raise ValueError(f"shard {shard}: gate drift")
        if manifest.get("runtime_generation")!=EXPECTED_RUNTIME:
            raise ValueError(f"shard {shard}: runtime drift")
        if manifest.get("parser_method")!=EXPECTED_METHOD:
            raise ValueError(f"shard {shard}: parser method drift")
        if manifest.get("methodology_version")!=EXPECTED_METHODOLOGY:
            raise ValueError(f"shard {shard}: methodology drift")
        if manifest.get("source_format")!="PDF":
            raise ValueError(f"shard {shard}: source format drift")
        if manifest.get("original_pdf_authority") is not True:
            raise ValueError(f"shard {shard}: original-PDF authority missing")
        if manifest.get("current_f10_historical_backfill_used") is not False:
            raise ValueError(f"shard {shard}: current F10 backfill boundary changed")
        if manifest.get("stage4_alpha_locked") is not True:
            raise ValueError(f"shard {shard}: Stage4 lock missing")
        docs=int(manifest.get("document_rows",-1))
        if "numeric_rows" not in manifest:
            raise ValueError(f"shard {shard}: missing numeric_rows")
        numeric=int(manifest["numeric_rows"])
        errors=int(manifest.get("error_count",-1))
        selected=int(manifest.get("selected_versions",-2))
        if docs<=0 or docs!=selected:
            raise ValueError(f"shard {shard}: document/selected count drift")
        if numeric<0:
            raise ValueError(f"shard {shard}: invalid numeric_rows {numeric}")
        if errors!=len(manifest.get("errors") or []):
            raise ValueError(f"shard {shard}: error ledger length drift")
        ledgers=list(artifact_dir.glob("output_sha256.txt"))
        if len(ledgers)!=1:
            raise ValueError(f"shard {shard}: expected one output_sha256.txt")
        hashes=parse_hash_ledger(ledgers[0])
        checked=0
        for relative,expected in hashes.items():
            target=artifact_dir/relative
            if not target.is_file():
                raise ValueError(f"shard {shard}: missing hashed file {relative}")
            actual=sha256(target)
            if actual!=expected:
                raise ValueError(f"shard {shard}: hash mismatch {relative} expected={expected} actual={actual}")
            checked+=1
        total_docs+=docs
        total_numeric+=numeric
        total_errors+=errors
        shard_rows.append({
            "shard":shard,"document_rows":docs,"numeric_rows":numeric,
            "error_count":errors,"hashed_files_verified":checked,
            "manifest_sha256":sha256(manifest_path),"hash_ledger_sha256":sha256(ledgers[0]),
        })
    if seen!=set(range(EXPECTED_SHARDS)):
        raise ValueError(f"shard index coverage drift {sorted(seen)}")
    if total_docs!=EXPECTED_DOCUMENTS:
        raise ValueError(f"document sum expected={EXPECTED_DOCUMENTS} actual={total_docs}")
    if total_numeric!=EXPECTED_NUMERIC:
        raise ValueError(f"numeric sum expected={EXPECTED_NUMERIC} actual={total_numeric}")
    if total_errors!=EXPECTED_ERRORS:
        raise ValueError(f"error sum expected={EXPECTED_ERRORS} actual={total_errors}")
    return {
        "gate":"S3G1J_V17_30_SOURCE_SHARD_INDEPENDENT_VERIFY_V1",
        "shard_count":EXPECTED_SHARDS,
        "document_rows":total_docs,
        "numeric_rows":total_numeric,
        "document_errors":total_errors,
        "shards":sorted(shard_rows,key=lambda x:x["shard"]),
        "all_output_sha256_ledgers_recomputed":True,
        "pass":True,"errors":[],
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True)
    ap.add_argument("--report",required=True)
    args=ap.parse_args()
    out=Path(args.report)
    try:
        report=verify(Path(args.root))
        code=0
    except Exception as exc:
        report={"gate":"S3G1J_V17_30_SOURCE_SHARD_INDEPENDENT_VERIFY_V1","pass":False,"errors":[str(exc)]}
        code=1
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return code


if __name__=="__main__":
    raise SystemExit(main())
