import importlib.util
import sys
from datetime import date
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "build_security_history.py"
spec = importlib.util.spec_from_file_location("build_security_history", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_code_transition_splits_inherited_entity_history_by_effective_code():
    events = [
        m.Event(
            exchange="SZSE",
            code="001872",
            event_type="LIST",
            effective_date=date(1993, 5, 5),
            name="招商港口",
            source_url="https://example.invalid/current",
            source_sha256="a" * 64,
            evidence_class="RETROSPECTIVE_PRIMARY",
        )
    ]
    transition = [{
        "exchange": "SZSE",
        "old_code": "000022",
        "new_code": "001872",
        "effective_date": "2018-12-26",
        "old_name": "深赤湾A",
        "new_name": "招商港口",
        "source_url": "https://example.invalid/change.pdf",
        "source_sha256": "b" * 64,
        "evidence_class": "POINT_IN_TIME_PRIMARY",
    }]
    rows = m.apply_code_transitions(m.build_intervals(events), transition)
    by_code = {r.code: r for r in rows}
    assert by_code["000022"].listed_from == "1993-05-05"
    assert by_code["000022"].listed_to_exclusive == "2018-12-26"
    assert by_code["000022"].delist_evidence_class == "POINT_IN_TIME_PRIMARY"
    assert by_code["001872"].listed_from == "2018-12-26"
    assert by_code["001872"].listed_to_exclusive is None
    assert by_code["001872"].list_evidence_class == "POINT_IN_TIME_PRIMARY"


def test_sse_transition_601313_to_601360_uses_same_code_time_semantics():
    events = [
        m.Event(
            exchange="SSE",
            code="601360",
            event_type="LIST",
            effective_date=date(2012, 1, 16),
            name="三六零",
            source_url="https://example.invalid/current",
            source_sha256="a" * 64,
            evidence_class="RETROSPECTIVE_PRIMARY",
        )
    ]
    transition = [{
        "exchange": "SSE",
        "old_code": "601313",
        "new_code": "601360",
        "effective_date": "2018-02-28",
        "old_name": "江南嘉捷",
        "new_name": "三六零",
        "source_url": "https://example.invalid/change.pdf",
        "source_sha256": "b" * 64,
        "evidence_class": "POINT_IN_TIME_PRIMARY",
    }]
    rows = m.apply_code_transitions(m.build_intervals(events), transition)
    by_code = {r.code: r for r in rows}
    assert by_code["601313"].listed_from == "2012-01-16"
    assert by_code["601313"].listed_to_exclusive == "2018-02-28"
    assert by_code["601313"].delist_evidence_class == "POINT_IN_TIME_PRIMARY"
    assert by_code["601360"].listed_from == "2018-02-28"
    assert by_code["601360"].listed_to_exclusive is None
    assert by_code["601360"].list_evidence_class == "POINT_IN_TIME_PRIMARY"


def test_transition_rejects_existing_predecessor_identity():
    base = [
        m.Interval("SZSE", "000022", "old", "1993-05-05", None, "RETROSPECTIVE_PRIMARY", None),
        m.Interval("SZSE", "001872", "new", "1993-05-05", None, "RETROSPECTIVE_PRIMARY", None),
    ]
    transition = [{
        "exchange": "SZSE", "old_code": "000022", "new_code": "001872",
        "effective_date": "2018-12-26", "old_name": "old", "new_name": "new",
        "source_url": "https://example.invalid/change.pdf", "source_sha256": "b" * 64,
        "evidence_class": "POINT_IN_TIME_PRIMARY",
    }]
    try:
        m.apply_code_transitions(base, transition)
    except ValueError as exc:
        assert "predecessor already exists" in str(exc)
    else:
        raise AssertionError("expected duplicate predecessor rejection")
