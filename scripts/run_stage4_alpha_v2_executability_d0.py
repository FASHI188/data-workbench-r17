#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

PREREG_FP="5407c8293c678287596abe2bc6cced8c83d6a2f997eb6ff8720b7790d59c8e6a"
LABELS_SHA="092061da5666215dcc1f4fa75ec0b1cdbcc43969560755e7cdae6de55e64d673"
EXPECTED_ROWS=5197648
EXPECTED_VALID20=5103016
ALLOWED=[
 "trade_date","exchange","code","entry_date","exit_date_20d","valid_label_20d","censor_reason_20d",
 "known_code_transition_security","finite_lifecycle_interval"
]
FORBIDDEN=[
 "stock_total_return_5d","benchmark_return_5d","excess_return_5d",
 "stock_total_return_20d","benchmark_return_20d","excess_return_20d"
]
BOUNDARY="PARTITION_BOUNDARY_INCOMPLETE_HORIZON"

def q(s:str)->str: return "'" + s.replace("'","''") + "'"
def sha256_file(p:Path)->str:
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def write_json(p:Path,x:object)->None:
 p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--labels",required=True)
 ap.add_argument("--prereg",required=True)
 ap.add_argument("--out",required=True)
 ap.add_argument("--synthetic",action="store_true")
 args=ap.parse_args()
 import duckdb
 labels=Path(args.labels); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
 prereg=json.loads(Path(args.prereg).read_text(encoding="utf-8"))
 if prereg["fingerprint"]!=PREREG_FP: raise ValueError("D0 preregistration fingerprint mismatch")
 if not args.synthetic and sha256_file(labels)!=LABELS_SHA: raise ValueError("development labels sha256 mismatch")
 con=duckdb.connect()
 cols=[r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(str(labels))})").fetchall()]
 missing=[c for c in ALLOWED if c not in cols]
 if missing: raise ValueError(f"missing required D0 columns: {missing}")
 con.execute(f"""
   CREATE TEMP TABLE d0 AS
   SELECT CAST(trade_date AS DATE) trade_date,
          upper(CAST(exchange AS VARCHAR)) exchange,
          lpad(CAST(code AS VARCHAR),6,'0') code,
          CAST(entry_date AS DATE) entry_date,
          CAST(exit_date_20d AS DATE) exit_date_20d,
          CAST(valid_label_20d AS BOOLEAN) valid_label_20d,
          CAST(censor_reason_20d AS VARCHAR) censor_reason_20d,
          CAST(known_code_transition_security AS BOOLEAN) known_code_transition_security,
          CAST(finite_lifecycle_interval AS BOOLEAN) finite_lifecycle_interval
   FROM read_parquet({q(str(labels))})
 """)
 rows,valid20,dmin,dmax=con.execute("SELECT count(*),count(*) FILTER(WHERE valid_label_20d),min(trade_date),max(trade_date) FROM d0").fetchone()
 if not args.synthetic:
  if rows!=EXPECTED_ROWS or valid20!=EXPECTED_VALID20: raise ValueError(f"population mismatch rows={rows} valid20={valid20}")
  if str(dmin)!="2015-01-05" or str(dmax)!="2022-12-30": raise ValueError(f"date boundary mismatch {dmin}..{dmax}")
  if con.execute("SELECT count(*) FROM d0 WHERE trade_date>=DATE '2023-01-03'").fetchone()[0]!=0: raise ValueError("OOS-or-later row in D0 input")
 invalid=rows-valid20
 invalid_cohorts=con.execute("SELECT count(DISTINCT trade_date) FROM d0 WHERE NOT valid_label_20d").fetchone()[0]
 boundary_invalid=con.execute(f"SELECT count(*) FROM d0 WHERE NOT valid_label_20d AND censor_reason_20d={q(BOUNDARY)}").fetchone()[0]
 overall={
   "rows":rows,"valid_20d_rows":valid20,"invalid_20d_rows":invalid,
   "invalid_20d_rate":(invalid/rows if rows else 0.0),"invalid_cohort_count":invalid_cohorts,
   "boundary_invalid_rows":boundary_invalid,"nonboundary_invalid_rows":invalid-boundary_invalid,
   "date_min":str(dmin),"date_max":str(dmax)
 }
 write_json(out/"d0_overall.json",overall)
 con.execute(f"""
   COPY (
     SELECT trade_date,count(*) rows,
            count(*) FILTER(WHERE valid_label_20d) valid_20d_rows,
            count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows,
            count(*) FILTER(WHERE NOT valid_label_20d)::DOUBLE/count(*) invalid_20d_rate,
            count(*) FILTER(WHERE NOT valid_label_20d AND censor_reason_20d={q(BOUNDARY)}) boundary_invalid_rows,
            count(*) FILTER(WHERE NOT valid_label_20d AND censor_reason_20d<>{q(BOUNDARY)}) nonboundary_invalid_rows
     FROM d0 GROUP BY trade_date ORDER BY trade_date
   ) TO {q(str(out/"d0_by_date.parquet"))} (FORMAT PARQUET,COMPRESSION ZSTD)
 """)
 def rows_json(sql:str):
  cur=con.execute(sql); names=[x[0] for x in cur.description]
  return [dict(zip(names,r)) for r in cur.fetchall()]
 by_time={
   "year":rows_json("SELECT year(trade_date) year,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY 1 ORDER BY 1"),
   "quarter":rows_json("SELECT year(trade_date) year,quarter(trade_date) quarter,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY 1,2 ORDER BY 1,2"),
   "month":rows_json("SELECT strftime(trade_date,'%Y-%m') month,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY 1 ORDER BY 1")
 }
 write_json(out/"d0_by_time.json",by_time)
 write_json(out/"d0_by_exchange.json",rows_json("SELECT exchange,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY exchange ORDER BY exchange"))
 write_json(out/"d0_by_censor_reason.json",rows_json("SELECT censor_reason_20d,count(*) rows FROM d0 GROUP BY censor_reason_20d ORDER BY censor_reason_20d"))
 write_json(out/"d0_by_flags.json",{
   "known_code_transition_security":rows_json("SELECT known_code_transition_security,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY 1 ORDER BY 1"),
   "finite_lifecycle_interval":rows_json("SELECT finite_lifecycle_interval,count(*) rows,count(*) FILTER(WHERE NOT valid_label_20d) invalid_20d_rows FROM d0 GROUP BY 1 ORDER BY 1")
 })
 manifest={
   "schema_version":1,"gate":"STAGE4_ALPHA_V2_EXECUTABILITY_D0",
   "preregistration_fingerprint":PREREG_FP,"synthetic":bool(args.synthetic),
   "input_labels_sha256":sha256_file(labels),"rows":rows,"valid_20d_rows":valid20,
   "allowed_columns_read":ALLOWED,"forbidden_columns_read":[],"model_fit_executed":False,
   "prediction_executed":False,"return_metric_computed":False,"policy_selected":False,
   "oos_accessed":False,"final_lockbox_accessed":False,
   "next_gate":"SEPARATE_D0_RESULT_ACCEPTANCE_NO_POLICY_SELECTION"
 }
 write_json(out/"d0_manifest.json",manifest)
 json_files=["d0_manifest.json","d0_overall.json","d0_by_time.json","d0_by_exchange.json","d0_by_censor_reason.json","d0_by_flags.json"]
 for n in json_files:
  txt=(out/n).read_text(encoding="utf-8")
  if any(f in txt for f in FORBIDDEN): raise ValueError(f"forbidden field leaked to output {n}")
 desc=[r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({q(str(out/'d0_by_date.parquet'))})").fetchall()]
 if any(f in desc for f in FORBIDDEN): raise ValueError("forbidden field leaked to parquet output")
 hashes={p.name:sha256_file(p) for p in out.iterdir() if p.is_file() and p.name!="artifact_hashes.json"}
 write_json(out/"artifact_hashes.json",dict(sorted(hashes.items())))
 print(json.dumps(manifest,ensure_ascii=False,indent=2))
 return 0
if __name__=="__main__": raise SystemExit(main())
