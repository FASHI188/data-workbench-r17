#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation, getcontext
from pathlib import Path

getcontext().prec = 28
MATERIAL_REFERENCE_DELTA = Decimal("0.01")

FIELDS = [
    "exchange","code","ex_date","action_type","cash_per_share","bonus_per_share",
    "transfer_per_share","rights_per_share","rights_price","prior_reference_price",
    "nominal_formula_ex_reference_price","g4_exdate_preclose","market_reference_relative_delta",
    "ex_reference_price","continuity_ratio","back_adjust_multiplier",
    "cumulative_back_adjust_multiplier","reference_source","source_count","source_evidence",
    "g4_source_sha256"
]


def D(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal("0")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def calc_event(action: dict[str, str], prior: Decimal, cumulative: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    cash = D(action.get("cash_per_share"))
    bonus = D(action.get("bonus_per_share"))
    transfer = D(action.get("transfer_per_share"))
    rights = D(action.get("rights_per_share"))
    rights_price = D(action.get("rights_price"))
    denom = Decimal(1) + bonus + transfer + rights
    ex_reference = (prior - cash + rights_price * rights) / denom
    if prior <= 0 or denom <= 0 or ex_reference <= 0:
        raise ValueError(f"invalid action reference prior={prior} denom={denom} ex={ex_reference}")
    continuity = ex_reference / prior
    back = prior / ex_reference
    return ex_reference, continuity, back, cumulative * back


def select_reference(action: dict[str, str], prior: Decimal, cumulative: Decimal, g4_preclose: Decimal) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, str]:
    nominal_ex, nominal_cont, nominal_back, nominal_cumulative = calc_event(action, prior, cumulative)
    if g4_preclose <= 0:
        raise ValueError("missing/nonpositive G4 preclose")
    delta = abs(g4_preclose - nominal_ex) / max(abs(nominal_ex), Decimal("1e-18"))
    if delta <= MATERIAL_REFERENCE_DELTA:
        return nominal_ex, nominal_cont, nominal_back, nominal_cumulative, nominal_ex, delta, "OFFICIAL_ACTION_FORMULA"
    has_share_distribution = D(action.get("bonus_per_share")) > 0 or D(action.get("transfer_per_share")) > 0
    if not has_share_distribution:
        raise ValueError(f"material nominal/G4 discrepancy without share-distribution semantics nominal={nominal_ex} g4={g4_preclose} delta={delta}")
    continuity = g4_preclose / prior
    back = prior / g4_preclose
    return g4_preclose, continuity, back, cumulative * back, nominal_ex, delta, "G4_EXDATE_PRECLOSE_MATERIAL_SHARE_DISTRIBUTION_SEMANTIC_OVERRIDE"


def read_gzip_csv(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def load_actions(path: Path, target_session: str) -> list[dict[str, str]]:
    rows = [r for r in read_gzip_csv(path) if r["ex_date"] <= target_session]
    rows.sort(key=lambda r: (r["ex_date"], r["exchange"], r["code"]))
    return rows


def load_last_historical_cumulative(path: Path) -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], tuple[str, Decimal]] = {}
    for row in read_gzip_csv(path):
        key = (row["exchange"], row["code"])
        current = out.get(key)
        if current is None or row["ex_date"] >= current[0]:
            out[key] = (row["ex_date"], D(row["cumulative_back_adjust_multiplier"]))
    return {key: value for key, (_, value) in out.items()}


