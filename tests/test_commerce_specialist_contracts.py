"""Pure specialist contracts: scoped authority, bounded inputs, real cue choices."""
from dataclasses import replace
import threading
import unittest

from decisionops.commerce.specialist_contracts import (
    Action, MockSpecialist, SpecialistRequest, validate_action)


class SpecialistContractTests(unittest.TestCase):
    def request(self, specialist='order', **updates):
        tools = ('payment', 'compensation_history') if specialist == 'order' else ('carrier_loss', 'fulfilment')
        values = dict(run_id='audit-run', call_id='audit-call', specialist=specialist, ordinal=1,
                      created_token='audit-token', generation=1, case_revision=0,
                      report='', projection={'requested_items': {'blue': 1}, 'observations': []},
                      allowed=tuple(Action('read', tool) for tool in tools), attempts=(),
                      budgets={'decisions': 4, 'remaining_ms': 5000, 'tools': 4})
        values.update(updates)
        return SpecialistRequest(**values)

    def test_roundtrip_is_exact_and_detached(self):
        request = self.request(attempts=({'tool': 'payment', 'status': 'missing', 'observation_id': 'audit-obs'},))
        raw = request.record()
        rebuilt = SpecialistRequest.from_record(raw)
        self.assertEqual(rebuilt, request)
        self.assertEqual(rebuilt.record(), raw)
        raw['projection']['requested_items']['blue'] = 2
        self.assertEqual(request.projection['requested_items']['blue'], 1)
        features = request.features()
        features['remaining_budgets']['decisions'] = 0
        self.assertEqual(request.budgets['decisions'], 4)

    def test_feature_projection_filters_audit_raw_rows_and_other_scopes(self):
        projection = {'case_id': 'audit-case', 'request_hash': 'audit-hash',
                      'requested_items': {'blue': 1}, 'assessment': 'internal',
                      'observations': [dict(tool=tool, value=True, status='success',
                                            id='audit-obs', payload={'secret': 'raw-row'}, dependencies=['audit-dep'])
                                       for tool in ('payment', 'carrier_loss', 'order_manifest', 'replacement_policy')]}
        request = self.request(projection=projection,
                               attempts=({'tool': 'payment', 'status': 'success', 'observation_id': 'audit-obs'},))
        features = request.features()
        self.assertEqual(set(features), {'specialist', 'report', 'observations', 'allowed_actions',
                                         'attempted_tools', 'remaining_budgets'})
        observations = features['observations']['observations']
        self.assertEqual([row['tool'] for row in observations], ['payment', 'order_manifest', 'replacement_policy'])
        self.assertTrue(all(set(row) == {'tool', 'value', 'status'} for row in observations))
        self.assertEqual(features['attempted_tools'], [{'tool': 'payment', 'status': 'success'}])
        self.assertNotIn('audit-', str(features))
        self.assertNotIn('raw-row', str(features))

    def test_actions_reject_cross_scope_or_write_authority(self):
        request = self.request()
        for action in ({'kind': 'execute'}, {'kind': 'propose'}, {'kind': 'report_blocker'},
                       {'kind': 'read', 'tool': 'carrier_loss'},
                       {'kind': 'read', 'tool': []},
                       {'kind': 'read', 'tool': 'payment', 'override': True},
                       [{'kind': 'read', 'tool': 'payment'}]):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(request, action)
        self.assertEqual(validate_action(request, {'kind': 'read', 'tool': 'payment'}), Action('read', 'payment'))
        with self.assertRaises(ValueError):
            validate_action(replace(request, allowed=(Action('read', 'compensation_history'),)), Action('read', 'payment'))
        with self.assertRaises(ValueError):
            self.request(allowed=(Action('propose'),))
        with self.assertRaises(ValueError):
            self.request('shipment', allowed=(Action('read', 'payment'),))

    def test_malformed_and_oversized_requests_fail(self):
        invalid = ({'specialist': 'finance'}, {'specialist': []}, {'ordinal': True}, {'ordinal': 5},
                   {'generation': 0}, {'case_revision': -1}, {'run_id': ''},
                   {'report': 'é' * 1001}, {'projection': {'raw': 'x' * 8193}},
                   {'projection': {'observations': ['bad']}}, {'projection': {'value': float('nan')}},
                   {'allowed': ()}, {'attempts': ({'tool': 'carrier_loss'},)},
                   {'attempts': tuple({'tool': 'payment'} for _ in range(5))},
                   {'budgets': {'decisions': 5, 'remaining_ms': 5000}},
                   {'budgets': {'decisions': True, 'remaining_ms': 5000}},
                   {'budgets': {'decisions': 4, 'remaining_ms': 5001}},
                   {'budgets': {'decisions': 4, 'remaining_ms': 5000, 'execute': 1}})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.request(**fields)
        raw = self.request().record()
        for change in ({'contract': 'wrong'}, {'override': True}, {'allowed': {'kind': 'read'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                SpecialistRequest.from_record(dict(raw, **change))

    def test_mock_report_cues_change_actual_allowed_decisions(self):
        chooser = MockSpecialist()
        self.assertEqual(chooser.choose(self.request()).tool, 'compensation_history')
        self.assertEqual(chooser.choose(self.request(report='Check payment')).tool, 'payment')
        self.assertEqual(chooser.choose(self.request('shipment')).tool, 'carrier_loss')
        self.assertEqual(chooser.choose(self.request('shipment', report='Refresh tracking')).tool, 'fulfilment')
        self.assertEqual(chooser.choose(self.request(attempts=({'tool': 'compensation_history'},))).tool, 'payment')
        review = Action('request_review', reason='unknown_evidence')
        self.assertEqual(chooser.choose(self.request(allowed=(review,))), review)

    def test_cancel_and_budget_caps(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(RuntimeError):
            MockSpecialist().choose(self.request(), cancelled)
        for budgets in ({'decisions': 0, 'remaining_ms': 5000}, {'decisions': 4, 'remaining_ms': 0}):
            with self.subTest(budgets=budgets), self.assertRaises(RuntimeError):
                MockSpecialist().choose(self.request(budgets=budgets))


class SpecialistResultTests(unittest.TestCase):
    def result(self, **updates):
        from decisionops.commerce.specialist_contracts import SpecialistResult
        values = dict(specialist='shipment', run_id='run', generation=1, case_revision=0,
                      status='complete', observation_ids=('OBS-1',),
                      observed_at='2026-11-13T10:00:00+00:00', deadline='2026-11-13T10:00:05Z')
        values.update(updates)
        return SpecialistResult(**values)

    def test_all_statuses_and_exact_json_roundtrip(self):
        import json
        from decisionops.commerce.specialist_contracts import RESULT_STATUSES, SpecialistResult
        for status in RESULT_STATUSES:
            with self.subTest(status=status):
                result = self.result(status=status)
                raw = json.loads(json.dumps(result.record()))
                self.assertEqual(SpecialistResult.from_record(raw), result)
                self.assertIsInstance(raw['observation_ids'], list)
        self.assertEqual(self.result(status='stale', observed_at='2026-11-13T10:01:00Z').status, 'stale')

    def test_malformed_result_bindings_and_timestamps_fail_closed(self):
        invalid = ({'specialist': 'finance'}, {'specialist': []}, {'run_id': ''}, {'generation': True},
                   {'generation': 0}, {'case_revision': -1}, {'status': 'approved'},
                   {'status': []}, {'observation_ids': ['OBS-1']}, {'observation_ids': ('OBS-1', 'OBS-1')},
                   {'observation_ids': tuple('OBS-' + str(n) for n in range(5))},
                   {'observation_ids': ('',)}, {'observation_ids': (True,)},
                   {'observed_at': '2026-11-13'}, {'observed_at': '2026-11-13T10:00:00'},
                   {'deadline': '2026-02-30T00:00:00Z'}, {'deadline': 123},
                   {'reason': ''}, {'reason': 'é' * 257}, {'reason': {'override': True}})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.result(**fields)
        from decisionops.commerce.specialist_contracts import SpecialistResult
        raw = self.result().record()
        for change in ({'status': 'propose'}, {'override': True}, {'observation_ids': ('OBS-1',)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                SpecialistResult.from_record(dict(raw, **change))


if __name__ == '__main__':
    unittest.main()
