import csv,gzip,importlib.util,json,subprocess,sys,tempfile,unittest
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
merge=load('merge','scripts/merge_g5_cninfo_primary.py');adj=load('adj','scripts/build_g5_adjustment_from_g3.py')

class G5SemanticTests(unittest.TestCase):
 def test_sse_differential_rows_are_not_summed(self):
  rows=[]
  for v,i in [('0.122','a'),('0.184','b')]:rows.append({'exchange':'SSE','code':'600989','ex_date':'2022-12-27','action_component':'DIVIDEND','cash_per_share':v,'bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','record_date':'','source_system':'SSE_NATIVE','source_id':i,'source_url':'u','source_sha256':i,'source_payload':i})
  controls=merge.aggregate_sse_control(rows);k=('SSE','600989','2022-12-27');self.assertTrue(controls[k]['cash']['differential'])
  pm={k:{'exchange':'SSE','code':'600989','ex_date':'2022-12-27','record_date':'','announcement_date':'','action_type':'CASH_DIVIDEND','cash_per_share':'0.14','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','rights_listing_date':'','source_count':1,'source_evidence':'[]'}}
  r=merge.reconcile_sse_nonrights(pm,controls);self.assertEqual(pm[k]['cash_per_share'],'0.14');self.assertEqual(len(r['differential']),1);self.assertEqual(len(r['unresolved_differential']),0);self.assertEqual(len(r['overrides']),0)
 def test_cninfo_declared_shareholder_rate_difference_preserves_marketwide_value(self):
  raw={'exchange':'SSE','code':'600989','ex_date':'2022-05-12','action_component':'DIVIDEND_BONUS_TRANSFER','cash_per_share':'0.28','bonus_per_share':'0','transfer_per_share':'0','source_system':'CNINFO','source_payload':json.dumps({'F007V':'限售股股东10派2.648元，流通股股东10派3.21元'},ensure_ascii=False)}
  declared,_=merge.detect_cninfo_differential_components([raw]);sse=[{'exchange':'SSE','code':'600989','ex_date':'2022-05-12','action_component':'DIVIDEND','cash_per_share':'0.321','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','record_date':'','source_system':'SSE_NATIVE','source_id':'a','source_url':'u','source_sha256':'a','source_payload':'a'}]
  k=('SSE','600989','2022-05-12');pm={k:{'exchange':'SSE','code':'600989','ex_date':'2022-05-12','record_date':'','announcement_date':'','action_type':'CASH_DIVIDEND','cash_per_share':'0.28','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','rights_listing_date':'','source_count':1,'source_evidence':'[]'}}
  r=merge.reconcile_sse_nonrights(pm,merge.aggregate_sse_control(sse),declared);self.assertEqual(pm[k]['cash_per_share'],'0.28');self.assertEqual(len(r['overrides']),0);self.assertEqual(len(r['cninfo_declared_differential']),1)
 def test_sse_differential_without_marketwide_value_fails_resolution(self):
  rows=[]
  for v,i in [('0.122','a'),('0.184','b')]:rows.append({'exchange':'SSE','code':'600989','ex_date':'2022-12-27','action_component':'DIVIDEND','cash_per_share':v,'bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0','record_date':'','source_system':'SSE_NATIVE','source_id':i,'source_url':'u','source_sha256':i,'source_payload':i})
  r=merge.reconcile_sse_nonrights({},merge.aggregate_sse_control(rows));self.assertEqual(len(r['unresolved_differential']),1)
 def test_material_transfer_uses_market_reference(self):
  e={'exchange':'SSE','code':'600699','ex_date':'2019-07-29','action_type':'CAPITAL_TRANSFER','cash_per_share':'0','bonus_per_share':'0','transfer_per_share':'0.4','rights_per_share':'0','rights_price':'0'}
  ex,_,back,_,_,_,delta,source,meta=adj.select_price_reference(e,Decimal('21.83'),Decimal('1'),{'preclose':'15.94','evidence':'B'});self.assertEqual(ex,Decimal('15.94'));self.assertGreater(delta,Decimal('0.01'));self.assertIn('SEMANTIC_OVERRIDE',source);self.assertIsNotNone(meta);self.assertAlmostEqual(float(back),21.83/15.94,places=9)
 def test_small_cash_keeps_exact_official_formula_not_rounded_market_reference(self):
  e={'exchange':'SSE','code':'600000','ex_date':'2024-01-01','action_type':'CASH_DIVIDEND','cash_per_share':'0.003','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0'}
  ex,_,_,_,_,_,_,source,meta=adj.select_price_reference(e,Decimal('10'),Decimal('1'),{'preclose':'10.00','evidence':'B'});self.assertEqual(ex,Decimal('9.997'));self.assertEqual(source,'OFFICIAL_ACTION_FORMULA');self.assertIsNone(meta)
 def test_material_cash_discrepancy_fails_closed(self):
  e={'exchange':'SSE','code':'600989','ex_date':'2022-12-27','action_type':'CASH_DIVIDEND','cash_per_share':'0.306','bonus_per_share':'0','transfer_per_share':'0','rights_per_share':'0','rights_price':'0'}
  with self.assertRaises(ValueError):adj.select_price_reference(e,Decimal('12.09'),Decimal('1'),{'preclose':'11.954','evidence':'B'})

