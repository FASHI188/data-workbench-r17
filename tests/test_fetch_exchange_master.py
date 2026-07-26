import importlib.util
import sys
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "fetch_exchange_master.py"
spec = importlib.util.spec_from_file_location("fetch_exchange_master", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_sse_jsonp_and_filter():
    raw = b'cb({"result":[{"A_STOCK_CODE":"600000","COMPANY_ABBR":"A","LIST_DATE":"1999-11-10"},{"A_STOCK_CODE":"688001","COMPANY_ABBR":"STAR"}]})'
    rows = m.sse_rows(m.parse_jsonp(raw))
    assert [r.code for r in rows] == ["600000"]
    assert rows[0].board_basis == "OFFICIAL_SSE_STOCK_TYPE_1"


def test_szse_excludes_chinext_and_marks_fallback():
    payload = {
        "data": [
            {"agdm": "000001", "agjc": "MAIN", "ssbk": "主板"},
            {"agdm": "300001", "agjc": "GEM", "ssbk": "创业板"},
            {"agdm": "002001", "agjc": "MAIN2"},
        ]
    }
    rows = m.szse_rows(payload)
    assert [r.code for r in rows] == ["000001", "002001"]
    assert rows[0].board_basis == "OFFICIAL_SZSE_BOARD_FIELD"
    assert rows[1].board_basis == "DERIVED_CODE_PREFIX"


def test_empty_rows_not_success_material():
    assert m.sse_rows({"result": []}) == []
