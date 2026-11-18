"""Frozen SQL comparison audits production evidence and chooser behavior."""
import json
import importlib.util
import os
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec('sqlalchemy'), 'Requires commerce SQL profile')
class ComparisonTests(unittest.TestCase):
    def test_all_modes_share_sources_budgets_and_independent_expected_outcomes(self):
        from decisionops.commerce.comparison import compare
        report = compare()
        self.assertEqual(report['modes'], ['rules', 'single_chooser', 'specialists'])
        self.assertEqual(report['live_model_quality'], 'unmeasured')
        self.assertEqual(report['live_model_cost_usd'], 'unmeasured')
        self.assertTrue(report['results'])
        grouped = {}
        for row in report['results']:
            grouped.setdefault(row['case'], []).append(row)
            self.assertTrue(row['correct'], row)
            self.assertLessEqual(row['policy_reads'], 12)
            self.assertLessEqual(row['decisions'], 16)
            self.assertTrue(row['evidence_valid'])
            self.assertIn('safety_reads', row)
            self.assertIn('retries', row)
            self.assertIn('fallbacks', row)
            self.assertIn('latency_ms', row)
        for rows in grouped.values():
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({r['source_sha256'] for r in rows}), 1)
            self.assertEqual(len({json.dumps(r['budgets'], sort_keys=True) for r in rows}), 1)
        eligible = [r for r in grouped['eligible'] if r['mode'] == 'specialists'][0]
        self.assertEqual(eligible['outcome'], 'proposed')
        self.assertEqual(eligible['policy_reads'], 7)
        self.assertEqual(eligible['safety_reads'], 7)
        self.assertEqual(eligible['repeated_reads'], 0)
        self.assertTrue(eligible['evidence_complete'])
        self.assertEqual(grouped['incomplete_history'][0]['expected'], 'review')
        self.assertEqual(grouped['already_replaced'][0]['expected'], 'blocked')

    def test_invalid_early_review_and_timeout_are_scored_as_failures(self):
        from decisionops.commerce.comparison import compare
        report = compare(adversarial=True)
        attacks = {r['attack']: r for r in report['results'] if r['case'] == 'eligible' and r['mode'] == 'single_chooser' and r.get('attack')}
        self.assertEqual(set(attacks), {'invalid_action', 'early_review', 'timeout'})
        self.assertFalse(attacks['early_review']['correct'])
        self.assertEqual(attacks['early_review']['outcome'], 'review')
        self.assertGreater(attacks['invalid_action']['fallbacks'], 0)
        self.assertGreater(attacks['timeout']['timeouts'], 0)
        self.assertEqual(attacks['invalid_action']['invalid_actions'], 1)
        self.assertTrue(attacks['invalid_action']['correct'])
        self.assertTrue(attacks['timeout']['correct'])
        self.assertGreaterEqual(report['summary']['single_chooser']['incorrect'], 1)

    def test_runner_emits_machine_readable_report(self):
        result = subprocess.run([sys.executable, '-m', 'decisionops.commerce.comparison'], capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['contract'], 'commerce-frozen-comparison/v1')
        self.assertIn('timing_boundary', report)


@unittest.skipUnless(os.environ.get('COMMERCE_COMPARISON_POSTGRES'), 'Opt-in full real product comparison')
class ProductComparisonTests(unittest.TestCase):
    def test_actual_services_and_graph_share_sources_without_masking_disagreements(self):
        from decisionops.commerce.comparison import compare_postgres
        report = compare_postgres(os.environ['COMMERCE_TEST_DATABASE_URL'])
        self.assertEqual(report['contract'], 'commerce-postgres-comparison/v1')
        self.assertGreaterEqual(len(report['results']), 30)
        hashes = {}
        for row in report['results']:
            hashes.setdefault(row['case'], set()).add(row['source_sha256'])
            self.assertEqual(row['policy_reads'], row['measured_policy_reads'])
            self.assertEqual(row['correct'], row['outcome'] == row['expected'])
            self.assertTrue(row['evidence_valid'])
            self.assertLessEqual(row['policy_reads'], 12)
            if row['case'] == 'eligible':
                self.assertEqual(row['outcome'], 'proposed')
                self.assertEqual(row['policy_reads'], 7)
                self.assertEqual(row['safety_reads'], 7)
                self.assertEqual(row['safety_bundled_assessments'], 1)
        self.assertTrue(all(len(values)==1 for values in hashes.values()))
