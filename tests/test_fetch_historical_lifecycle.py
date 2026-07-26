import importlib.util
import sys
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

MODULE = Path(__file__).parents[1] / "scripts" / "fetch_historical_lifecycle.py"
spec = importlib.util.spec_from_file_location("fetch_historical_lifecycle", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def workbook_bytes(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "终止上市"
    for row in rows:
        ws.append(row)
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_szse_official_code_range_classification():
    assert m.szse_security_class("000000") == "UNKNOWN"
    assert m.szse_security_class("000004") == "MAIN_A"
    assert m.szse_security_class("002001") == "MAIN_A"
    assert m.szse_security_class("003001") == "MAIN_A"
    assert m.szse_security_class("004999") == "MAIN_A"
    assert m.szse_security_class("001001") == "MAIN_CDR"
    assert m.szse_security_class("001199") == "MAIN_CDR"
    assert m.szse_security_class("001200") == "MAIN_A"
    assert m.szse_security_class("200018") == "MAIN_B"
    assert m.szse_security_class("300001") == "UNKNOWN"


def test_szse_xlsx_excludes_b_and_cdr():
    raw = workbook_bytes([
        ["证券代码", "证券简称", "上市日期", "终止上市日期"],
        ["000004", "国华退", "1990-12-01", "2026-07-14"],
        ["200018", "神城B退", "1992-06-16", "2020-01-07"],
        ["001001", "测试存托", "2020-01-01", "2025-01-01"],
    ])
    rows, control = m.parse_szse_delisted_xlsx(raw, "https://www.szse.cn/test")
    assert [x.code for x in rows] == ["000004"]
    assert control["class_counts"] == {"MAIN_A": 1, "MAIN_B": 1, "MAIN_CDR": 1}


def test_date_normalization_accepts_exchange_formats():
    assert m.normalize_date("20260714") == "2026-07-14"
    assert m.normalize_date("2026-07-14") == "2026-07-14"