def load_price_history(historical_root: Path, forward_root: Path) -> dict[tuple[str, str], list[tuple[str, Decimal]]]:
    by_code: dict[tuple[str, str], list[tuple[str, Decimal]]] = defaultdict(list)
    historical_files = sorted(historical_root.rglob("*2026*.csv.gz"))
    forward_files = sorted(forward_root.rglob("*.csv.gz"))
    if not historical_files:
        raise ValueError("no 2026 historical OHLCV files found")
    if not forward_files:
        raise ValueError("no forward OHLCV files found")
    for path in historical_files + forward_files:
        for row in read_gzip_csv(path):
            day = row["trade_date"]
            if day > "2026-08-12":
                continue
            by_code[(row["exchange"], row["code"])].append((day, D(row["close"])))
    for key, rows in by_code.items():
        rows.sort(key=lambda x: x[0])
        dedup: list[tuple[str, Decimal]] = []
        for day, close in rows:
            if dedup and dedup[-1][0] == day:
                if dedup[-1][1] != close:
                    raise ValueError(f"conflicting OHLCV close for {key} {day}")
                continue
            dedup.append((day, close))
        by_code[key] = dedup
    return by_code


def latest_close_between(rows: list[tuple[str, Decimal]], after_exclusive: str | None, before_exclusive: str) -> tuple[str, Decimal] | None:
    days = [x[0] for x in rows]
    idx = bisect.bisect_left(days, before_exclusive) - 1
    if idx < 0:
        return None
    day, close = rows[idx]
    if after_exclusive is not None and day <= after_exclusive:
        return None
    return day, close


def bscode(exchange: str, code: str) -> str:
    return ("sh." if exchange == "SSE" else "sz.") + code


def query_g4_preclose(bs, exchange: str, code: str, ex_date: str) -> tuple[Decimal, str]:
    fields = "date,code,preclose,tradestatus"
    rs = bs.query_history_k_data_plus(
        bscode(exchange, code), fields,
        start_date=ex_date, end_date=ex_date,
        frequency="d", adjustflag="3"
    )
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(dict(zip(rs.fields, rs.get_row_data())))
    if rs.error_code != "0":
        raise RuntimeError(f"BaoStock G4 query failed {exchange}:{code}:{ex_date} {rs.error_code} {rs.error_msg}")
    if len(rows) != 1:
        raise ValueError(f"expected exactly one G4 row for {exchange}:{code}:{ex_date}; got {len(rows)}")
    row = rows[0]
    if row.get("date") != ex_date:
        raise ValueError(f"G4 date mismatch for {exchange}:{code}:{ex_date}: {row}")
    raw = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return D(row.get("preclose")), sha256_bytes(raw)


