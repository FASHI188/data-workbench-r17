#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz

import stage3_financial_coordinate_fallback_v14 as rows_v14
import stage3_financial_statement_blocks_v16_5 as blocks
import diagnose_stage3_s3g1j_v17_29_six_sources as base

TARGETS: dict[str, dict[str, Any]] = {
    "1223347318": {
        "source_sha256": "d765c94532cd41a496d147da72cbff392bce4ff776b41b88d95dcf3f1fb697c8",
        "source_bytes": 492929,
        "economic_date": "2025-03-31",
        "equity_values": ["1296487058.05", "1276495395.79"],
        "assets_values": ["2250857154.79", "2237673819.93"],
        "liabilities_values": ["954370096.74", "961178424.14"],
    },
    "1223407043": {
        "source_sha256": "7540a56179783625ac256726480ef32faf85a893549057fe9e6546abfd6ee903",
        "source_bytes": 1367714,
        "economic_date": "2024-12-31",
        "equity_values": ["1320477812.85", "1259908009.27"],
        "assets_values": ["1885230514.78", "1750850622.44"],
        "liabilities_values": ["564752701.93", "490942613.17"],
    },
}


def normalize(text: str) -> str:
    return rows_v14._norm(text or "").replace(":", "：").replace("（", "(").replace("）", ")")


def amounts(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rows_v14._numeric_word_candidates(row))


def amount_pair(row: dict[str, Any], expected: list[str]) -> bool:
    wanted = [Decimal(x) for x in expected]
    candidates = amounts(row)
    for start in range(max(0, len(candidates) - 1)):
        pair = candidates[start:start+2]
        if [Decimal(str(item["value"])) for item in pair] == wanted:
            return True
    return False


def row_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(row.get("text") or ""),
        "normalized": normalize(str(row.get("text") or "")),
        "y": str(row.get("y") or ""),
        "x0": min((float(w["x0"]) for w in row.get("words") or []), default=0.0),
        "amounts": [str(x.get("value")) for x in amounts(row)],
    }


def read_rows(documents: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with gzip.open(documents, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            aid = str(row.get("announcement_id") or "")
            if aid in TARGETS:
                out[aid] = row
    if set(out) != set(TARGETS):
        raise ValueError(f"missing cross-page probe rows {sorted(set(TARGETS)-set(out))}")
    return out


def probe_pdf(aid: str, row: dict[str, str], target: dict[str, Any]) -> dict[str, Any]:
    if row.get("selected_source_sha256") != target["source_sha256"]:
        raise ValueError(f"{aid}: temporary diagnostic selected SHA mismatch")
    if int(row.get("selected_source_bytes") or 0) != int(target["source_bytes"]):
        raise ValueError(f"{aid}: temporary diagnostic selected byte mismatch")
    raw = base.fetch_pdf(row["selected_source_url"], target["source_sha256"], target["source_bytes"])
    if hashlib.sha256(raw).hexdigest() != target["source_sha256"]:
        raise ValueError(f"{aid}: exact PDF SHA mismatch after fetch")

    with fitz.open(stream=raw, filetype="pdf") as doc:
        rows_by_page = {page+1: rows_v14._rows_from_words(doc[page]) for page in range(len(doc))}
        events = blocks.formal_statement_events(doc)
        probes: dict[str, list[dict[str, Any]]] = {}
        for concept, expected in (
            ("TOTAL_ASSETS", target["assets_values"]),
            ("TOTAL_LIABILITIES", target["liabilities_values"]),
            ("TOTAL_EQUITY", target["equity_values"]),
        ):
            matches=[]
            for page, rows in rows_by_page.items():
                for idx, item in enumerate(rows):
                    if not amount_pair(item, expected):
                        continue
                    before = [row_summary(x) for x in rows[max(0,idx-4):idx]]
                    after = [row_summary(x) for x in rows[idx+1:min(len(rows),idx+5)]]
                    prev_tail = [row_summary(x) for x in rows_by_page.get(page-1, [])[-5:]] if page > 1 else []
                    next_head = [row_summary(x) for x in rows_by_page.get(page+1, [])[:8]] if page < len(doc) else []
                    event = blocks.bind_alias_to_preceding_statement_event(
                        events, page, float(item.get("y") or 0),
                        min((float(w["x0"]) for w in item.get("words") or []), default=0.0),
                    )
                    matches.append({
                        "page": page,
                        "amount_row": row_summary(item),
                        "before_same_page": before,
                        "after_same_page": after,
                        "previous_page_tail": prev_tail,
                        "next_page_head": next_head,
                        "bound_statement_event": event,
                    })
            probes[concept]=matches

        group_events=[e for e in events if e.get("role")=="GROUP" and "合并资产负债表" in str(e.get("line") or "")]
        parent_events=[e for e in events if e.get("role")=="PARENT" and "母公司资产负债表" in str(e.get("line") or "")]
        if len(group_events) != 1:
            raise ValueError(f"{aid}: expected exactly one formal GROUP balance-sheet event, got {len(group_events)}")
        if len(parent_events) > 1:
            raise ValueError(f"{aid}: multiple formal PARENT balance-sheet events")
        if any(len(probes[c]) != 1 for c in ("TOTAL_ASSETS","TOTAL_LIABILITIES","TOTAL_EQUITY")):
            raise ValueError(f"{aid}: expected one exact A/L/E amount pair probe each")

    identity=[]
    for idx,label in enumerate(("CURRENT","PRIOR")):
        a=Decimal(target["assets_values"][idx]); l=Decimal(target["liabilities_values"][idx]); e=Decimal(target["equity_values"][idx])
        identity.append({"column":label,"assets":str(a),"liabilities":str(l),"equity_explicit_pdf":str(e),"residual":str(a-l-e)})
    if any(Decimal(x["residual"]) != 0 for x in identity):
        raise ValueError(f"{aid}: dual-column A=L+E identity not exact")

    return {
        "announcement_id": aid,
        "source_sha256": target["source_sha256"],
        "source_bytes": target["source_bytes"],
        "economic_date": target["economic_date"],
        "formal_group_balance_sheet_events": group_events,
        "formal_parent_balance_sheet_events": parent_events,
        "amount_pair_probes": probes,
        "dual_column_identity": identity,
        "candidate_parser_authorized": False,
        "diagnostic_only": True,
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--documents", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()
    rows=read_rows(Path(args.documents))
    results=[probe_pdf(aid, rows[aid], TARGETS[aid]) for aid in sorted(TARGETS)]
    report={
        "gate":"S3G1J_V17_29_CROSS_PAGE_EQUITY_WORD_ROW_PROBE_V1",
        "target_count":2,
        "target_ids":sorted(TARGETS),
        "all_exact_source_sha_verified":True,
        "all_dual_column_identity_exact_zero":True,
        "candidate_parser_authorized":False,
        "formal_parser_changed":False,
        "runtime_authority_changed":False,
        "production_data_changed":False,
        "stage3_status":"NOT_READY",
        "stage4_alpha_locked":True,
        "targets":results,
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
