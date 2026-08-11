#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "governance/stage3_workflow_activation_manifest.json"
OUT = ROOT / "build/v17_30_activation_boundary_repair/stage3_workflow_activation_manifest.json"
REPORT = ROOT / "build/v17_30_activation_boundary_repair/repair_report.json"


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    assert data["schema_version"] == 17
    current = data["accepted_production_runtime"]
    assert current["generation"] == "V17.30"
    assert current["full_basis_execution_pending"] is False
    assert current["last_completed_full_basis_generation"] == "V17.30"
    assert current["last_completed_full_basis_run"] == 31518370789
    assert current["last_completed_numeric_observation_count"] == 1051826
    assert current["last_completed_document_error_count"] == 1362
    assert current["last_completed_unresolved_tie_count"] == 1279
    assert current["data_verdict"] == "FAIL_CLOSED"

    b = data["hard_boundaries"]
    before = dict(b)
    b["v17_30_full_basis_execution_pending"] = False
    b["v17_30_full_basis_execution_started"] = True
    b["remaining_document_errors_last_completed_basis"] = 1362
    b["remaining_unresolved_ties_last_completed_basis"] = 1279

    assert b["v17_30_full_basis_execution_pending"] is False
    assert b["v17_30_full_basis_execution_started"] is True
    assert b["remaining_document_errors_last_completed_basis"] == 1362
    assert b["remaining_unresolved_ties_last_completed_basis"] == 1279
    assert b["stage3_status"] == "NOT_READY"
    assert b["stage4_alpha_live_locked"] is True
    assert b["committed_production_data_changed"] is False
    assert b["trained_model_changed"] is False
    assert b["main_changed"] is False

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    report = {
        "gate": "S3G1J_V17_30_ACTIVATION_BOUNDARY_REPAIR",
        "pass": True,
        "changed_keys": {
            k: {"before": before.get(k), "after": b.get(k)}
            for k in [
                "v17_30_full_basis_execution_pending",
                "v17_30_full_basis_execution_started",
                "remaining_document_errors_last_completed_basis",
                "remaining_unresolved_ties_last_completed_basis",
            ]
        },
        "stage3_status": b["stage3_status"],
        "stage4_alpha_live_locked": b["stage4_alpha_live_locked"],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
