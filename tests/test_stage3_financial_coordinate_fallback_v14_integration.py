from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import requests

from stage3_financial_pdf_parser_v9 import parse_pdf_bytes

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "config/stage3_s3g1j_v10_diagnostic_samples.json"

EXPECTED_TRUE = {
    "1206660047": {"TOTAL_ASSETS": "4647020000000", "TOTAL_LIABILITIES": "4312935000000", "TOTAL_EQUITY": "334085000000"},
    "1206728992": {"TOTAL_ASSETS": "493013036920.42", "TOTAL_LIABILITIES": "374810235262.95", "TOTAL_EQUITY": "118202801657.47"},
    "1216700376": {"TOTAL_ASSETS": "55583389860.43", "TOTAL_LIABILITIES": "21627644896.73", "TOTAL_EQUITY": "33955744963.70"},
    "1217635500": {"TOTAL_ASSETS": "8833297000000", "TOTAL_LIABILITIES": "8122284000000", "TOTAL_EQUITY": "711013000000"},
}

EXPECTED_FALSE = {
    "1201392942",  # 000023: mother-company statement, not consolidated
    "1202260810",  # 601166: raw coordinate identity chose prior/wrong role column
    "1203373899",  # 000046: trust-business table
    "1209868800",  # 000046: trust-business table
}


def _sample_map() -> dict[str, dict]:
    spec = json.loads(SAMPLES.read_text(encoding="utf-8"))
    return {str(x["announcement_id"]): x for x in spec["samples"]}


def _download(session: requests.Session, sample: dict) -> bytes:
    response = session.get(
        sample["url"],
        headers={
            "User-Agent": "Mozilla/5.0 S3G1J-V14-production-integration",
            "Referer": "https://www.cninfo.com.cn/",
        },
        timeout=120,
    )
    response.raise_for_status()
    raw = response.content
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sample["sha256"]:
        raise AssertionError(f"SHA mismatch {sample['announcement_id']} expected={sample['sha256']} actual={actual}")
    return raw


class CoordinateFallbackV14IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = _sample_map()
        cls.session = requests.Session()

    def test_exact_four_role_qualified_recoveries(self):
        for announcement_id, expected in EXPECTED_TRUE.items():
            with self.subTest(announcement_id=announcement_id):
                raw = _download(self.session, self.samples[announcement_id])
                parsed = parse_pdf_bytes(raw)
                block = parsed.get("balance_sheet_block") or {}
                self.assertEqual(block.get("arbitration"), "V14_COORDINATE_GROUP_CURRENT_A_EQUALS_L_PLUS_E")
                self.assertEqual(parsed.get("validation_errors") or [], [])
                observations = parsed.get("observations") or {}
                for concept, value in expected.items():
                    obs = observations.get(concept) or {}
                    self.assertEqual(obs.get("status"), "FOUND")
                    self.assertEqual(obs.get("normalized_cny_value"), value)
                    self.assertEqual(obs.get("extraction_scope"), "VALIDATED_BALANCE_SHEET_BLOCK_V14_COORDINATE_ROLE_GATE")

    def test_exact_four_raw_false_positives_remain_fail_closed(self):
        for announcement_id in EXPECTED_FALSE:
            with self.subTest(announcement_id=announcement_id):
                raw = _download(self.session, self.samples[announcement_id])
                parsed = parse_pdf_bytes(raw)
                block = parsed.get("balance_sheet_block") or {}
                self.assertNotEqual(block.get("arbitration"), "V14_COORDINATE_GROUP_CURRENT_A_EQUALS_L_PLUS_E")
                self.assertTrue(
                    parsed.get("validation_errors") or not parsed.get("balance_sheet_block"),
                    f"false-positive sample unexpectedly became authoritative: {announcement_id}",
                )


if __name__ == "__main__":
    unittest.main()
