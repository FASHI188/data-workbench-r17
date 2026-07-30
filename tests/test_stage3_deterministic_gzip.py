import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.finalize_stage3_announcement_ledger import write_deterministic_csv_gz as write_announcement_gzip
from scripts.finalize_stage3_financial_pdf_values import write_deterministic_csv_gz as write_financial_gzip


class DeterministicGzipTests(unittest.TestCase):
    def _assert_writer_is_byte_deterministic(self, writer):
        fields = ["a", "b"]
        rows = [{"a": "1", "b": "中文"}, {"a": "2", "b": "x"}]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = root / "left.csv.gz"
            right = root / "different-name.csv.gz"
            writer(left, fields, rows)
            writer(right, fields, rows)
            self.assertEqual(left.read_bytes(), right.read_bytes())
            self.assertEqual(
                hashlib.sha256(left.read_bytes()).hexdigest(),
                hashlib.sha256(right.read_bytes()).hexdigest(),
            )
            with gzip.open(left, "rt", encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), "a,b\r\n1,中文\r\n2,x\r\n")

    def test_announcement_finalizer_gzip_is_byte_deterministic(self):
        self._assert_writer_is_byte_deterministic(write_announcement_gzip)

    def test_financial_finalizer_gzip_is_byte_deterministic(self):
        self._assert_writer_is_byte_deterministic(write_financial_gzip)


if __name__ == "__main__":
    unittest.main()
