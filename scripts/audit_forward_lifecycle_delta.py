#!/usr/bin/env python3
"""Audit lifecycle freshness as an incremental delta from the frozen Stage2 universe.

Historical lifecycle evidence remains frozen and authoritative for <= coverage_end. This audit
only asks whether the fresh reconciled current universe introduces identity changes after the
freeze that are fully explained. Additions with official listing dates are accepted as LIST
events. Removals fail closed until an explicit official DELIST/code-transition resolver exists.
Name-only changes are recorded but are not security-identity changes.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SEED = ROOT / "data/security_lifecycle/current_list_seed.csv"
CURRENT_MASTER = ROOT / "data/current_master/cn_main_a.csv"
CURRENT_MANIFEST = ROOT / "data/current_master/manifest.json"
RECONCILIATION = ROOT / "data/current_master/reconciliation.json"
STAGE2_FINAL = ROOT / "data/stage2_final/manifest.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def norm_date(value: str) -> date:
    s = (value or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return date.fromisoformat(s)


def main() -> int:
    errors: list[str] = []
    for p in (FROZEN_SEED, CURRENT_MASTER, CURRENT_MANIFEST, RECONCILIATION, STAGE2_FINAL):
        if not p.exists():
            errors.append(f"missing {p.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"gate":"FORWARD_LIFECYCLE","pass":False,"errors":errors},ensure_ascii=False,indent=2))
        return 2

    frozen_rows = read_csv(FROZEN_SEED)
    current_rows = read_csv(CURRENT_MASTER)
    current_manifest = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))
    recon = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    stage2 = json.loads(STAGE2_FINAL.read_text(encoding="utf-8"))

    try:
        coverage_end = date.fromisoformat(str(stage2.get("coverage", {}).get("end") or stage2.get("coverage_end") or ""))
    except Exception:
        errors.append("invalid frozen Stage2 coverage_end")
        coverage_end = date.min
    try:
        as_of = date.fromisoformat(str((current_manifest.get("szse") or {}).get("as_of") or ""))
    except Exception:
        errors.append("invalid current master as_of")
        as_of = date.min

    if current_manifest.get("hard_gate_status") != "PASS_CANDIDATE":
        errors.append("fresh current master is not PASS_CANDIDATE")
    if recon.get("g1_reconciled") is not True:
        errors.append("fresh current master is not independently reconciled")
    if as_of <= coverage_end:
        errors.append(f"current as_of does not advance frozen coverage: {as_of} <= {coverage_end}")

    frozen: dict[tuple[str,str], dict[str,str]] = {}
    for r in frozen_rows:
        key=(r.get("exchange", ""), r.get("code", ""))
        if key in frozen: errors.append(f"duplicate frozen identity {key}")
        frozen[key]=r
    current: dict[tuple[str,str], dict[str,str]] = {}
    for r in current_rows:
        key=(r.get("exchange", ""), r.get("code", ""))
        if key in current: errors.append(f"duplicate current identity {key}")
        current[key]=r

    added_keys = sorted(current.keys() - frozen.keys())
    removed_keys = sorted(frozen.keys() - current.keys())
    if removed_keys:
        errors.append(
            "unresolved current-universe removals require explicit official DELIST/code-transition evidence: "
            + repr(removed_keys[:20])
        )

    additions=[]
    for key in added_keys:
        r=current[key]
        ex,code=key
        try:
            listing=norm_date(r.get("listing_date") or "")
        except Exception:
            errors.append(f"invalid listing_date for added identity {ex}:{code}")
            continue
        if not (coverage_end < listing <= as_of):
            errors.append(f"added identity outside forward window {ex}:{code} listing={listing}")
        source_url=(r.get("source_url") or "").strip()
        payload=(r.get("source_row_json") or "").strip()
        if not source_url or not payload:
            errors.append(f"added identity lacks official row evidence {ex}:{code}")
        else:
            try: json.loads(payload)
            except Exception: errors.append(f"added identity source payload is not JSON {ex}:{code}")
        source_sha=(current_manifest.get(ex.lower()) or {}).get("sha256_raw" if ex=="SSE" else "sha256_all_pages")
        if not isinstance(source_sha,str) or len(source_sha)!=64:
            errors.append(f"missing official source hash for added identity {ex}:{code}")
        additions.append({
            "exchange":ex,"code":code,"name":r.get("name"),"listing_date":listing.isoformat(),
            "source_url":source_url,"source_sha256":source_sha,
        })

    common = sorted(current.keys() & frozen.keys())
    listing_date_mismatches=[]
    name_changes=[]
    for key in common:
        old=frozen[key]; new=current[key]
        try:
            old_date=norm_date(old.get("effective_date") or "")
            new_date=norm_date(new.get("listing_date") or "")
            if old_date != new_date:
                listing_date_mismatches.append({"exchange":key[0],"code":key[1],"frozen":old_date.isoformat(),"current":new_date.isoformat()})
        except Exception:
            errors.append(f"invalid common listing date {key}")
        if (old.get("name") or "") != (new.get("name") or ""):
            name_changes.append({"exchange":key[0],"code":key[1],"frozen_name":old.get("name"),"current_name":new.get("name")})
    if listing_date_mismatches:
        errors.append(f"common identity listing-date drift: {listing_date_mismatches[:20]}")

    report={
        "gate":"FORWARD_LIFECYCLE",
        "pass":not errors,
        "frozen_coverage_end":coverage_end.isoformat() if coverage_end != date.min else None,
        "current_as_of":as_of.isoformat() if as_of != date.min else None,
        "frozen_current_count":len(frozen),
        "fresh_current_count":len(current),
        "added_count":len(added_keys),
        "removed_count":len(removed_keys),
        "additions":additions,
        "removals":[{"exchange":x[0],"code":x[1]} for x in removed_keys],
        "name_change_count":len(name_changes),
        "name_changes":name_changes,
        "listing_date_mismatch_count":len(listing_date_mismatches),
        "errors":errors,
        "identity_policy":"frozen historical lifecycle + explicit forward delta; unresolved removals fail closed",
        "authoritative":False,
    }
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not errors else 2


if __name__=="__main__":
    sys.exit(main())
