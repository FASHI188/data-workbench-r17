#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import build_stage3_filing_ledger as filing_base

TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
STOCK_MAP_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
STATIC_ROOT = "https://static.cninfo.com.cn/"
PAGE_SIZE = 30
FROZEN_END = date(2026, 7, 24)
START = date(2026, 7, 25)
END = date(2026, 8, 12)
ANNOUNCEMENT_CATEGORIES = {
    "EARNINGS_FORECAST": "category_yjygjxz_szsh", "DAILY_OPERATION": "category_rcjy_szsh",
    "EQUITY_CHANGE": "category_gqbd_szsh", "CORRECTION_SUPPLEMENT": "category_bcgz_szsh",
    "CLARIFICATION_APOLOGY": "category_cqdq_szsh", "RISK_WARNING": "category_fxts_szsh",
    "SPECIAL_TREATMENT_DELISTING": "category_tbclts_szsh", "DELISTING_PERIOD": "category_tszlq_szsh",
    "UNLOCK": "category_jj_szsh", "EQUITY_INCENTIVE": "category_gqjl_szsh",
    "ADDITIONAL_ISSUANCE": "category_zf_szsh", "RIGHTS_ISSUE": "category_pg_szsh",
    "CONVERTIBLE_BOND": "category_kzzq_szsh", "OTHER_FINANCING": "category_qtrz_szsh",
}
FILING_CATEGORIES = {k: v[0] for k, v in filing_base.CATEGORIES.items()}
ANNOUNCEMENT_FIELDS = ["exchange","query_code","code","source_instrument_code","org_id","event_category","announcement_id","announcement_title","source_published_date","publication_precision","effective_session","available_at","source_url","query_plate","query_page","query_response_sha256"]
FILING_FIELDS = ["exchange","source_code","effective_code","org_id","report_family","announcement_id","announcement_title","source_published_at","publication_precision","economic_date","effective_session","available_at","usable_in_stage2","availability_reason","revision_kind","revision_sequence","supersedes_announcement_id","is_full_report_candidate","source_url","query_page","query_response_sha256"]
SESSIONS: list[date] = []

def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()

def pubdate(item: dict) -> str:
    try: ms = int(item.get("announcementTime"))
    except Exception: return ""
    return datetime.fromtimestamp(ms / 1000, tz=ZoneInfo("UTC")).astimezone(TZ).date().isoformat()

def next_session(day: date, sessions: list[date]) -> date | None:
    idx = bisect.bisect_right(sessions, day)
    return sessions[idx] if idx < len(sessions) else None

def _date8(value: str) -> date | None:
    s = str(value or "").replace("-", "")
    if len(s) == 8 and s.isdigit(): return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return None

def load_master(path: Path) -> tuple[dict[str, dict], set[str]]:
    by_code = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = str(r.get("code") or "")
            if len(code) != 6 or not code.isdigit(): raise ValueError(f"invalid current-master code {code!r}")
            if code in by_code: raise ValueError(f"duplicate current-master code {code}")
            by_code[code] = r
    if not by_code: raise ValueError("empty current master")
    return by_code, set(by_code)

