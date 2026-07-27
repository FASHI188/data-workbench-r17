#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
URLS = [
    {
        "role": "CONTEMPORANEOUS_PRECHANGE_NOTICE",
        "url": "https://static.cninfo.com.cn/finalpage/2018-02-02/1204386750.PDF",
        "expected_old_code": "601313",
        "expected_new_code": "601360",
        "expected_effective_date": "2018-02-28",
    },
    {
        "role": "POSTCHANGE_PRIMARY_CONFIRMATION",
        "url": "https://static.cninfo.com.cn/finalpage/2018-04-27/1204804713.PDF",
        "expected_old_code": "601313",
        "expected_new_code": "601360",
        "expected_effective_date": "2018-02-28",
    },
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    out = ROOT / "data/stage3_source_probe"
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    evidence = []
    errors = []
    for spec in URLS:
        try:
            r = s.get(spec["url"], headers={"User-Agent":UA,"Referer":"https://www.cninfo.com.cn/"}, timeout=60)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                raise ValueError(f"not PDF content-type={r.headers.get('Content-Type')}")
            evidence.append({
                **spec,
                "bytes": len(r.content),
                "sha256": sha(r.content),
                "content_type": r.headers.get("Content-Type"),
            })
        except Exception as exc:
            errors.append(f"{spec['role']}: {exc!r}")
    report = {
        "gate": "SECURITY_CODE_TRANSITION_601313_TO_601360_EVIDENCE",
        "pass": len(evidence) == len(URLS) and not errors,
        "exchange": "SSE",
        "old_code": "601313",
        "new_code": "601360",
        "old_name": "江南嘉捷",
        "new_name": "三六零",
        "effective_date": "2018-02-28",
        "evidence": evidence,
        "errors": errors,
    }
    (out / "transition_601313_601360.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
