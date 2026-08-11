from __future__ import annotations

import copy
import json
import unittest

import prepare_stage3_s3g1j_v17_29_six_source_input as p


class V1729SixSourceInputAdapterTests(unittest.TestCase):
    def sample(self) -> tuple[dict[str, str], dict]:
        target = {
            "announcement_id": "1202799494",
            "source_sha256": "abc123",
        }
        row = {
            "announcement_id": "1202799494",
            "document_status": "ERROR",
            "tie_candidate_count": "1",
            "tie_resolution": "TIE_SOURCE_INCOMPLETE",
            "selected_source_url": "https://static.cninfo.com.cn/x.pdf",
            "selected_source_sha256": "",
            "selected_source_bytes": "",
            "canonical_source_url": "",
            "candidate_evidence_json": json.dumps([{
                "id": "1202799494",
                "url": "https://static.cninfo.com.cn/x.pdf",
                "sha256": "abc123",
                "bytes": 12345,
            }]),
        }
        return row, target

    def test_error_row_uses_single_candidate_identity_when_top_level_selection_is_empty(self) -> None:
        row, target = self.sample()
        out = p.normalize_row(row, target)
        self.assertEqual(out["selected_source_sha256"], "abc123")
        self.assertEqual(out["selected_source_bytes"], "12345")
        self.assertEqual(out["selected_source_url"], "https://static.cninfo.com.cn/x.pdf")
        self.assertEqual(row["selected_source_sha256"], "")
        self.assertEqual(row["selected_source_bytes"], "")

    def test_candidate_sha_must_match_governance_evidence(self) -> None:
        row, target = self.sample()
        candidate = json.loads(row["candidate_evidence_json"])
        candidate[0]["sha256"] = "different"
        row["candidate_evidence_json"] = json.dumps(candidate)
        with self.assertRaisesRegex(ValueError, "candidate source SHA drift"):
            p.normalize_row(row, target)

    def test_multiple_candidates_fail_closed(self) -> None:
        row, target = self.sample()
        candidates = json.loads(row["candidate_evidence_json"])
        candidates.append(copy.deepcopy(candidates[0]))
        row["candidate_evidence_json"] = json.dumps(candidates)
        with self.assertRaisesRegex(ValueError, "exactly one candidate"):
            p.normalize_row(row, target)

    def test_nonempty_top_level_identity_must_not_conflict(self) -> None:
        row, target = self.sample()
        row["selected_source_sha256"] = "conflict"
        with self.assertRaisesRegex(ValueError, "conflicts with candidate evidence"):
            p.normalize_row(row, target)

    def test_url_mismatch_fails_closed(self) -> None:
        row, target = self.sample()
        row["selected_source_url"] = "https://static.cninfo.com.cn/other.pdf"
        with self.assertRaisesRegex(ValueError, "selected source URL drift"):
            p.normalize_row(row, target)


if __name__ == "__main__":
    unittest.main()
