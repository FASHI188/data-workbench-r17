from __future__ import annotations

from decimal import Decimal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_stage4_forward_g5_adjustment import calc_event, select_reference

EPS = Decimal("1e-24")


def action(cash="0", bonus="0", transfer="0", rights="0", rights_price="0"):
    return {
        "cash_per_share": cash,
        "bonus_per_share": bonus,
        "transfer_per_share": transfer,
        "rights_per_share": rights,
        "rights_price": rights_price,
    }


def test_cash_dividend_formula_matches_frozen_g5_direction() -> None:
    ex, continuity, back, cumulative = calc_event(action(cash="0.10"), Decimal("10"), Decimal("2"))
    assert ex == Decimal("9.90")
    assert continuity == Decimal("0.99")
    assert back == Decimal("10") / Decimal("9.90")
    assert cumulative == Decimal("2") * back
    assert abs(ex * cumulative - Decimal("20")) <= EPS


def test_small_g4_difference_keeps_official_formula() -> None:
    selected, continuity, back, cumulative, nominal, delta, source = select_reference(
        action(cash="0.10"), Decimal("10"), Decimal("1"), Decimal("9.90")
    )
    assert selected == nominal == Decimal("9.90")
    assert delta == 0
    assert source == "OFFICIAL_ACTION_FORMULA"
    assert abs(selected * cumulative - Decimal("10")) <= EPS


def test_material_share_distribution_can_use_g4_preclose_override() -> None:
    selected, continuity, back, cumulative, nominal, delta, source = select_reference(
        action(cash="0.10", transfer="0.30"), Decimal("13"), Decimal("1"), Decimal("10.10")
    )
    assert nominal == (Decimal("13") - Decimal("0.10")) / Decimal("1.30")
    assert delta > Decimal("0.01")
    assert selected == Decimal("10.10")
    assert source.startswith("G4_EXDATE_PRECLOSE")
    assert abs(selected * cumulative - Decimal("13")) <= EPS


def test_material_cash_only_discrepancy_fails_closed() -> None:
    try:
        select_reference(action(cash="0.10"), Decimal("10"), Decimal("1"), Decimal("9.50"))
    except ValueError as exc:
        assert "without share-distribution semantics" in str(exc)
    else:
        raise AssertionError("material non-share discrepancy must fail closed")


def test_nonpositive_reference_fails_closed() -> None:
    try:
        calc_event(action(cash="1"), Decimal("0.5"), Decimal("1"))
    except ValueError:
        pass
    else:
        raise AssertionError("nonpositive ex-reference must fail closed")
