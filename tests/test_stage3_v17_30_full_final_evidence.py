import json
import unittest
from pathlib import Path


class V1730FullFinalEvidenceContract(unittest.TestCase):
    def test_registered_evidence_is_exact_and_fail_closed(self):
        p = Path('governance/stage3_s3g1j_v17_30_full_final.json')
        data = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(data['gate'], 'S3G1J_V17_30_FULL_64_SHARD_ACCEPTANCE')
        self.assertEqual(data['status'], 'MACHINE_ACCEPTED_EXECUTION_WITH_FAIL_CLOSED_DATA_VERDICT')
        self.assertEqual(data['accepted_run']['run_id'], 31518370789)
        self.assertEqual(data['accepted_run']['head_sha'], 'a18b81a9f38692533d0427f4a5b50767abf1a7c8')
        self.assertEqual(data['accepted_run']['artifact_id'], 9112098872)
        self.assertEqual(data['accepted_run']['artifact_digest'], 'sha256:706c6dd7252a64fd5c2956df6c594b5c91de29f02ca7d0553fa932017e8867ba')
        self.assertEqual(data['source_execution']['execution_pr'], 126)
        self.assertFalse(data['source_execution']['execution_pr_merged'])
        self.assertTrue(data['source_execution']['execution_pr_closed_without_merge'])
        self.assertEqual(data['source_execution']['run_id'], 31480775354)
        self.assertEqual(data['source_execution']['shard_count'], 64)
        self.assertEqual(data['accepted_pr']['number'], 127)
        self.assertEqual(data['accepted_pr']['merge_commit'], '121972a404c8773963477907c8b9abd3a4f5160b')
        result = data['full_basis_result']
        self.assertTrue(result['execution_pass'])
        self.assertTrue(result['source_shard_verify_pass'])
        self.assertTrue(result['document_non_regression_pass'])
        self.assertTrue(result['numeric_non_regression_pass'])
        self.assertTrue(result['promotion_gold_equality_pass'])
        self.assertTrue(result['real_source_recheck_pass'])
        self.assertEqual(result['document_count'], 121354)
        self.assertEqual(result['numeric_observation_count'], 1051826)
        self.assertEqual(result['document_error_count'], 1362)
        self.assertEqual(result['unresolved_tie_count'], 1279)
        self.assertEqual(result['changed_announcement_ids'], ['1223347318', '1223407043'])
        self.assertEqual(result['non_target_document_count'], 121352)
        self.assertEqual(result['target_numeric_rows'], 6)
        self.assertEqual(result['unexpected_document_regression_count'], 0)
        self.assertFalse(result['final_data_gate_pass'])
        self.assertEqual(result['final_data_verdict'], 'FAIL_CLOSED')
        self.assertEqual(data['numeric_non_regression']['previous_existing_semantic_sha256'], data['numeric_non_regression']['current_existing_semantic_sha256'])
        self.assertEqual(data['numeric_non_regression']['fresh_target_numeric_semantic_sha256'], data['numeric_non_regression']['promotion_gold_target_numeric_semantic_sha256'])
        self.assertEqual(data['hard_boundaries']['stage3_status'], 'NOT_READY')
        self.assertTrue(data['hard_boundaries']['stage4_alpha_live_locked'])
        self.assertFalse(data['hard_boundaries']['main_changed'])
        self.assertFalse(data['hard_boundaries']['merge_to_main_authorized'])


if __name__ == '__main__':
    unittest.main()
