import unittest

from scripts.audit_stage3_final_lock import semantic_gate_digest, stage3_fingerprint_basis


class Stage3FinalFingerprintTests(unittest.TestCase):
    def test_transport_metadata_does_not_change_semantic_gate_digest(self):
        a = [{"record": {
            "gate": "S3G2_POINT_IN_TIME_ANNOUNCEMENT_LEDGER",
            "pass": True,
            "errors": [],
            "ledger_sha256": "abc",
            "unique_announcements": 123,
            "run_id": 1,
            "artifact_digest": "sha256:first",
            "generated_at": "2026-07-30T00:00:00Z",
        }}]
        b = [{"record": {
            "gate": "S3G2_POINT_IN_TIME_ANNOUNCEMENT_LEDGER",
            "pass": True,
            "errors": [],
            "ledger_sha256": "abc",
            "unique_announcements": 123,
            "run_id": 2,
            "artifact_digest": "sha256:second",
            "generated_at": "2026-07-31T00:00:00Z",
        }}]
        self.assertEqual(semantic_gate_digest(a), semantic_gate_digest(b))

    def test_semantic_change_changes_gate_digest(self):
        a = [{"record": {"gate": "S3G2", "pass": True, "errors": [], "ledger_sha256": "abc"}}]
        b = [{"record": {"gate": "S3G2", "pass": True, "errors": [], "ledger_sha256": "def"}}]
        self.assertNotEqual(semantic_gate_digest(a), semantic_gate_digest(b))

    def test_dataset_fingerprint_basis_contains_no_transport_identity(self):
        basis = stage3_fingerprint_basis(
            "policy-sha",
            {"S3G2": {"audit_gates": ["S3G2"], "semantic_sha256": "abc"}},
        )
        text = repr(basis)
        self.assertNotIn("run_id", text)
        self.assertNotIn("artifact_digest", text)
        self.assertEqual(basis["trading_universe_policy_sha256"], "policy-sha")


if __name__ == "__main__":
    unittest.main()
