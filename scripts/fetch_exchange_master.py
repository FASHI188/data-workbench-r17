#!/usr/bin/env python3
"""Fetch current SSE/SZSE A-share master lists from official exchange endpoints.

Stage-2B rule: source rows are preserved; normalization never upgrades evidence.
Network failures are errors, not empty successful imports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
SSE_PAGE = "https://www.sse.com.cn/assortment/stock/list/share/"
SSE_API = (
    "https://query.sse.com.cn/sseQuery/commonQuery.do"
    "?jsonCallBack=jsonpCallback123456"
    "&STOCK_TYPE=1&REG_PROVINCE=&CSRC_CODE=&STOCK_CODE="
    "&sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L"
    "&COMPANY_STATUS=2%2C4%2C5%2C7%2C8&type=inParams&isPagination=true"
    "&pageHelp.cacheSize=1&pageHelp.beginPage=1&pageHelp.pageSize=4000"
    "&pageHelp.pageNo=1&pageHelp.endPage=1"
)
SZSE_PAGE = "https://www.szse.cn/certificate/maind/"
SZSE_API = (
    "https://www.szse.cn/api/report/ShowReport/data"
    "?SHOWTYPE=JSON&CATALOGID=1110&TABKEY=tab1&PAGENO=1"
)


@dataclass(frozen=True)
class MasterRow:
    exchange: str
    board: str
    security_type: str
    code: str
    name: str
    listing_date: str | None
    source_url: str
    source_row_json: str
    board_basis: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str, referer: str, timeout: int = 30) -> bytes:
    r = requests.get(
        url,
        headers={"User-Agent": UA, "Referer": referer, "Accept": "*/*"},
        timeout=timeout,
    )
    r.raise_for_status()
    if not r.content:
        raise RuntimeError(f"empty response: {url}")
    return r.content


def parse_jsonp(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="strict").strip()
    m = re.match(r"^[^(]+\((.*)\)\s*;?$", text, flags=re.S)
    if m:
        text = m.group(1)
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    return obj


def first_nonempty(d: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = d.get(key)
        if value not in (None, "", "-"):
            return str(value).strip()
    return None


def sse_rows(payload: dict[str, Any]) -> list[MasterRow]:
    raw_rows = payload.get("result") or payload.get("data") or []
    if not isinstance(raw_rows, list):
        raise ValueError("SSE rows are not a list")
    out: list[MasterRow] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        code = first_nonempty(row, ["A_STOCK_CODE", "SECURITY_CODE_A", "STOCK_CODE"])
        name = first_nonempty(row, ["COMPANY_ABBR", "SEC_NAME_CN", "SECURITY_ABBR_A"])
        if not code or not re.fullmatch(r"6\d{5}", code):
            continue
        if not name:
            raise ValueError(f"SSE row missing name for {code}")
        out.append(
            MasterRow(
                exchange="SSE",
                board="MAIN",
                security_type="A_SHARE",
                code=code,
                name=name,
                listing_date=first_nonempty(row, ["LIST_DATE", "LISTING_DATE", "A_LIST_DATE"]),
                source_url=SSE_API,
                source_row_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
                board_basis="OFFICIAL_SSE_STOCK_TYPE_1",
            )
        )
    return out


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)


def szse_rows(payload: Any) -> list[MasterRow]:
    """Parse SZSE CATALOGID=1110 conservatively.

    Prefer explicit code fields. Main-board classification uses explicit board text when
    present; only if absent, the Shenzhen code-family fallback is used and tagged as
    DERIVED_CODE_PREFIX so audit can reject it if a stronger source is required.
    """
    out: dict[str, MasterRow] = {}
    for row in walk_dicts(payload):
        code = first_nonempty(row, ["agdm", "zqdm", "gsdm", "code", "A股代码", "证券代码"])
        name = first_nonempty(row, ["agjc", "zqjc", "gsjc", "name", "A股简称", "证券简称", "公司简称"])
        if not code or not re.fullmatch(r"\d{6}", code) or not name:
            continue

        board_text = first_nonempty(row, ["bk", "ssbk", "board", "板块", "市场板块"]) or ""
        if "创业" in board_text or code.startswith(("300", "301")):
            continue
        if "主板" in board_text:
            basis = "OFFICIAL_SZSE_BOARD_FIELD"
        elif code.startswith(("000", "001", "002", "003")):
            basis = "DERIVED_CODE_PREFIX"
        else:
            continue

        out[code] = MasterRow(
            exchange="SZSE",
            board="MAIN",
            security_type="A_SHARE",
            code=code,
            name=name,
            listing_date=first_nonempty(row, ["agssrq", "ssrq", "listingDate", "上市日期"]),
            source_url=SZSE_API,
            source_row_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
            board_basis=basis,
        )
    return sorted(out.values(), key=lambda x: x.code)


def write_csv(path: Path, rows: list[MasterRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys()) if rows else list(MasterRow.__annotations__.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/current_master")
    ap.add_argument("--allow-derived-szse-board", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    fetched_at = datetime.now(timezone.utc).isoformat()

    sse_raw = get(SSE_API, SSE_PAGE)
    szse_raw = get(SZSE_API, SZSE_PAGE)
    sse = sorted(sse_rows(parse_jsonp(sse_raw)), key=lambda x: x.code)
    szse_payload = json.loads(szse_raw.decode("utf-8"))
    szse = szse_rows(szse_payload)

    if not sse:
        raise RuntimeError("SSE import produced zero rows")
    if not szse:
        raise RuntimeError("SZSE import produced zero rows")
    if not args.allow_derived_szse_board and any(r.board_basis == "DERIVED_CODE_PREFIX" for r in szse):
        raise RuntimeError("SZSE has rows classified only by code prefix; official board evidence required")

    write_csv(out / "sse_main_a.csv", sse)
    write_csv(out / "szse_main_a.csv", szse)
    write_csv(out / "cn_main_a.csv", sorted(sse + szse, key=lambda x: (x.exchange, x.code)))

    manifest = {
        "fetched_at_utc": fetched_at,
        "scope": "SSE_MAIN_A + SZSE_MAIN_A only",
        "sse": {"rows": len(sse), "sha256_raw": sha256_bytes(sse_raw), "url": SSE_API},
        "szse": {"rows": len(szse), "sha256_raw": sha256_bytes(szse_raw), "url": SZSE_API},
        "hard_gate_status": "PASS_CANDIDATE",
        "notes": [
            "PASS_CANDIDATE is not Stage2 PASS until official aggregate/control totals reconcile.",
            "Network or parser failure is fatal; zero-row imports never count as success."
        ]
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
