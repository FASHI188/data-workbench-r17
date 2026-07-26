import importlib.util
import sys
from datetime import date
from pathlib import Path
import pytest

MODULE = Path(__file__).parents[1] / "scripts" / "build_security_history.py"
spec = importlib.util.spec_from_file_location("build_security_history", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def ev(code, typ, dt, name="X"):
    return m.Event("SSE", code, typ, date.fromisoformat(dt), name, "https://www.sse.com.cn/x", "0" * 64, "POINT_IN_TIME_PRIMARY")


def test_list_and_delist_interval():
    rows = m.build_intervals([ev("600001", "LIST", "2010-01-01"), ev("600001", "DELIST", "2020-06-01")])
    assert rows[0].listed_from == "2010-01-01"
    assert rows[0].listed_to_exclusive == "2020-06-01"


def test_open_current_interval():
    rows = m.build_intervals([ev("600002", "LIST", "2012-01-01")])
    assert rows[0].listed_to_exclusive is None


def test_delist_before_list_fails():
    with pytest.raises(ValueError):
        m.build_intervals([ev("600003", "DELIST", "2020-01-01")])


def test_duplicate_list_fails():
    with pytest.raises(ValueError):
        m.build_intervals([ev("600004", "LIST", "2010-01-01"), ev("600004", "LIST", "2011-01-01")])
