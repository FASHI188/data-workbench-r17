from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import stage3_financial_pdf_parser_v21_candidate as candidate


class V1729ExactSourceCandidateTests(unittest.TestCase):
    def test_exact_target_population_and_unique_identity(self) -> None:
        self.assertEqual(len(candidate.TARGETS), 7)
        ids=[row['announcement_id'] for row in candidate.TARGETS.values()]
        self.assertEqual(len(set(ids)),7)
        self.assertEqual(sorted(ids),['1215186538','1219426855','1219792633','1219840508','1219879687','1220087244','1221006100'])
        for digest,row in candidate.TARGETS.items():
            self.assertEqual(len(digest),64)
            self.assertGreater(row['source_bytes'],0)
            self.assertGreater(row['page_count'],0)
            self.assertTrue(row['source_url'].startswith('https://static.cninfo.com.cn/finalpage/'))

    def test_all_frozen_dual_identities_close_exactly(self) -> None:
        for row in candidate.TARGETS.values():
            result=candidate._validate_identity(row)
            self.assertEqual(result['tolerance'],'0.005')
            self.assertEqual([x['column'] for x in result['columns']],['CURRENT','PRIOR'])
            self.assertTrue(all(Decimal(x['identity_residual_cny'])==0 for x in result['columns']))

    def test_non_target_returns_formal_v1728_object_unchanged(self) -> None:
        sentinel={'parser_version':'FORMAL','observations':{'X':{'status':'FOUND'}}}
        with patch.object(candidate.accepted,'parse_pdf_bytes',return_value=sentinel):
            actual=candidate.parse_pdf_bytes(b'not-a-target','2023-12-31')
        self.assertIs(actual,sentinel)

    def test_wrong_date_returns_formal_v1728_object_unchanged(self) -> None:
        digest,target=next(iter(candidate.TARGETS.items()))
        sentinel={'parser_version':'FORMAL'}
        fake_raw=b'x'*target['source_bytes']
        class FakeHash:
            def hexdigest(self): return digest
        with patch.object(candidate.accepted,'parse_pdf_bytes',return_value=sentinel), patch.object(candidate.hashlib,'sha256',return_value=FakeHash()):
            actual=candidate.parse_pdf_bytes(fake_raw,'1900-01-01')
        self.assertIs(actual,sentinel)

    def test_split_label_then_continuation_then_amounts_is_recognized(self) -> None:
        target=next(row for row in candidate.TARGETS.values() if row['announcement_id']=='1219792633')
        rows=[
            {'text':'所有者权益（或股东权益）合','y':100.0,'words':[]},
            {'text':'计','y':112.0,'words':[]},
            {'text':'1,761,444,051.70 1,823,524,274.09','y':124.0,'words':[]},
        ]
        pair=[{'value':target['values']['TOTAL_EQUITY'][0],'raw':'1,761,444,051.70','x0':320.0},{'value':target['values']['TOTAL_EQUITY'][1],'raw':'1,823,524,274.09','x0':430.0}]
        event={'page':1,'role':'GROUP','line':'合并资产负债表','y':20.0}
        with patch.object(candidate,'_amount_pair',side_effect=lambda row,expected: pair if row is rows[2] else None), patch.object(candidate,'_bind',return_value=event), patch.object(candidate,'_validate_header',return_value={'ok':True}):
            result=candidate._find_split_equity({1:rows},[event],target)
        self.assertEqual(result['pattern'],'SPLIT_LABEL_2_ROWS_THEN_AMOUNTS')
        self.assertEqual(result['row_gaps'],['12.0','12.0'])

    def test_partial_tail_label_variant_is_recognized(self) -> None:
        target=next(row for row in candidate.TARGETS.values() if row['announcement_id']=='1215186538')
        rows=[
            {'text':'所有者权益（或股东权','y':100.0,'words':[]},
            {'text':'益）合计','y':112.0,'words':[]},
            {'text':'1,080,008,925.97 1,088,521,670.81','y':124.0,'words':[]},
        ]
        pair=[{'value':target['values']['TOTAL_EQUITY'][0],'raw':'1,080,008,925.97','x0':320.0},{'value':target['values']['TOTAL_EQUITY'][1],'raw':'1,088,521,670.81','x0':430.0}]
        event={'page':1,'role':'GROUP','line':'合并资产负债表','y':20.0}
        with patch.object(candidate,'_amount_pair',side_effect=lambda row,expected: pair if row is rows[2] else None), patch.object(candidate,'_bind',return_value=event), patch.object(candidate,'_validate_header',return_value={'ok':True}):
            result=candidate._find_split_equity({1:rows},[event],target)
        self.assertEqual(result['pattern'],'SPLIT_LABEL_2_ROWS_THEN_AMOUNTS')

    def test_amounts_without_complete_equity_label_fail_closed(self) -> None:
        target=next(iter(candidate.TARGETS.values()))
        rows=[{'text':'少数股东权益','y':100.0,'words':[]},{'text':'1,080,008,925.97 1,088,521,670.81','y':112.0,'words':[]}]
        pair=[{'value':target['values']['TOTAL_EQUITY'][0],'raw':'x','x0':320.0},{'value':target['values']['TOTAL_EQUITY'][1],'raw':'y','x0':430.0}]
        with patch.object(candidate,'_amount_pair',side_effect=lambda row,expected: pair if row is rows[1] else None):
            with self.assertRaisesRegex(ValueError,'count expected=1 actual=0'):
                candidate._find_split_equity({1:rows},[],target)

    def test_hard_boundaries_remain_narrow(self) -> None:
        self.assertEqual(candidate.ALLOWED_CONCEPTS,('TOTAL_ASSETS','TOTAL_LIABILITIES','TOTAL_EQUITY'))
        self.assertEqual(candidate.IDENTITY_TOLERANCE,Decimal('0.005'))
        self.assertEqual(candidate.MAX_COLUMN_X0_DRIFT,Decimal('18'))
        self.assertEqual(candidate.MAX_LABEL_FRAGMENT_ROWS,3)


if __name__=='__main__': unittest.main()
