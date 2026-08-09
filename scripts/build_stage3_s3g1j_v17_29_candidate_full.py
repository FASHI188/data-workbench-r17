#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from collections import Counter
from pathlib import Path

import requests

import stage3_financial_pdf_parser_v21_candidate as candidate

SOURCE_DOCUMENTS_SHA256 = "7589750684ec26280c095d4b3a2d21b114c6bb77a882f4633c2ea128de5f38f3"
SOURCE_VALUES_SHA256 = "2c6e6255be58e86a0b24b889a67e8dccb43835eb9770ca690dde7429b477bbf7"
SOURCE_DOCUMENT_ROWS = 121354
SOURCE_NUMERIC_ROWS = 1051799
TARGET_COUNT = 7
TARGET_NUMERIC_ROWS = 21
CANDIDATE_NUMERIC_ROWS = 1051820
SOURCE_ERRORS = 1371
CANDIDATE_ERRORS = 1364
SOURCE_UNRESOLVED_TIES = 1288
CANDIDATE_UNRESOLVED_TIES = 1281
TARGET_IDS = tuple(sorted(t["announcement_id"] for t in candidate.TARGETS.values()))
TARGETS_BY_AID = {t["announcement_id"]: {"source_sha256": sha, **t} for sha, t in candidate.TARGETS.items()}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def read_gz(path: Path) -> tuple[list[str], list[dict[str,str]]]:
    with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
        r=csv.DictReader(f); return list(r.fieldnames or []), list(r)


