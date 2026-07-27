#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_one(root: Path, name: str) -> Path:
    xs = list(root.rglob(name))
    if len(xs) != 1:
        raise ValueError(f"expected exactly one {name} under {root}, got {len(xs)}")
    return xs[0]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sums", required=True)
    ap.add_argument("--g2", required=True)
    ap.add_argument("--g3", required=True)
    ap.add_argument("--g4", required=True)
    ap.add_argument("--g5", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    manifest_path = Path(a.manifest)
    sums_path = Path(a.sums)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    m = load(manifest_path)
    basis = m.get("fingerprint_basis") or {}
    gates = basis.get("gates") or {}
    checks = basis.get("cross_gate_checks") or {}

    canonical = json.dumps(
        basis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fp = hashlib.sha256(canonical).hexdigest()
    if fp != m.get("stage2_dataset_fingerprint"):
        errors.append(f"canonical fingerprint mismatch computed={fp} manifest={m.get('stage2_dataset_fingerprint')}")

    sums = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, key = line.split(None, 1)
        sums[key.strip()] = digest.strip()
    manifest_sha = sha256_file(manifest_path)
    if sums.get("manifest.json") != manifest_sha:
        errors.append(f"manifest SHA mismatch sums={sums.get('manifest.json')} actual={manifest_sha}")
    if sums.get("canonical:stage2-fingerprint-basis") != fp:
        errors.append("SHA256SUMS canonical fingerprint mismatch")

    if m.get("version") != "V3.2.25-stage2-final-freeze":
        errors.append(f"unexpected version {m.get('version')}")
    if m.get("status") != "PASS" or m.get("all_hard_gates_pass") is not True or m.get("alpha_training_allowed") is not True:
        errors.append("final manifest is not an enabled PASS freeze")
    if m.get("errors"):
        errors.append(f"manifest errors not empty: {m.get('errors')}")

    # G1 is unchanged from V3.2.24; the workflow independently verifies its run/artifact digest.
    g2 = load(find_one(Path(a.g2), "g2_audit.json"))
    g3 = load(find_one(Path(a.g3), "g3_audit.json"))
    g3id = load(find_one(Path(a.g3), "g3_code_identity_audit.json"))
    g4 = load(find_one(Path(a.g4), "g4_audit.json"))
    g5 = load(find_one(Path(a.g5), "g5_audit.json"))

    def require(cond: bool, msg: str):
        if not cond:
            errors.append(msg)

    require(g2.get("pass") is True and not g2.get("errors"), "G2 audit is not clean PASS")
    require(g2.get("current_open_interval_count") == 3191, "G2 current open count != 3191")
    require(g2.get("closed_interval_count") == 292, "G2 closed interval count != 292")
    require(g2.get("total_intervals") == 3483, "G2 interval count != 3483")
    require(g2.get("code_transitions") == 3, "G2 code transition count != 3")
    g2_intervals = find_one(Path(a.g2), "security_intervals.csv")
    require(sha256_file(g2_intervals) == gates["G2"].get("security_intervals_sha256"), "G2 security interval SHA mismatch")

    require(g3.get("pass") is True and not g3.get("errors"), "G3 audit is not clean PASS")
    require(g3.get("total_rows") == 8038444, "G3 total rows != 8,038,444")
    require(g3.get("trading_days") == 2808, "G3 trading days != 2,808")
    require(g3.get("dataset_fingerprint") == gates["G3"].get("dataset_fingerprint"), "G3 dataset fingerprint mismatch")
    require(g3id.get("pass") is True and not g3id.get("errors"), "G3 code-time identity audit failed")
    transitions = g3id.get("transitions") or []
    require(len(transitions) == 3, "G3 identity audit did not check exactly 3 transitions")
    target = [x for x in transitions if x.get("exchange") == "SSE" and x.get("old_code") == "601313" and x.get("new_code") == "601360"]
    require(len(target) == 1, "G3 identity audit missing 601313->601360")
    if target:
        t = target[0]
        require(t.get("effective_date") == "2018-02-28", "601313 transition effective date mismatch")
        require(t.get("old_last") == "2018-02-14", "601313 last official bar mismatch")
        require(t.get("new_first") == "2018-02-28", "601360 first official bar mismatch")

    require(g4.get("pass") is True and not g4.get("errors"), "G4 audit is not clean PASS")
    require(g4.get("expected_security_count") == 3402, "G4 expected security count != 3402")
    require(g4.get("row_security_count") == 3402, "G4 row security count != 3402")
    require(g4.get("state_rows") == 8124206, "G4 state rows != 8,124,206")
    require(g4.get("tradable_states_missing_g3") == 0, "G4 tradable states missing G3 != 0")
    require(g4.get("code_transitions_checked") == 3, "G4 did not check 3 transitions")
    require(g4.get("dataset_fingerprint") == gates["G4"].get("dataset_fingerprint"), "G4 dataset fingerprint mismatch")
    require(g4.get("601268_all_suspended") is True, "601268 suspension control failed")
    require(g4.get("600656_2016_05_12_nontrading") is True, "600656 non-trading control failed")

    require(g5.get("pass") is True and not g5.get("errors"), "G5 audit is not clean PASS")
    require(g5.get("official_action_events") == 25914, "G5 official action count != 25,914")
    require(g5.get("adjustment_events") == 25914, "G5 adjustment count != 25,914")
    require(g5.get("g3_dataset_fingerprint") == g3.get("dataset_fingerprint"), "G5/G3 fingerprint mismatch")
    require(g5.get("factor_ratio_mismatches") == 0, "G5 factor ratio mismatch count != 0")
    require(g5.get("material_nonshare_discrepancy_count") == 0, "G5 material non-share discrepancy count != 0")
    require(g5.get("suspended_reference_bootstrap_count") == 1, "G5 suspended bootstrap count != 1")
    require(g5.get("dataset_fingerprint") == gates["G5"].get("dataset_fingerprint"), "G5 dataset fingerprint mismatch")

    # Manifest gate values must match live downloaded evidence, not merely claim PASS.
    require(gates["G2"].get("total_intervals") == g2.get("total_intervals"), "manifest/G2 interval mismatch")
    require(gates["G2"].get("code_transitions") == g2.get("code_transitions"), "manifest/G2 transition mismatch")
    require(gates["G3"].get("rows") == g3.get("total_rows"), "manifest/G3 row mismatch")
    require(gates["G3"].get("trading_days") == g3.get("trading_days"), "manifest/G3 trading-day mismatch")
    require(gates["G4"].get("security_count") == g4.get("row_security_count"), "manifest/G4 security mismatch")
    require(gates["G4"].get("state_rows") == g4.get("state_rows"), "manifest/G4 row mismatch")
    require(gates["G5"].get("official_action_events") == g5.get("official_action_events"), "manifest/G5 official action mismatch")
    require(gates["G5"].get("adjustment_events") == g5.get("adjustment_events"), "manifest/G5 adjustment mismatch")

    require(checks.get("g1_current_set_equals_g2_open_intervals") is True, "cross gate G1/G2 set equality not locked")
    require(checks.get("g1_only_count") == 0 and checks.get("g2_open_only_count") == 0, "cross gate G1/G2 residual sets nonzero")
    require(checks.get("g2_code_transitions") == 3, "cross gate transition count != 3")
    require(checks.get("g3_code_time_identity_all_exchanges_pass") is True, "cross gate all-exchange identity not PASS")
    require(checks.get("g4_tradable_states_missing_g3") == 0, "cross gate G4/G3 missing != 0")
    require(checks.get("g5_official_action_count_equals_adjustment_count") is True, "cross gate G5 counts not equal")
    require(checks.get("g5_g3_fingerprint_matches_g3") is True, "cross gate G5/G3 fingerprint flag false")

    report = {
        "gate": "STAGE2_FINAL_FREEZE_V3_2_25",
        "pass": not errors,
        "version": m.get("version"),
        "stage2_dataset_fingerprint": fp,
        "manifest_sha256": manifest_sha,
        "g2_intervals": g2.get("total_intervals"),
        "g3_rows": g3.get("total_rows"),
        "g3_trading_days": g3.get("trading_days"),
        "g4_security_count": g4.get("row_security_count"),
        "g4_state_rows": g4.get("state_rows"),
        "g5_actions": g5.get("official_action_events"),
        "errors": errors,
    }
    (out / "stage2_final_freeze_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