class FactorControlTests(unittest.TestCase):
 def _write_gz(self,p,fields,rows):
  p.parent.mkdir(parents=True,exist_ok=True)
  with gzip.open(p,'wt',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 def _run(self,factor_rows,chain_rows):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);factor=td/'factor';out=td/'out';chain=td/'chain.csv.gz';fields=['exchange','code','effective_date','fore_adjust_factor','back_adjust_factor']
   for i in range(16):
    self._write_gz(factor/f'g5_events_shard{i:02d}.csv.gz',fields,factor_rows if i==0 else []);(factor/f'g5_manifest_shard{i:02d}.json').write_text(json.dumps({'securities':1 if i==0 else 0,'query_errors':[]}),encoding='utf-8')
   self._write_gz(chain,['exchange','code','ex_date','action_type','back_adjust_multiplier'],chain_rows)
   cp=subprocess.run([sys.executable,str(ROOT/'scripts/audit_g5_baostock_factor_control.py'),'--factor-root',str(factor),'--chain',str(chain),'--out',str(out)],capture_output=True,text=True);return cp.returncode,json.loads((out/'g5_baostock_control.json').read_text())
 def test_fore_rebase_does_not_erase_valid_back_factor(self):
  factor=[{'exchange':'SSE','code':'600001','effective_date':'2020-01-01','fore_adjust_factor':'1','back_adjust_factor':'1'},{'exchange':'SSE','code':'600001','effective_date':'2020-06-02','fore_adjust_factor':'0.5','back_adjust_factor':'1.1'}];chain=[{'exchange':'SSE','code':'600001','ex_date':'2020-06-01','action_type':'CASH_DIVIDEND','back_adjust_multiplier':'1.1'}]
  rc,r=self._run(factor,chain);self.assertEqual(rc,0);self.assertTrue(r['pass']);self.assertEqual(r['factor_ratio_mismatches'],0);self.assertEqual(r['official_actions_matched'],1);self.assertGreaterEqual(r['methodology_rebases_logged'],1)
 def test_absent_quantized_secondary_change_is_warning_not_contradiction(self):
  factor=[{'exchange':'SSE','code':'600001','effective_date':'2020-01-01','fore_adjust_factor':'1','back_adjust_factor':'1'},{'exchange':'SSE','code':'600001','effective_date':'2020-06-02','fore_adjust_factor':'1','back_adjust_factor':'1'}];chain=[{'exchange':'SSE','code':'600001','ex_date':'2020-06-01','action_type':'CASH_DIVIDEND','back_adjust_multiplier':'1.001'}]
  rc,r=self._run(factor,chain);self.assertEqual(rc,0);self.assertTrue(r['pass']);self.assertEqual(r['official_actions_secondary_unobserved'],1)
 def test_comparable_back_factor_mismatch_still_fails(self):
  factor=[{'exchange':'SSE','code':'600001','effective_date':'2020-01-01','fore_adjust_factor':'1','back_adjust_factor':'1'},{'exchange':'SSE','code':'600001','effective_date':'2020-06-02','fore_adjust_factor':'1.2','back_adjust_factor':'1.2'}];chain=[{'exchange':'SSE','code':'600001','ex_date':'2020-06-01','action_type':'CAPITAL_TRANSFER','back_adjust_multiplier':'1.1'}]
  rc,r=self._run(factor,chain);self.assertNotEqual(rc,0);self.assertFalse(r['pass']);self.assertEqual(r['factor_ratio_mismatches'],1)

if __name__=='__main__':unittest.main()
