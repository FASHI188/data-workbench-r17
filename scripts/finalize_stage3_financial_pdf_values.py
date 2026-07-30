#!/usr/bin/env python3
from __future__ import annotations

import argparse,csv,gzip,hashlib,io,json
from collections import Counter,defaultdict
from datetime import date
from pathlib import Path

NUMERIC_FIELDS=[
    "exchange","source_code","effective_code","issuer_org_id","report_family","economic_date","announcement_id","revision_sequence",
    "source_published_at","effective_session","available_at","concept","raw_value","normalized_cny_value","unit","unit_multiplier",
    "source_url","source_sha256","source_format","extraction_method","methodology_version","page","matched_alias","confidence"
]
DOC_FIELDS=[
    "exchange","source_code","effective_code","issuer_org_id","report_family","economic_date","announcement_id","revision_sequence",
    "source_published_at","effective_session","available_at","canonical_title","canonical_source_url","selected_source_url","selected_source_sha256",
    "selected_source_bytes","tie_candidate_count","tie_resolution","candidate_evidence_json","tier1_found","tier2_found","numeric_observations","document_status","document_error"
]


def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def readgz(path:Path):
    with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):yield r


def write_deterministic_csv_gz(path:Path,fields,rows)->None:
    # Canonical Stage3 fingerprints must not depend on output filename or wall-clock time.
    with path.open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=9,mtime=0) as gz:
            with io.TextIOWrapper(gz,encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--versions',required=True);ap.add_argument('--stage2-manifest',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True);errors=[]
    manifests=sorted(root.rglob('financial_extract_shard*.manifest.json'));nums=sorted(root.rglob('financial_values_shard*.csv.gz'));docs=sorted(root.rglob('financial_documents_shard*.csv.gz'))
    if len(manifests)!=64:errors.append(f'expected 64 manifests got {len(manifests)}')
    if len(nums)!=64:errors.append(f'expected 64 numeric files got {len(nums)}')
    if len(docs)!=64:errors.append(f'expected 64 document files got {len(docs)}')
    expected_versions={}
    with gzip.open(a.versions,'rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):expected_versions[r['canonical_announcement_id']]=r
    stage2=json.loads(Path(a.stage2_manifest).read_text(encoding='utf-8'))
    if stage2.get('version')!='V3.2.25-stage2-final-freeze' or stage2.get('stage2_dataset_fingerprint')!='f17f7ab63f4532dda635eb7366e7df7bf5497a5ce814410105312bccb53125bb':errors.append('wrong Stage2 dependency')
    manifest_map={}
    for p in manifests:
        m=json.loads(p.read_text(encoding='utf-8'));manifest_map[int(m['shard'])]=m
        if m.get('error_count')!=0 or m.get('errors'):errors.append(f"shard {m.get('shard')} errors={m.get('error_count')} {m.get('errors',[])[:5]}")
    for p in nums:
        sh=int(p.stem.split('shard')[-1].split('.')[0]);m=manifest_map.get(sh)
        if m and sha(p)!=m.get('numeric_sha256'):errors.append(f'numeric SHA mismatch shard {sh}')
    for p in docs:
        sh=int(p.stem.split('shard')[-1].split('.')[0]);m=manifest_map.get(sh)
        if m and sha(p)!=m.get('documents_sha256'):errors.append(f'doc SHA mismatch shard {sh}')
    all_docs=[];all_nums=[]
    for p in docs:all_docs.extend(readgz(p))
    for p in nums:all_nums.extend(readgz(p))
    doc_by={};dup_docs=[]
    for r in all_docs:
        aid=r['announcement_id']
        if aid in doc_by:dup_docs.append(aid)
        doc_by[aid]=r
    if dup_docs:errors.append(f'duplicate document IDs {dup_docs[:20]} count={len(dup_docs)}')
    missing_docs=sorted(set(expected_versions)-set(doc_by));extra_docs=sorted(set(doc_by)-set(expected_versions))
    if missing_docs:errors.append(f'missing version documents {missing_docs[:20]} count={len(missing_docs)}')
    if extra_docs:errors.append(f'extra version documents {extra_docs[:20]} count={len(extra_docs)}')
    bad_docs=[r['announcement_id'] for r in all_docs if r['document_status']!='PASS' or not r['selected_source_sha256']]
    if bad_docs:errors.append(f'documents not clean PASS {bad_docs[:20]} count={len(bad_docs)}')
    unresolved_ties=[r['announcement_id'] for r in all_docs if r['tie_resolution'] in ('TIE_SOURCE_INCOMPLETE','TIE_VALUE_CONFLICT','NO_CANDIDATE')]
    if unresolved_ties:errors.append(f'unresolved tied versions {unresolved_ties[:20]} count={len(unresolved_ties)}')
    obs_keys=set();dup_obs=[];coverage=Counter();by_year=defaultdict(Counter);by_family=defaultdict(Counter)
    for r in all_nums:
        k=(r['announcement_id'],r['concept'])
        if k in obs_keys:dup_obs.append(k)
        obs_keys.add(k)
        d=doc_by.get(r['announcement_id'])
        if not d:errors.append(f"numeric row missing document {r['announcement_id']}");continue
        if r['source_sha256']!=d['selected_source_sha256']:errors.append(f"numeric/document SHA mismatch {r['announcement_id']} {r['concept']}")
        if r['source_format']!='PDF' or not r['source_sha256'] or not r['normalized_cny_value']:errors.append(f"invalid numeric provenance {r['announcement_id']} {r['concept']}")
        if r['effective_session']!=d['effective_session'] or r['available_at']!=d['available_at']:errors.append(f"availability mismatch {r['announcement_id']} {r['concept']}")
        if r['effective_session'] and r['source_published_at'] and date.fromisoformat(r['effective_session'])<=date.fromisoformat(r['source_published_at']):errors.append(f"same-day/backdated availability {r['announcement_id']}")
        coverage[r['concept']]+=1;by_year[r['economic_date'][:4]][r['concept']]+=1;by_family[r['report_family']][r['concept']]+=1
    if dup_obs:errors.append(f'duplicate observation keys {dup_obs[:20]} count={len(dup_obs)}')
    numeric_out=out/'stage3_financial_raw_values.csv.gz';doc_out=out/'stage3_financial_documents.csv.gz'
    all_nums.sort(key=lambda r:(r['source_published_at'],r['exchange'],r['source_code'],r['announcement_id'],r['concept']))
    all_docs.sort(key=lambda r:(r['source_published_at'],r['exchange'],r['source_code'],r['announcement_id']))
    write_deterministic_csv_gz(numeric_out,NUMERIC_FIELDS,all_nums)
    write_deterministic_csv_gz(doc_out,DOC_FIELDS,all_docs)
    report={
        'gate':'S3G1J_ORIGINAL_PDF_FINANCIAL_VALUES_FINAL','pass':not errors,'stage2_version':stage2.get('version'),'stage2_fingerprint':stage2.get('stage2_dataset_fingerprint'),
        'canonical_version_count':len(expected_versions),'document_count':len(all_docs),'numeric_observation_count':len(all_nums),'concept_coverage':dict(coverage),
        'coverage_by_year':{k:dict(v) for k,v in sorted(by_year.items())},'coverage_by_family':{k:dict(v) for k,v in sorted(by_family.items())},
        'unresolved_tie_count':len(unresolved_ties),'document_error_count':len(bad_docs),'financial_values_sha256':sha(numeric_out),'financial_documents_sha256':sha(doc_out),
        'gzip_header_mtime':0,'gzip_embedded_filename':'','authority':'CNINFO_ORIGINAL_FILING_PDF_BYTES_WITH_SHA256','historical_current_f10_used_as_truth':False,'errors':errors
    }
    (out/'stage3_financial_raw_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('gate','pass','canonical_version_count','document_count','numeric_observation_count','concept_coverage','unresolved_tie_count','document_error_count','errors')},ensure_ascii=False,indent=2))
    return 0 if not errors else 2
if __name__=='__main__':raise SystemExit(main())