def action_type(row: dict[str, str]) -> str:
    parts = []
    if D(row.get("cash_per_share")) != 0:
        parts.append("CASH_DIVIDEND")
    if D(row.get("bonus_per_share")) != 0:
        parts.append("BONUS_SHARE")
    if D(row.get("transfer_per_share")) != 0:
        parts.append("CAPITAL_TRANSFER")
    if D(row.get("rights_per_share")) != 0:
        parts.append("RIGHTS_ISSUE")
    return "+".join(parts) if parts else row.get("action_component", "UNKNOWN")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", required=True)
    parser.add_argument("--historical-g5", required=True)
    parser.add_argument("--historical-ohlcv-root", required=True)
    parser.add_argument("--forward-ohlcv-root", required=True)
    parser.add_argument("--target-session", default="2026-08-12")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    import baostock as bs

    actions = load_actions(Path(args.actions), args.target_session)
    historical_cumulative = load_last_historical_cumulative(Path(args.historical_g5))
    prices = load_price_history(Path(args.historical_ohlcv_root), Path(args.forward_ohlcv_root))
    cumulative = defaultdict(lambda: Decimal(1), historical_cumulative)
    reference_state: dict[tuple[str, str], tuple[str, Decimal]] = {}
    output: list[dict[str, str]] = []
    errors: list[str] = []
    overrides: list[dict[str, str]] = []

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError("BaoStock login failed: " + login.error_msg)
    try:
        for index, action in enumerate(actions):
            key = (action["exchange"], action["code"])
            rows = prices.get(key, [])
            prior_state = reference_state.get(key)
            last_event_date = prior_state[0] if prior_state else None
            newer_close = latest_close_between(rows, last_event_date, action["ex_date"])
            if newer_close is not None:
                prior = newer_close[1]
            elif prior_state is not None:
                prior = prior_state[1]
            else:
                any_prior = latest_close_between(rows, None, action["ex_date"])
                if any_prior is None:
                    errors.append(f"missing prior OHLCV reference for {key} {action['ex_date']}")
                    continue
                prior = any_prior[1]
            try:
                g4_preclose, g4_sha = query_g4_preclose(bs, action["exchange"], action["code"], action["ex_date"])
                ex_ref, cont, back, new_cum, nominal_ex, delta, source = select_reference(
                    action, prior, cumulative[key], g4_preclose
                )
                if source.startswith("G4_"):
                    overrides.append({
                        "exchange": action["exchange"], "code": action["code"], "ex_date": action["ex_date"],
                        "nominal_ex_reference": format(nominal_ex, "f"), "g4_preclose": format(g4_preclose, "f"),
                        "relative_delta": format(delta, "f")
                    })
                cumulative[key] = new_cum
                reference_state[key] = (action["ex_date"], ex_ref)
                output.append({
                    "exchange": action["exchange"], "code": action["code"], "ex_date": action["ex_date"],
                    "action_type": action_type(action), "cash_per_share": action["cash_per_share"],
                    "bonus_per_share": action["bonus_per_share"], "transfer_per_share": action["transfer_per_share"],
                    "rights_per_share": action["rights_per_share"], "rights_price": action["rights_price"],
                    "prior_reference_price": format(prior, "f"),
                    "nominal_formula_ex_reference_price": format(nominal_ex, "f"),
                    "g4_exdate_preclose": format(g4_preclose, "f"),
                    "market_reference_relative_delta": format(delta, "f"),
                    "ex_reference_price": format(ex_ref, "f"), "continuity_ratio": format(cont, "f"),
                    "back_adjust_multiplier": format(back, "f"),
                    "cumulative_back_adjust_multiplier": format(new_cum, "f"),
                    "reference_source": source + "_WITH_FORWARD_G4_BAOSTOCK_CONTROL",
                    "source_count": "1", "source_evidence": json.dumps({
                        "action_source_system": action["source_system"], "action_source_id": action["source_id"],
                        "action_source_url": action["source_url"], "action_source_sha256": action["source_sha256"]
                    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    "g4_source_sha256": g4_sha
                })
            except Exception as exc:
                errors.append(f"{key}:{action['ex_date']}: {exc}")
            if index and index % 20 == 0:
                time.sleep(0.2)
    finally:
        bs.logout()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "forward_g5_adjustment_chain.csv.gz"
    output.sort(key=lambda r: (r["ex_date"], r["exchange"], r["code"]))
    with gzip.open(csv_path, "wt", encoding="utf-8", newline="", compresslevel=9) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(output)
    report = {
        "gate": "STAGE4_FORWARD_G5_ADJUSTMENT_EXTENSION",
        "pass": not errors and len(output) == len(actions),
        "target_session": args.target_session,
        "input_action_rows": len(actions),
        "output_adjustment_rows": len(output),
        "g4_control_rows": len(output),
        "material_share_distribution_override_count": len(overrides),
        "material_share_distribution_overrides": overrides,
        "material_reference_delta_threshold": str(MATERIAL_REFERENCE_DELTA),
        "historical_formula_semantics": "IDENTICAL_TO_BUILD_G5_ADJUSTMENT_FROM_G3",
        "g4_control_semantics": "BAOSTOCK_UNADJUSTED_PRECLOSE_ADJUSTFLAG_3_EXACT_EX_DATE",
        "data_sha256": sha256_bytes(csv_path.read_bytes()),
        "errors": errors,
        "authoritative": False,
        "stage4_feature_support_only": True,
        "alpha_training_allowed": False,
        "live_signal_allowed": False
    }
    (out / "forward_g5_adjustment_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
