from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_forward_disclosure_ledger as m
import audit_forward_financial_disclosures as audit


def test_next_session_is_strictly_later():
    sessions=[date(2026,8,10),date(2026,8,11),date(2026,8,12),date(2026,8,13)]
    assert m.next_session(date(2026,8,12),sessions)==date(2026,8,13)
    assert m.next_session(date(2026,8,13),sessions) is None


def test_identity_prefers_current_master_then_unique_org_mapping():
    master={"600000":{"exchange":"SSE"},"000001":{"exchange":"SZSE"}}
    by_org={"gssz0000001":["000001"]}
    assert m.map_identity({"secCode":"600000","orgId":"x"},master,by_org)[0]=="600000"
    mapped=m.map_identity({"secCode":"127999","orgId":"gssz0000001"},master,by_org)
    assert mapped[0]=="000001" and mapped[3]=="SAME_ISSUER_NON_EQUITY_INSTRUMENT"


def test_ambiguous_org_fails_closed():
    master={"000001":{"exchange":"SZSE"},"000002":{"exchange":"SZSE"}}
    mapped=m.map_identity({"secCode":"127999","orgId":"org"},master,{"org":["000001","000002"]})
    assert mapped[0] is None and mapped[3].startswith("AMBIGUOUS_ORG_TO_EQUITY")


def test_retained_error_requires_original_source_sha():
    assert audit.evidence_has_source_sha('[{"sha256":"abc"}]')
    assert not audit.evidence_has_source_sha('[{"error":"timeout"}]')