def load_sessions(phase2_root: Path, phase3_manifest: Path) -> list[date]:
    days: set[date] = set()
    for p in sorted(phase2_root.rglob("*.csv.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                if not rd.fieldnames or "trade_date" not in rd.fieldnames: continue
                for r in rd:
                    if r.get("trade_date"): days.add(date.fromisoformat(r["trade_date"]))
        except OSError: continue
    p3 = json.loads(phase3_manifest.read_text(encoding="utf-8"))
    next_s = str((p3.get("audit") or {}).get("next_session") or "")
    if next_s: days.add(date.fromisoformat(next_s))
    out = sorted(days)
    if not out or out[-1] < END: raise ValueError(f"insufficient forward sessions last={out[-1] if out else None}")
    return out

def query_payload(plate: str, category: str, start: date, end: date, page: int) -> dict[str, str]:
    return {"pageNum":str(page),"pageSize":str(PAGE_SIZE),"column":"szse","tabName":"fulltext","plate":plate,"stock":"","searchkey":"","secid":"","category":category,"trade":"","seDate":f"{start.isoformat()}~{end.isoformat()}","sortName":"","sortType":"","isHLtitle":"true"}

def post_json(session: requests.Session, payload: dict[str, str], attempts: int = 6) -> tuple[bytes, dict]:
    last = None
    for i in range(attempts):
        try:
            r = session.post(QUERY_URL, data=payload, headers={"User-Agent":UA,"Referer":"https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search","X-Requested-With":"XMLHttpRequest"}, timeout=60)
            r.raise_for_status(); obj = r.json()
            if not isinstance(obj, dict) or "announcements" not in obj: raise ValueError("unexpected CNINFO payload")
            return r.content, obj
        except Exception as exc:
            last = exc
            if i + 1 < attempts: time.sleep(min(0.8 * (2 ** i), 10.0))
    raise RuntimeError(f"CNINFO query failed: {last!r}")

def get_stock_map(session: requests.Session) -> tuple[bytes, list[dict]]:
    last = None
    for i in range(6):
        try:
            r = session.get(STOCK_MAP_URL, headers={"User-Agent":UA,"Referer":"https://www.cninfo.com.cn/"}, timeout=60); r.raise_for_status()
            return r.content, r.json().get("stockList") or []
        except Exception as exc:
            last = exc
            if i < 5: time.sleep(min(0.8 * (2 ** i), 10.0))
    raise RuntimeError(f"CNINFO stock map failed: {last!r}")

def org_equity_map(stock_rows: list[dict], master_codes: set[str]) -> dict[str, list[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for r in stock_rows:
        code, org = str(r.get("code") or ""), str(r.get("orgId") or "")
        if code in master_codes and org: out[org].add(code)
    return {org: sorted(codes) for org, codes in out.items()}

def map_identity(item: dict, master: dict[str, dict], by_org: dict[str, list[str]]) -> tuple[str | None, str, str, str | None]:
    returned, org = str(item.get("secCode") or ""), str(item.get("orgId") or "")
    if returned in master: return returned, returned, org, None
    mapped = by_org.get(org, []) if org else []
    if len(mapped) == 1: return mapped[0], returned, org, "SAME_ISSUER_NON_EQUITY_INSTRUMENT"
    if len(mapped) > 1: return None, returned, org, f"AMBIGUOUS_ORG_TO_EQUITY:{org}:{mapped}"
    return None, returned, org, None

def fetch_category(session, plate, label, category, start, end, master, by_org, kind):
    out_ann, out_fil, errors = [], [], []
    meta = {"kind":kind,"plate":plate,"label":label,"category":category,"pages":0,"source_total":0,"raw_rows":0,"in_scope_rows":0,"off_scope_rows":0,"page_sha256":[]}
    raw, obj = post_json(session, query_payload(plate, category, start, end, 1)); total = int(obj.get("totalAnnouncement") or 0); pages = max(1, math.ceil(total / PAGE_SIZE)); packs=[(1,raw,obj)]
    for pn in range(2,pages+1): packs.append((pn,*post_json(session,query_payload(plate,category,start,end,pn)))); time.sleep(0.02)
    meta["pages"], meta["source_total"] = pages, total; seen=set()
    for pn,page_raw,page_obj in packs:
        anns=page_obj.get("announcements") or []; meta["raw_rows"] += len(anns); digest=sha(page_raw); meta["page_sha256"].append({"page":pn,"sha256":digest,"rows":len(anns)})
        for item in anns:
            aid=str(item.get("announcementId") or "")
            if not aid: errors.append(f"missing announcementId {kind}:{plate}:{label}:page={pn}"); continue
            code,source_inst,org,map_note=map_identity(item,master,by_org)
            if code is None:
                if map_note: errors.append(f"{map_note}:aid={aid}")
                else: meta["off_scope_rows"] += 1
                continue
            pub=pubdate(item)
            if not pub: errors.append(f"missing publication date aid={aid}"); continue
            pub_day=date.fromisoformat(pub); listing=_date8(master[code].get("listing_date"))
            if listing and pub_day < listing: meta["off_scope_rows"] += 1; continue
            key=(aid,label)
            if key in seen: continue
            seen.add(key); eff=next_session(pub_day,SESSIONS); available=datetime.combine(eff,datetime.min.time(),tzinfo=TZ).isoformat() if eff else ""; u=str(item.get("adjunctUrl") or "").lstrip("/"); source_url=STATIC_ROOT+u if u else ""; title=str(item.get("announcementTitle") or "")
            if kind == "announcement":
                out_ann.append({"exchange":master[code]["exchange"],"query_code":code,"code":code,"source_instrument_code":source_inst,"org_id":org,"event_category":label,"announcement_id":aid,"announcement_title":title,"source_published_date":pub,"publication_precision":"DATE_ONLY","effective_session":eff.isoformat() if eff else "","available_at":available,"source_url":source_url,"query_plate":plate,"query_page":str(pn),"query_response_sha256":digest})
            else:
                econ,revision,is_full=filing_base.classify_title(title,label)
                out_fil.append({"exchange":master[code]["exchange"],"source_code":code,"effective_code":code,"org_id":org,"report_family":label,"announcement_id":aid,"announcement_title":title,"source_published_at":pub,"publication_precision":"DATE_ONLY","economic_date":econ,"effective_session":eff.isoformat() if eff else "","available_at":available,"usable_in_stage2":"1" if eff else "0","availability_reason":"DATE_ONLY_NEXT_TRADING_SESSION" if eff else "NO_KNOWN_LATER_SESSION","revision_kind":revision,"revision_sequence":"","supersedes_announcement_id":"","is_full_report_candidate":"1" if is_full else "0","source_url":source_url,"query_page":str(pn),"query_response_sha256":digest})
            meta["in_scope_rows"] += 1
    if meta["raw_rows"] < total: errors.append(f"pagination shortfall {kind}:{plate}:{label} total={total} rows={meta['raw_rows']}")
    return out_ann,out_fil,errors,meta

def write_gz(path,fields,rows):
    with gzip.open(path,"wt",encoding="utf-8",newline="",compresslevel=9) as f: w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--master",required=True); ap.add_argument("--phase2-root",required=True); ap.add_argument("--phase3-manifest",required=True); ap.add_argument("--out",required=True); ap.add_argument("--start",default=START.isoformat()); ap.add_argument("--end",default=END.isoformat()); args=ap.parse_args()
    global SESSIONS
    start,end=date.fromisoformat(args.start),date.fromisoformat(args.end)
    if start <= FROZEN_END or end < start: raise ValueError(f"invalid forward window {start}..{end}")
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True); master,master_codes=load_master(Path(args.master)); SESSIONS=load_sessions(Path(args.phase2_root),Path(args.phase3_manifest)); session=requests.Session(); stock_raw,stock_rows=get_stock_map(session); by_org=org_equity_map(stock_rows,master_codes)
    announcements=[]; filings=[]; errors=[]; queries=[]
    for plate in ("sh","sz"):
        for label,category in ANNOUNCEMENT_CATEGORIES.items():
            a,f,e,m=fetch_category(session,plate,label,category,start,end,master,by_org,"announcement"); announcements.extend(a); filings.extend(f); errors.extend(e); queries.append(m)
        for label,category in FILING_CATEGORIES.items():
            a,f,e,m=fetch_category(session,plate,label,category,start,end,master,by_org,"filing"); announcements.extend(a); filings.extend(f); errors.extend(e); queries.append(m)
    ann_keyed={}; fil_keyed={}
    for r in announcements: ann_keyed.setdefault((r["exchange"],r["code"],r["announcement_id"],r["event_category"]),r)
    for r in filings: fil_keyed.setdefault((r["exchange"],r["source_code"],r["announcement_id"],r["report_family"]),r)
    announcements=sorted(ann_keyed.values(),key=lambda r:(r["source_published_date"],r["exchange"],r["code"],r["announcement_id"],r["event_category"])); filings=sorted(fil_keyed.values(),key=lambda r:(r["source_published_at"],r["exchange"],r["source_code"],r["announcement_id"],r["report_family"]))
    for r in announcements:
        if not r["announcement_id"] or not r["query_response_sha256"]: errors.append(f"announcement contract identity/hash missing {r}")
        if r["effective_session"] and r["effective_session"] <= r["source_published_date"]: errors.append(f"same-day announcement use forbidden aid={r['announcement_id']}")
    for r in filings:
        if r["is_full_report_candidate"] == "1" and (not r["economic_date"] or not r["source_url"]): errors.append(f"full filing missing period/url aid={r['announcement_id']}")
        if r["effective_session"] and r["effective_session"] <= r["source_published_at"]: errors.append(f"same-day filing use forbidden aid={r['announcement_id']}")
    ann_path=out/"forward_announcement_ledger.csv.gz"; fil_path=out/"forward_periodic_filing_ledger.csv.gz"; write_gz(ann_path,ANNOUNCEMENT_FIELDS,announcements); write_gz(fil_path,FILING_FIELDS,filings)
    manifest={"gate":"FORWARD_FINANCIAL_AND_ANNOUNCEMENT_SOURCE_LEDGER","pass":not errors,"frozen_coverage_end":FROZEN_END.isoformat(),"coverage_start":start.isoformat(),"coverage_end":end.isoformat(),"current_universe":len(master),"stock_map_rows":len(stock_rows),"stock_map_sha256":sha(stock_raw),"announcement_rows":len(announcements),"filing_rows":len(filings),"full_report_candidates":sum(r["is_full_report_candidate"]=="1" for r in filings),"announcement_sha256":sha(ann_path.read_bytes()),"filing_sha256":sha(fil_path.read_bytes()),"query_count":len(queries),"query_pages":sum(int(q["pages"]) for q in queries),"queries":queries,"errors":errors,"announcement_semantics":"metadata/category presence only; no scalar magnitude inferred from title","date_only_policy":"first strictly later observed trading session; same-day use forbidden","authoritative":False}
    (out/"forward_disclosure_source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({k:manifest[k] for k in ("pass","current_universe","announcement_rows","filing_rows","full_report_candidates","query_pages","errors")},ensure_ascii=False)); return 0 if not errors else 2
if __name__ == "__main__": raise SystemExit(main())
