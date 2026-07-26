#!/usr/bin/env python3
"""Fetch current SSE/SZSE A-share master lists from official exchange endpoints.

Stage-2B rule: source rows are preserved; normalization never upgrades evidence.
Network failures, pagination truncation and empty imports are errors.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
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
SZSE_API_BASE = (
    "https://www.szse.cn/api/report/ShowReport/data"
    "?SHOWTYPE=JSON&CATALOGID=1110&TABKEY=tab1&PAGENO={page}"
)
SZSE_API = SZSE_API_BASE.format(page=1)


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


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
        }
    )
    return s


def warm(session: requests.Session, url: str) -> None:
    """Best-effort page warmup. The exchange API remains the evidence source."""
    try:
        session.get(url, timeout=20)
    except requests.RequestException:
        pass


def get(
    url: str,
    referer: str,
    *,
    origin: str | None = None,
    session: requests.Session | None = None,
    timeout: int = 30,
    attempts: int = 3,
) -> bytes:
    s = session or make_session()
    headers = {
        "Referer": referer,
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if origin:
        headers["Origin"] = origin
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = s.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            if not r.content:
                raise RuntimeError(f"empty response: {url}")
            return r.content
        except (requests.RequestException, RuntimeError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(0.5 * attempt)
    assert last is not None
    raise last


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


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]*>", "", value)
    return re.sub(r"\s+", " ", value).strip()


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
        if code.startswith(("688", "689")):
            continue
        list_board = first_nonempty(row, ["LIST_BOARD", "BOARD_CODE"])
        if list_board not in (None, "1"):
            continue
        if not name:
            raise ValueError(f"SSE row missing name for {code}")
        out.append(
            MasterRow(
                exchange="SSE",
                board="MAIN",
                security_type="A_SHARE",
                code=code,
                name=clean_text(name),
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


def szse_metadata(payload: Any) -> dict[str, Any]:
    for row in walk_dicts(payload):
        meta = row.get("metadata")
        if isinstance(meta, dict) and str(meta.get("catalogid")) == "1110":
            return meta
    raise ValueError("SZSE metadata catalogid=1110 not found")


def szse_rows(payload: Any, source_url: str = SZSE_API) -> list[MasterRow]:
    """Parse one or more SZSE CATALOGID=1110 payloads conservatively."""
    out: dict[str, MasterRow] = {}
    for row in walk_dicts(payload):
        code = first_nonempty(row, ["agdm", "zqdm", "gsdm", "code", "A股代码", "证券代码"])
        name = first_nonempty(row, ["agjc", "zqjc", "gsjc", "name", "A股简称", "证券简称", "公司简称"])
        if not code or not re.fullmatch(r"\d{6}", code) or not name:
            continue

        board_text = clean_text(first_nonempty(row, ["bk", "ssbk", "board", "板块", "市场板块"]) or "")
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
            name=clean_text(name),
            listing_date=first_nonempty(row, ["agssrq", "ssrq", "listingDate", "上市日期"]),
            source_url=source_url,
            source_row_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
            board_basis=basis,
        )
    return sorted(out.values(), key=lambda x: x.code)


def fetch_sse() -> tuple[bytes, list[MasterRow]]:
    s = make_session()
    warm(s, SSE_PAGE)
    raw = get(SSE_API, SSE_PAGE, origin="https://www.sse.com.cn", session=s)
    rows = sorted(sse_rows(parse_jsonp(raw)), key=lambda x: x.code)
    return raw, rows


def fetch_szse_all() -> tuple[list[bytes], list[MasterRow], dict[str, Any]]:
    s = make_session()
    warm(s, SZSE_PAGE)

    page1_url = SZSE_API_BASE.format(page=1)
    raw1 = get(page1_url, SZSE_PAGE, origin="https://www.szse.cn", session=s)
    payload1 = json.loads(raw1.decode("utf-8"))
    meta = szse_metadata(payload1)
    pagecount = int(meta.get("pagecount") or 0)
    recordcount = int(meta.get("recordcount") or 0)
    if pagecount < 1 or recordcount < 1:
        raise RuntimeError(f"invalid SZSE pagination metadata: {meta}")

    raws = [raw1]
    rows_by_code: dict[str, MasterRow] = {r.code: r for r in szse_rows(payload1, page1_url)}
    for page in range(2, pagecount + 1):
        url = SZSE_API_BASE.format(page=page)
        raw = get(url, SZSE_PAGE, origin="https://www.szse.cn", session=s)
        payload = json.loads(raw.decode("utf-8"))
        raws.append(raw)
        for r in szse_rows(payload, url):
            rows_by_code[r.code] = r

    # Count every A-share row before main-board filtering to detect pagination truncation.
    all_codes: set[str] = set()
    for raw in raws:
        payload = json.loads(raw.decode("utf-8"))
        for row in walk_dicts(payload):
            code = first_nonempty(row, ["agdm"])
            if code and re.fullmatch(r"\d{6}", code):
                all_codes.add(code)
    if len(all_codes) != recordcount:
        raise RuntimeError(
            f"SZSE pagination incomplete: metadata recordcount={recordcount}, unique A-share rows={len(all_codes)}"
        )

    return raws, sorted(rows_by_code.values(), key=lambda x: x.code), meta


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

    sse_raw, sse = fetch_sse()
    szse_raws, szse, szse_meta = fetch_szse_all()

    if not sse:
        raise RuntimeError("SSE import produced zero rows")
    if not szse:
        raise RuntimeError("SZSE import produced zero rows")
    if not args.allow_derived_szse_board and any(r.board_basis == "DERIVED_CODE_PREFIX" for r in szse):
        raise RuntimeError("SZSE has rows classified only by code prefix; official board evidence required")

    write_csv(out / "sse_main_a.csv", sse)
    write_csv(out / "szse_main_a.csv", szse)
    write_csv(out / "cn_main_a.csv", sorted(sse + szse, key=lambda x: (x.exchange, x.code)))

    szse_digest = hashlib.sha256()
    for raw in szse_raws:
        szse_digest.update(raw)
        szse_digest.update(b"\n")

    manifest = {
        "fetched_at_utc": fetched_at,
        "scope": "SSE_MAIN_A + SZSE_MAIN_A only",
        "sse": {
            "rows": len(sse),
            "sha256_raw": sha256_bytes(sse_raw),
            "url": SSE_API,
        },
        "szse": {
            "rows": len(szse),
            "sha256_all_pages": szse_digest.hexdigest(),
            "pagecount": int(szse_meta.get("pagecount") or 0),
            "recordcount_all_a": int(szse_meta.get("recordcount") or 0),
            "as_of": str(szse_meta.get("subname") or "").strip(),
            "url_template": SZSE_API_BASE,
        },
        "hard_gate_status": "PASS_CANDIDATE",
        "notes": [
            "PASS_CANDIDATE is not Stage2 PASS until independent official controls reconcile.",
            "Network, parser or pagination failure is fatal; zero-row and truncated imports never count as success.",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
