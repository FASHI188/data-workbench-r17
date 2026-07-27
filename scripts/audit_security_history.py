#!/usr/bin/env python3
"""Fail-closed audit for G2 survivorship-free, code-time-aware lifecycle coverage."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/current_master/cn_main_a.csv"
INTERVALS = ROOT / "data/security_lifecycle/security_intervals.csv"
EVENTS = ROOT / "data/security_lifecycle/events.csv"
MANIFEST = ROOT / "data/security_lifecycle/manifest.json"
RAW = ROOT / "data/security_lifecycle/raw"
TRANSITIONS = ROOT / "config/security_code_transitions.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_scope(exchange: str, code: str) -> bool:
    if exchange == "SSE":
        return len(code) == 6 and code.isdigit() and not code.startswith(("688", "689"))
    if exchange == "SZSE":
        if len(code) != 6 or not code.isdigit(): return False
        n = int(code)
        return 1 <= n <= 4999 and not (1001 <= n <= 1199)
    return False


def load_transitions() -> list[dict[str,str]]:
    raw=json.loads(TRANSITIONS.read_text(encoding="utf-8"))
    if not isinstance(raw,list):raise ValueError("transition config not a list")
    return [{k:str(v) for k,v in t.items()} for t in raw]


def main() -> int:
    errors: list[str] = []
    for path in (MASTER, INTERVALS, EVENTS, MANIFEST, TRANSITIONS):
        if not path.exists(): errors.append(f"missing {path.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"gate":"G2","pass":False,"errors":errors},ensure_ascii=False,indent=2));return 2

    master=read_csv(MASTER);intervals=read_csv(INTERVALS);events=read_csv(EVENTS);manifest=json.loads(MANIFEST.read_text(encoding="utf-8"));transitions=load_transitions()
    current_master={(r["exchange"],r["code"]) for r in master}
    current_intervals={(r["exchange"],r["code"]) for r in intervals if not (r.get("listed_to_exclusive") or "").strip()}
    if current_master!=current_intervals:
        only_master=sorted(current_master-current_intervals);only_history=sorted(current_intervals-current_master)
        errors.append(f"current projection mismatch: only_master={len(only_master)}, only_history={len(only_history)}, sample_master={only_master[:10]}, sample_history={only_history[:10]}")

    interval_by_key={}
    for row in intervals:
        key=(row["exchange"],row["code"])
        if key in interval_by_key:errors.append(f"multiple intervals for security identity: {key}")
        interval_by_key[key]=row
    for row in events:
        if not valid_scope(row.get("exchange",""),row.get("code","")):errors.append(f"out-of-scope lifecycle event: {row.get('exchange')}:{row.get('code')}")
    for row in intervals:
        if not valid_scope(row.get("exchange",""),row.get("code","")):errors.append(f"out-of-scope lifecycle interval: {row.get('exchange')}:{row.get('code')}")
        try:
            a=date.fromisoformat(row["listed_from"]);b=date.fromisoformat(row["listed_to_exclusive"]) if row.get("listed_to_exclusive") else None
            if b is not None and b<=a:errors.append(f"non-positive interval: {row}")
        except Exception:errors.append(f"invalid interval dates: {row}")

    delists=[r for r in events if r.get("event_type")=="DELIST"];delist_keys={(r.get("exchange",""),r.get("code","")) for r in delists}
    if len(delist_keys)!=len(delists):errors.append("duplicate DELIST security keys")
    for exchange in ("SSE","SZSE"):
        if sum(r.get("exchange")==exchange for r in delists)==0:errors.append(f"no historical DELIST events for {exchange}")
    current_delisted_overlap=current_master&delist_keys
    if current_delisted_overlap:errors.append(f"current/delisted overlap: {sorted(current_delisted_overlap)[:20]}")

    transition_old_keys=set();transition_new_keys=set();transition_controls=manifest.get("controls",{}).get("code_transitions",[]) or [];control_by_pair={(str(x.get("exchange")),str(x.get("old_code")),str(x.get("new_code"))):x for x in transition_controls}
    for t in transitions:
        ex=t["exchange"];old=t["old_code"];new=t["new_code"];eff=t["effective_date"];oldk=(ex,old);newk=(ex,new)
        if oldk in transition_old_keys or newk in transition_new_keys:errors.append(f"duplicate transition identity: {t}")
        transition_old_keys.add(oldk);transition_new_keys.add(newk)
        oldi=interval_by_key.get(oldk);newi=interval_by_key.get(newk)
        if oldi is None:errors.append(f"transition predecessor interval missing: {oldk}")
        else:
            if oldi.get("listed_to_exclusive")!=eff:errors.append(f"transition predecessor end mismatch {oldk}: {oldi.get('listed_to_exclusive')} != {eff}")
            if oldi.get("delist_evidence_class")!=t["evidence_class"]:errors.append(f"transition predecessor evidence mismatch {oldk}")
        if newi is None:errors.append(f"transition successor interval missing: {newk}")
        else:
            if newi.get("listed_from")!=eff:errors.append(f"transition successor start mismatch {newk}: {newi.get('listed_from')} != {eff}")
            if (newi.get("listed_to_exclusive") or "").strip():errors.append(f"transition successor unexpectedly closed: {newk}")
            if newi.get("list_evidence_class")!=t["evidence_class"]:errors.append(f"transition successor evidence mismatch {newk}")
        ctrl=control_by_pair.get((ex,old,new))
        if ctrl is None:errors.append(f"transition manifest control missing: {old}->{new}")
        else:
            if str(ctrl.get("effective_date"))!=eff or str(ctrl.get("source_sha256"))!=t["source_sha256"]:errors.append(f"transition manifest control mismatch: {old}->{new}")
            raw_file=RAW/str(ctrl.get("raw_file") or "")
            if not raw_file.exists():errors.append(f"transition raw evidence missing: {raw_file.relative_to(ROOT)}")
            elif file_sha256(raw_file)!=t["source_sha256"]:errors.append(f"transition raw evidence SHA mismatch: {raw_file.name}")

    closed_intervals=[r for r in intervals if (r.get("listed_to_exclusive") or "").strip()];closed_keys={(r["exchange"],r["code"]) for r in closed_intervals};expected_closed=delist_keys|transition_old_keys
    if closed_keys!=expected_closed:
        errors.append(f"closed interval evidence mismatch: intervals={len(closed_keys)} delists={len(delist_keys)} transitions={len(transition_old_keys)} only_intervals={sorted(closed_keys-expected_closed)[:10]} only_expected={sorted(expected_closed-closed_keys)[:10]}")

    effective_dates=[]
    for row in events:
        try:effective_dates.append(date.fromisoformat(row["effective_date"]))
        except Exception:errors.append(f"invalid effective_date for {row.get('exchange')}:{row.get('code')}")
    if effective_dates and min(effective_dates)>date(2015,1,1):errors.append(f"lifecycle evidence does not reach 2015-01-01; earliest={min(effective_dates)}")

    counts=manifest.get("counts",{});expected_current=int(counts.get("current_active") or -1);expected_delisted=int(counts.get("delisted_a_all_history") or -1);expected_intervals=int(counts.get("expected_intervals") or -1);expected_events=int(counts.get("lifecycle_events") or -1);expected_transitions=int(counts.get("code_transitions") or -1)
    if len(current_master)!=expected_current:errors.append(f"manifest current_active mismatch: {expected_current} != {len(current_master)}")
    if len(delists)!=expected_delisted:errors.append(f"manifest delisted count mismatch: {expected_delisted} != {len(delists)}")
    if len(intervals)!=expected_intervals:errors.append(f"manifest interval count mismatch: {expected_intervals} != {len(intervals)}")
    if len(events)!=expected_events:errors.append(f"manifest event count mismatch: {expected_events} != {len(events)}")
    if len(transitions)!=expected_transitions:errors.append(f"manifest code-transition count mismatch: {expected_transitions} != {len(transitions)}")

    controls=manifest.get("controls",{});raw_checks=[(RAW/"sse_main_a_status3_delisted.jsonp",controls.get("sse",{}).get("delisted_source_sha256")),(RAW/"sse_main_a_all_statuses.jsonp",controls.get("sse",{}).get("all_status_source_sha256")),(RAW/"szse_main_delisted_selectModule_main.xlsx",controls.get("szse",{}).get("source_sha256"))]
    for path,expected_sha in raw_checks:
        if not path.exists():errors.append(f"missing raw lifecycle source: {path.relative_to(ROOT)}");continue
        actual=file_sha256(path)
        if not expected_sha or actual!=expected_sha:errors.append(f"raw source SHA mismatch: {path.name}")
    if controls.get("sse",{}).get("state_partition_exact") is not True:errors.append("SSE active+delisted state partition is not exact")
    if controls.get("szse",{}).get("current_delisted_disjoint") is not True:errors.append("SZSE current/delisted sets are not proven disjoint")
    szse_class_counts=controls.get("szse",{}).get("class_counts",{})
    if int(szse_class_counts.get("UNKNOWN") or 0)!=0:errors.append(f"SZSE historical workbook contains unknown security classes: {szse_class_counts}")
    if manifest.get("historical_backfill_complete") is not True:errors.append("historical_backfill_complete is not true")
    if manifest.get("coverage_start")!="2015-01-01":errors.append("coverage_start is not 2015-01-01")
    if not manifest.get("coverage_end"):errors.append("coverage_end missing")

    report={"gate":"G2","pass":not errors,"current_master_count":len(current_master),"current_open_interval_count":len(current_intervals),"closed_interval_count":len(closed_intervals),"delist_events":len(delists),"code_transitions":len(transitions),"total_intervals":len(intervals),"total_events":len(events),"errors":errors}
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if not errors else 2


if __name__=="__main__":sys.exit(main())
