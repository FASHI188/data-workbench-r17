#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

TRANSITION_REPAIRED = {0, 1, 15}
INSTRUMENT_REPAIRED = {11}
EXPECTED_SHARDS = set(range(16))
EXPECTED_IDENTITIES = 3402


def find_manifest(root: Path, shard: int) -> Path:
    xs = list(root.rglob(f"announcement_ledger_shard{shard:02d}.manifest.json"))
    if len(xs) != 1:
        raise RuntimeError(f"expected exactly one manifest for shard {shard} under {root}, got {len(xs)}")
    return xs[0]


def find_data(root: Path, shard: int) -> Path:
    xs = list(root.rglob(f"announcement_ledger_shard{shard:02d}.csv.gz"))
    if len(xs) != 1:
        raise RuntimeError(f"expected exactly one data file for shard {shard} under {root}, got {len(xs)}")
    return xs[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original-root", required=True)
    ap.add_argument("--transition-repair-root", required=True)
    ap.add_argument("--instrument-repair-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    original = Path(a.original_root)
    transition = Path(a.transition_repair_root)
    instrument = Path(a.instrument_repair_root)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    chosen = []
    total_identities = 0
    stock_shas = set()
    repair_alias_rows = 0
    non_equity_rows = 0

    for shard in sorted(EXPECTED_SHARDS):
        if shard in TRANSITION_REPAIRED:
            source_root = transition
            expected_gate = "S3G2_ANNOUNCEMENT_LEDGER_SHARD_V2"
            source_label = "TRANSITION_REPAIRED_V2"
        elif shard in INSTRUMENT_REPAIRED:
            source_root = instrument
            expected_gate = "S3G2_ANNOUNCEMENT_LEDGER_SHARD_V3"
            source_label = "INSTRUMENT_REPAIRED_V3"
        else:
            source_root = original
            expected_gate = "S3G2_ANNOUNCEMENT_LEDGER_SHARD"
            source_label = "ORIGINAL_V1"
        try:
            mp = find_manifest(source_root, shard)
            dp = find_data(source_root, shard)
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"shard {shard}: {exc}")
            continue
        if int(m.get("shard", -1)) != shard or int(m.get("shards", -1)) != 16:
            errors.append(f"shard identity mismatch {shard}: {m.get('shard')}/{m.get('shards')}")
        if m.get("errors"):
            errors.append(f"chosen shard {shard} has errors: {m.get('errors')[:10]}")
        if m.get("gate") != expected_gate:
            errors.append(f"chosen shard {shard} gate {m.get('gate')} != {expected_gate}")
        total_identities += int(m.get("security_identities") or 0)
        stock_shas.add(str(m.get("stock_map_sha256") or ""))
        repair_alias_rows += int(m.get("registered_transition_alias_rows") or 0)
        non_equity_rows += int(m.get("same_issuer_non_equity_instrument_rows") or 0)
        shutil.copy2(mp, out / mp.name)
        shutil.copy2(dp, out / dp.name)
        chosen.append({
            "shard": shard,
            "source": source_label,
            "security_identities": int(m.get("security_identities") or 0),
            "rows": int(m.get("rows") or 0),
            "registered_transition_alias_rows": int(m.get("registered_transition_alias_rows") or 0),
            "same_issuer_non_equity_instrument_rows": int(m.get("same_issuer_non_equity_instrument_rows") or 0),
            "data_sha256": m.get("data_sha256"),
        })

    if {x["shard"] for x in chosen} != EXPECTED_SHARDS:
        errors.append(f"assembled shard set incomplete: {[x['shard'] for x in chosen]}")
    if total_identities != EXPECTED_IDENTITIES:
        errors.append(f"assembled security identities {total_identities} != {EXPECTED_IDENTITIES}")
    if len(stock_shas) != 1:
        errors.append(f"stock map SHA differs across chosen shards: {sorted(stock_shas)}")
    if repair_alias_rows < 2:
        errors.append(f"expected registered transition aliases, got {repair_alias_rows}")
    if non_equity_rows < 1:
        errors.append("expected at least one independently verified same-issuer non-equity instrument row")

    report = {
        "gate": "S3G2_ANNOUNCEMENT_MIXED_SHARD_ASSEMBLY_V2",
        "pass": not errors,
        "transition_repaired_shards": sorted(TRANSITION_REPAIRED),
        "instrument_repaired_shards": sorted(INSTRUMENT_REPAIRED),
        "chosen_shards": chosen,
        "security_identity_count": total_identities,
        "registered_transition_alias_rows": repair_alias_rows,
        "same_issuer_non_equity_instrument_rows": non_equity_rows,
        "stock_map_sha256": next(iter(stock_shas)) if len(stock_shas) == 1 else None,
        "errors": errors,
    }
    (out / "stage3_announcement_repair_assembly_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
