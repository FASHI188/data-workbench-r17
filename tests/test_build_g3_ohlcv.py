import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

MODULE = Path(__file__).parents[1] / "scripts" / "build_g3_ohlcv.py"
spec = importlib.util.spec_from_file_location("build_g3_ohlcv", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def xlsx_bytes(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_parse_sse_dayk_normalizes_and_filters():
    payload = {
        "code": "600000",
        "begin": 1,
        "end": 3,
        "kline": [
            [20141231, 10, 11, 9, 10.5, 100, 1000],
            [20150105, 10, 12, 9, 11, 200, 2200],
            [20150106, 11, 11.5, 10.5, 11.2, 300, 3300],
        ],
    }
    rows, diag = m.parse_sse_dayk(
        json.dumps(payload).encode(), "600000", (m.date(2010,1,1), None), m.date(2015,1,6)
    )
    assert [r["trade_date"] for r in rows] == ["2015-01-05", "2015-01-06"]
    assert rows[0]["volume_shares"] == "200"
    assert rows[0]["amount_cny"] == "2200"
    assert diag["source_total_rows"] == 3


def test_parse_sse_rejects_outside_lifecycle():
    payload = {"code":"600000","kline":[[20150105,10,11,9,10,1,10]]}
    try:
        m.parse_sse_dayk(json.dumps(payload).encode(), "600000", (m.date(2015,1,6), None), m.date(2015,1,6))
    except ValueError as exc:
        assert "outside lifecycle" in str(exc)
    else:
        raise AssertionError("expected lifecycle rejection")


def test_parse_szse_day_filters_scope_and_converts_units():
    raw = xlsx_bytes([
        ["交易日期","证券代码","证券简称","前收","开盘","最高","最低","今收","涨跌幅（%）","成交量(万股)","成交金额(万元)","市盈率"],
        ["2015-01-05","000001","平安银行","10","10","11","9","10.5","5","1.25","2.34","10"],
        ["2015-01-05","300001","创业板","10","10","11","9","10.5","5","2","3","10"],
    ])
    rows, diag = m.parse_szse_day(raw, m.date(2015,1,5), {"000001": (m.date(1991,1,1), None)})
    assert len(rows) == 1
    assert rows[0]["code"] == "000001"
    assert rows[0]["volume_shares"] == "12500"
    assert rows[0]["amount_cny"] == "23400"
    assert diag["source_data_rows"] == 2
    assert diag["ignored_out_of_scope"] == 1


def test_parse_szse_holiday_no_data():
    raw = xlsx_bytes([
        ["交易日期","证券代码","证券简称","前收","开盘","最高","最低","今收","涨跌幅（%）","成交量(万股)","成交金额(万元)","市盈率"],
        ["没有找到符合条件的数据！",None,None,None,None,None,None,None,None,None,None,None],
    ])
    rows, diag = m.parse_szse_day(raw, m.date(2015,1,1), {})
    assert rows == []
    assert diag["source_data_rows"] == 0
