#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path

from stage3_financial_pdf_parser_v10 import _mupdf_diagnostic_guard


if __name__ == "__main__":
    target = Path(__file__).with_name("diagnose_stage3_s3g1j_v17_13_no_right_amount.py")
    with _mupdf_diagnostic_guard():
        runpy.run_path(str(target), run_name="__main__")
