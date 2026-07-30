import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.finalize_stage3_announcement_ledger import write_deterministic_csv_gz


class DeterministicGzipTests(unittest.TestCase):
    def test_same_rows_have_identical_gzip_bytes_across_filenames(self):
        fields = ["a", "b"]
        rows = [{"a": "1", "b": "中文"}, {"a": "2", "b": "x"}]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            left = root / "left.csv.gz"
            right = root / "different-name.csv.gz"
            write_deterministic_csv_gz(left, fields, rows)
            write_deterministic_csv_gz(right, fields, rows)
            self.assertEqual(left.read_bytes(), right.read_bytes())
            self.assertEqual(
                hashlib.sha256(left.read_bytes()).hexdigest(),
                hashlib.sha256(right.read_bytes()).hexdigest(),
            )
            with gzip.open(left, "rt", encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), "a,b\r\n1,中文\r\n2,x\r\n")


if __name__ == "__main__":
    unittest.main()