def write_gz(path: Path, fieldnames: list[str], rows: list[dict[str,str]]) -> None:
    buf=io.StringIO(newline=''); w=csv.DictWriter(buf,fieldnames=fieldnames,lineterminator='\n'); w.writeheader(); w.writerows(rows)
    raw=buf.getvalue().encode('utf-8')
    with path.open('wb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as gz: gz.write(raw)


def row_counter(rows: list[dict[str,str]], fields: list[str]) -> Counter[tuple[str,...]]:
    return Counter(tuple(r.get(k,'') for k in fields) for r in rows)


def semantic_sha(rows: list[dict[str,str]], fields: list[str]) -> str:
    h=hashlib.sha256()
    for tup,count in sorted(row_counter(rows,fields).items()):
        h.update(json.dumps([list(tup),count],ensure_ascii=False,separators=(',',':')).encode('utf-8')); h.update(b'\n')
    return h.hexdigest()


def tie_taxonomy(rows: list[dict[str,str]]) -> dict[str,int]:
    c=Counter(r.get('tie_resolution','') for r in rows)
    return {"TIE_SOURCE_INCOMPLETE":c['TIE_SOURCE_INCOMPLETE'],"TIE_VALUE_CONFLICT":c['TIE_VALUE_CONFLICT']}


def download(session: requests.Session, url: str) -> bytes:
    last=None
    for attempt in range(1,7):
        try:
            res=session.get(url,timeout=(30,180)); res.raise_for_status(); raw=res.content
            if not raw.startswith(b'%PDF'): raise ValueError(f'not PDF {url}')
            return raw
        except Exception as exc:
            last=exc
            if attempt<6: time.sleep(attempt*5)
    raise RuntimeError(f'download failed {url}: {last}')


def equity_debug(raw: bytes, target: dict) -> list[dict]:
    """Read-only failure context; never participates in candidate acceptance."""
    out=[]
    with candidate.fitz.open(stream=raw,filetype='pdf') as doc:
        events=candidate.blocks.formal_statement_events(doc)
        rows_by_page=candidate._rows_by_page(doc)
        for page,rows in rows_by_page.items():
            for idx,row in enumerate(rows):
                pair=candidate._amount_pair(row,target['values']['TOTAL_EQUITY'])
                if pair is None: continue
                before=[]
                for pos in range(max(0,idx-5),idx+1):
                    r=rows[pos]
                    event=candidate._bind(events,page,r)
                    before.append({
                        'offset':pos-idx,
                        'text':str(r.get('text') or ''),
                        'normalized':candidate._normalize(str(r.get('text') or '')),
                        'y':str(r.get('y')),
                        'event_role':None if event is None else event.get('role'),
                        'event_page':None if event is None else event.get('page'),
                        'event_line':None if event is None else event.get('line'),
                    })
                out.append({
                    'page':page,
                    'amount_row_text':str(row.get('text') or ''),
                    'amount_pair':[str(item.get('value')) for item in pair],
                    'context':before,
                })
    return out


def candidate_value_row(doc: dict[str,str], target: dict, concept: str, obs: dict) -> dict[str,str]:
    return {
        "exchange":doc["exchange"],"source_code":doc["source_code"],"effective_code":doc["effective_code"],"issuer_org_id":doc["issuer_org_id"],
        "report_family":doc["report_family"],"economic_date":doc["economic_date"],"announcement_id":doc["announcement_id"],"revision_sequence":doc["revision_sequence"],
        "source_published_at":doc["source_published_at"],"effective_session":doc["effective_session"],"available_at":doc["available_at"],"concept":concept,
        "raw_value":str(obs.get("raw_value") or ""),"normalized_cny_value":str(obs["normalized_cny_value"]),"unit":"元","unit_multiplier":"1",
        "source_url":target["source_url"],"source_sha256":target["source_sha256"],"source_format":"PDF","extraction_method":candidate.METHOD,
        "methodology_version":candidate.METHODOLOGY_VERSION,"page":str(obs["page"]),"matched_alias":str(obs["matched_alias"]),"confidence":str(obs.get("confidence") or "HIGH"),
    }


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--documents',required=True); ap.add_argument('--values',required=True); ap.add_argument('--out',required=True)
    args=ap.parse_args(); documents_path=Path(args.documents); values_path=Path(args.values); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    if sha256(documents_path)!=SOURCE_DOCUMENTS_SHA256: raise ValueError('source documents SHA mismatch')
    if sha256(values_path)!=SOURCE_VALUES_SHA256: raise ValueError('source values SHA mismatch')
    doc_fields, source_docs=read_gz(documents_path); value_fields, source_values=read_gz(values_path)
    if len(source_docs)!=SOURCE_DOCUMENT_ROWS or len(source_values)!=SOURCE_NUMERIC_ROWS: raise ValueError('source population mismatch')
    by_aid={r['announcement_id']:r for r in source_docs}
    if any(aid not in by_aid for aid in TARGET_IDS): raise ValueError('target missing from source documents')

    session=requests.Session(); candidate_docs=[]; extra_values=[]; target_reports=[]
    for row in source_docs:
        aid=row['announcement_id']
        if aid not in TARGETS_BY_AID:
            candidate_docs.append(dict(row)); continue
        target=TARGETS_BY_AID[aid]
        if row['economic_date']!=target['economic_date']: raise ValueError(f'{aid} economic date mismatch')
        evidence=json.loads(row['candidate_evidence_json'])
        exact=[e for e in evidence if e.get('sha256')==target['source_sha256'] and int(e.get('bytes') or 0)==int(target['source_bytes'])]
        if len(exact)!=1: raise ValueError(f'{aid} exact canonical evidence count={len(exact)}')
        if exact[0].get('url')!=target['source_url']: raise ValueError(f'{aid} source URL drift')
        raw=download(session,target['source_url']); digest=hashlib.sha256(raw).hexdigest()
        if digest!=target['source_sha256'] or len(raw)!=int(target['source_bytes']): raise ValueError(f'{aid} downloaded source identity mismatch')
        try:
            parsed=candidate.parse_pdf_bytes(raw,target['economic_date'])
        except Exception as exc:
            debug=equity_debug(raw,target)
            raise ValueError(f"{aid} candidate parse failed: {exc}; equity_debug={json.dumps(debug,ensure_ascii=False,separators=(',',':'))}") from exc
        if parsed.get('parser_version')!=candidate.METHOD or parsed.get('validation_errors'): raise ValueError(f'{aid} candidate parse not accepted')
        obs=parsed.get('observations') or {}
        found={c for c in candidate.ALLOWED_CONCEPTS if isinstance(obs.get(c),dict) and obs[c].get('status')=='FOUND'}
        if found!=set(candidate.ALLOWED_CONCEPTS): raise ValueError(f'{aid} exact A/L/E scope failed {found}')
        for concept in candidate.ALLOWED_CONCEPTS:
            expected=target['values'][concept][0]
            if str(obs[concept].get('normalized_cny_value'))!=expected: raise ValueError(f'{aid} {concept} value mismatch')
            extra_values.append(candidate_value_row(row,target,concept,obs[concept]))
        block=parsed.get('balance_sheet_block') or {}; identity=block.get('dual_column_identity') or {}
        if block.get('candidate_only') is not True or block.get('exact_source_sha256')!=target['source_sha256']: raise ValueError(f'{aid} candidate scope marker failed')
        if block.get('equity_value_inferred_as_assets_minus_liabilities') is not False or block.get('ocr_enabled') is not False or block.get('fuzzy_alias_matching_enabled') is not False: raise ValueError(f'{aid} prohibited method enabled')
        cols=identity.get('columns') or []
        if len(cols)!=2 or any(str(c.get('identity_residual_cny')) not in {'0','0.0','0.00','0.000'} for c in cols): raise ValueError(f'{aid} identity residual changed')
        new=dict(row); new['selected_source_url']=target['source_url']; new['selected_source_sha256']=target['source_sha256']; new['selected_source_bytes']=str(target['source_bytes'])
        new['tie_resolution']='SINGLE_CANONICAL'; new['tier1_found']='0'; new['tier2_found']='3'; new['numeric_observations']='3'; new['document_status']='PASS'; new['document_error']=''
        ev=dict(exact[0]); ev.update({'tier1_found':0,'tier2_found':3,'parser_version':candidate.METHOD,'validation_errors':[],'candidate_only':True}); new['candidate_evidence_json']=json.dumps([ev],ensure_ascii=False,separators=(',',':'))
        candidate_docs.append(new)
        target_reports.append({"announcement_id":aid,"source_sha256":target['source_sha256'],"source_bytes":target['source_bytes'],"economic_date":target['economic_date'],"selected_pages":block['selected_pages'],"split_equity_pattern":block['split_equity_pattern'],"identity":identity})

    candidate_values=source_values+sorted(extra_values,key=lambda r:(r['announcement_id'],r['concept']))
    if len(candidate_docs)!=SOURCE_DOCUMENT_ROWS or len(extra_values)!=TARGET_NUMERIC_ROWS or len(candidate_values)!=CANDIDATE_NUMERIC_ROWS: raise ValueError('candidate population mismatch')
    source_non=[r for r in source_docs if r['announcement_id'] not in TARGET_IDS]; cand_non=[r for r in candidate_docs if r['announcement_id'] not in TARGET_IDS]
    non_target_equal=row_counter(source_non,doc_fields)==row_counter(cand_non,doc_fields)
    existing_numeric_equal=row_counter(source_values,value_fields)==row_counter(candidate_values[:-TARGET_NUMERIC_ROWS],value_fields)
    source_errors=sum(r['document_status']=='ERROR' for r in source_docs); candidate_errors=sum(r['document_status']=='ERROR' for r in candidate_docs)
    source_ties=tie_taxonomy(source_docs); candidate_ties=tie_taxonomy(candidate_docs)
    source_unresolved=sum(source_ties.values()); candidate_unresolved=sum(candidate_ties.values())
    changed=sorted(r['announcement_id'] for r in candidate_docs if r['announcement_id'] in TARGET_IDS)
    distribution=Counter(r['announcement_id'] for r in extra_values)
    if source_errors!=SOURCE_ERRORS or candidate_errors!=CANDIDATE_ERRORS: raise ValueError(f'error count mismatch {source_errors}->{candidate_errors}')
    if source_unresolved!=SOURCE_UNRESOLVED_TIES or candidate_unresolved!=CANDIDATE_UNRESOLVED_TIES: raise ValueError(f'tie count mismatch {source_unresolved}->{candidate_unresolved}')
    if source_ties!={"TIE_SOURCE_INCOMPLETE":1274,"TIE_VALUE_CONFLICT":14} or candidate_ties!={"TIE_SOURCE_INCOMPLETE":1267,"TIE_VALUE_CONFLICT":14}: raise ValueError(f'tie taxonomy mismatch {source_ties}->{candidate_ties}')
    if not non_target_equal or not existing_numeric_equal or changed!=list(TARGET_IDS) or any(distribution[a]!=3 for a in TARGET_IDS): raise ValueError('non-regression or target distribution failed')

    docs_out=out/'stage3_financial_documents_v17_29_candidate.csv.gz'; values_out=out/'stage3_financial_values_v17_29_candidate.csv.gz'
    write_gz(docs_out,doc_fields,candidate_docs); write_gz(values_out,value_fields,candidate_values)
    report={
        "gate":"S3G1J_V17_29_SEVEN_EXACT_SOURCE_CANDIDATE_SAFETY_V1","candidate_only":True,"formal_runtime_generation":"V17.28","candidate_generation":"V17.29",
        "target_announcement_ids":list(TARGET_IDS),"target_count":TARGET_COUNT,"target_numeric_rows":TARGET_NUMERIC_ROWS,
        "source_document_rows":len(source_docs),"candidate_document_rows":len(candidate_docs),"source_numeric_rows":len(source_values),"candidate_numeric_rows":len(candidate_values),
        "source_document_errors":source_errors,"candidate_document_errors":candidate_errors,"document_error_reduction":source_errors-candidate_errors,
        "source_unresolved_tie_taxonomy":source_ties,"candidate_unresolved_tie_taxonomy":candidate_ties,"source_unresolved_ties":source_unresolved,"candidate_unresolved_ties":candidate_unresolved,"unresolved_tie_reduction":source_unresolved-candidate_unresolved,
        "non_target_document_rows":len(source_non),"non_target_document_exact_equal":non_target_equal,"existing_numeric_rows":len(source_values),"existing_numeric_exact_equal":existing_numeric_equal,
        "source_existing_numeric_semantic_sha256":semantic_sha(source_values,value_fields),"candidate_existing_numeric_semantic_sha256":semantic_sha(candidate_values[:-TARGET_NUMERIC_ROWS],value_fields),
        "changed_document_ids":changed,"target_numeric_distribution":dict(sorted(distribution.items())),"target_reports":sorted(target_reports,key=lambda r:r['announcement_id']),
        "non_balance_values_promoted":False,"e_equals_a_minus_l_inference":False,"ocr_enabled":False,"fuzzy_alias_matching_enabled":False,"source_policy_relaxed":False,"point_in_time_policy_relaxed":False,"issuer_gate_relaxed":False,"accounting_tolerance":"0.005",
        "formal_runtime_changed":False,"production_data_changed":False,"candidate_promotion_authorized":False,"final_data_verdict":"FAIL_CLOSED","stage3_status":"NOT_READY","stage4_alpha_live_locked":True,"main_changed":False,"pass":True,"errors":[],
    }
    report_path=out/'stage3_s3g1j_v17_29_candidate_safety.json'; report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    identities={p.name:sha256(p) for p in (docs_out,values_out,report_path)}; (out/'output_sha256.json').write_text(json.dumps(identities,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['target_count','source_numeric_rows','candidate_numeric_rows','source_document_errors','candidate_document_errors','source_unresolved_ties','candidate_unresolved_ties','non_target_document_exact_equal','existing_numeric_exact_equal','pass']},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
