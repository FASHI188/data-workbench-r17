#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_g5_official_actions as cn  # noqa: E402

BASE = "https://webapi.cninfo.com.cn/api/"
PROFILE = "sysapi/p_sysapi1067"
FIN_APIS = {
    "KEY_RATIOS": "sysapi/p_sysapi1140",
    "BALANCE_SHEET": "sysapi/p_sysapi1143",
    "INCOME_STATEMENT": "sysapi/p_sysapi1141",
    "CASH_FLOW": "sysapi/p_sysapi1142",
}
SAMPLES = ["000001", "600519", "601268", "000022", "001872", "000043", "001914"]
CURRENT_REQUIRED = {"000001", "600519", "001872", "001914"}
VERSION_FIELDS = {
    "DECLAREDATE",
    "ANNOUNCEMENTDATE",
    "ANNOUNCEMENTID",
    "REPORTDATE",
    "UPDATEDATE",
    "MODIFYDATE",
    "VERSION",
    "REVISION",
    "REVISIONID",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def find_sign(obj: Any) -> str | None:
    for d in walk_dicts(obj):
        v = d.get("F002N")
        if v not in (None, ""):
            return str(v)
    return None


def records(obj: Any) -> list:
    if isinstance(obj, dict):
        for key in ("records", "data"):
            v = obj.get(key)
            if isinstance(v, list):
                return v
    return []


def shape(obj: Any) -> dict:
    rs = records(obj)
    dict_rows = [x for x in rs if isinstance(x, dict)]
    keys = sorted({str(k) for r in dict_rows[:30] for k in r.keys()})
    versionish = sorted({k for k in keys if k.upper() in VERSION_FIELDS or any(t in k.upper() for t in ("DECLARE", "ANNOUN", "UPDATE", "MODIFY", "VERSION", "REVISION"))})
    periodish = sorted({k for k in keys if k.upper() in {"ENDDATE", "F001D", "F003D", "REPORTDATE"} or re_year_key(k)})
    return {
        "record_count": len(rs),
        "record_type_sample": sorted({type(x).__name__ for x in rs[:30]}),
        "dict_keys": keys,
        "version_or_publication_fields": versionish,
        "period_fields": periodish,
        "sample_records": rs[:3],
    }


def re_year_key(k: str) -> bool:
    return len(k) == 4 and k.isdigit() and 1900 <= int(k) <= 2100


def call(session: requests.Session, js, api: str, params: dict[str, str]):
    raw, url, obj = cn.cn_post(session, js, BASE + api, params)
    return raw, url, obj


def main() -> int:
    outdir = ROOT / "data/stage3_source_probe"
    outdir.mkdir(parents=True, exist_ok=True)
    js = cn.init_cninfo()
    session = requests.Session()
    errors: list[str] = []
    diagnostics: list[dict] = []
    usable_current = set()
    historical_structured_support = set()
    all_version_fields = set()

    for code in SAMPLES:
        rec: dict[str, Any] = {"code": code, "profile": None, "financial": {}}
        try:
            raw, url, obj = call(session, js, PROFILE, {"scode": code})
            sign = find_sign(obj)
            rec["profile"] = {
                "url": url,
                "sha256": sha(raw),
                "bytes": len(raw),
                "sign_F002N": sign,
                "shape": shape(obj),
            }
        except Exception as exc:
            sign = None
            rec["profile"] = {"error": repr(exc)}

        if not sign:
            rec["status"] = "NO_SIGN_F002N"
            if code in CURRENT_REQUIRED:
                errors.append(f"current required code {code} has no F002N sign")
            diagnostics.append(rec)
            continue

        nonempty_all = True
        for label, api in FIN_APIS.items():
            api_runs = []
            # Annual is mandatory. For 000001 additionally test all four report types
            # to establish whether one code request can cover the full quarterly cadence.
            rtypes = ["1", "2", "3", "4"] if code == "000001" else ["4"]
            for rtype in rtypes:
                try:
                    raw, url, obj = call(
                        session,
                        js,
                        api,
                        {"scode": code, "sign": sign, "rtype": rtype},
                    )
                    sh = shape(obj)
                    all_version_fields.update(sh["version_or_publication_fields"])
                    api_runs.append(
                        {
                            "rtype": rtype,
                            "url": url,
                            "sha256": sha(raw),
                            "bytes": len(raw),
                            "shape": sh,
                        }
                    )
                    if rtype == "4" and sh["record_count"] == 0:
                        nonempty_all = False
                except Exception as exc:
                    nonempty_all = False
                    api_runs.append({"rtype": rtype, "error": repr(exc)})
            rec["financial"][label] = {"api": api, "runs": api_runs}

        if nonempty_all:
            historical_structured_support.add(code)
            if code in CURRENT_REQUIRED:
                usable_current.add(code)
        rec["status"] = "STRUCTURED_FINANCIALS_NONEMPTY" if nonempty_all else "PARTIAL_OR_EMPTY_STRUCTURED_FINANCIALS"
        diagnostics.append(rec)

    missing_current = sorted(CURRENT_REQUIRED - usable_current)
    if missing_current:
        errors.append(f"current required codes lack all four annual financial API datasets: {missing_current}")

    # Point-in-time authority requires publication/revision metadata in the value response.
    # If absent, the API is still an official structured cross-check but cannot silently
    # replace immutable original filing versions in historical training.
    has_revision_semantics = bool(all_version_fields)
    report = {
        "gate": "S3G1D_CNINFO_FINANCIAL_API_REQUEST_PROBE",
        "pass": not errors,
        "profile_api": PROFILE,
        "financial_apis": FIN_APIS,
        "required_params": ["scode", "sign", "rtype"],
        "sample_codes": SAMPLES,
        "current_required_codes": sorted(CURRENT_REQUIRED),
        "current_required_supported": sorted(usable_current),
        "historical_codes_with_all_four_annual_structured_datasets": sorted(historical_structured_support),
        "observed_version_or_publication_fields": sorted(all_version_fields),
        "point_in_time_value_authority": has_revision_semantics,
        "authority_interpretation": (
            "Structured financial responses expose publication/revision semantics and may be considered for PIT value authority only after filing-level reconciliation."
            if has_revision_semantics
            else "Structured financial responses do not expose sufficient publication/revision identity in this probe. Treat them as official structured extraction/cross-check only; immutable historical training values must remain anchored to the original filing revision available at that session."
        ),
        "diagnostics": diagnostics,
        "errors": errors,
    }
    (outdir / "cninfo_financial_api_request_probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "gate": report["gate"],
                "pass": report["pass"],
                "current_required_supported": report["current_required_supported"],
                "historical_codes_with_all_four_annual_structured_datasets": report["historical_codes_with_all_four_annual_structured_datasets"],
                "observed_version_or_publication_fields": report["observed_version_or_publication_fields"],
                "point_in_time_value_authority": report["point_in_time_value_authority"],
                "errors": report["errors"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
