import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from decisionops.commerce.live_specialist_evaluation import OpenAISpecialistTransport


class LiveSpecialistTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.create = self.client.responses.create
        self.create.return_value = SimpleNamespace(
            status='completed', output_text='{"choice": 1}',
            usage=SimpleNamespace(input_tokens=125, output_tokens=10),
        )
        self.transport = OpenAISpecialistTransport(self.client, 'test-model', max_calls=1)
        self.request = {'role': 'specialist', 'features': {
            'report': 'private text', 'requested_items': {'private-item': 1},
            'specialist': 'shipment', 'observations': {'observations': [
                {'tool': 'fulfilment', 'status': 'success', 'value': True,
                 'payload': 'private observation'},
            ]}, 'attempted_tools': [], 'remaining_budgets': {'decisions': 2},
            'allowed_actions': [{'kind': 'request_review', 'reason': 'manual_review'},
                                {'kind': 'read', 'tool': 'carrier_loss'}],
        }}

    def test_completed_choice_uses_only_allowed_fields_and_counts_usage(self):
        self.assertEqual(self.transport(self.request), self.request['features']['allowed_actions'][1])
        sent = self.create.call_args.kwargs
        self.assertFalse(sent['store'])
        self.assertNotIn('private', sent['input'])
        self.assertEqual(json.loads(sent['input'])['observations'],
                         [{'tool': 'fulfilment', 'status': 'success', 'value': True}])
        self.assertEqual(self.transport.summary()['input_tokens'], 125)

    def test_request_cap_and_out_of_scope_role(self):
        with self.assertRaises(ValueError):
            self.transport({'role': 'customer', 'message': 'private'})
        self.transport(self.request)
        with self.assertRaises(ValueError):
            self.transport(self.request)
        self.create.assert_called_once()
        self.assertEqual(self.transport.summary()['budget_denials'], 1)

    def test_invalid_or_failed_response_is_counted(self):
        self.create.return_value.output_text = '{"choice": true}'
        with self.assertRaises(ValueError):
            self.transport(self.request)
        self.assertEqual(self.transport.summary()['unsuccessful_calls'], 1)
        self.assertEqual(self.transport.summary()['output_tokens'], 10)

    def test_report_distinguishes_applied_provider_reads_and_fallbacks(self):
        self.transport.choice_sources.update({'one': 'provider', 'two': 'provider', 'three': 'fallback'})
        row = {'mode': 'injected_specialists', 'specialist_decisions': [
            {'id': 'one', 'disposition': 'applied', 'error': None},
            {'id': 'two', 'disposition': 'discarded', 'error': 'late_or_stale_result'},
            {'id': 'three', 'disposition': 'applied', 'error': None},
            {'id': 'four', 'disposition': 'discarded', 'error': 'decision_deadline'},
        ]}
        self.transport.annotate({'runs': [row]})
        self.assertNotIn('specialist_decisions', row)
        self.assertEqual(row['specialist_choice_counts'], {
            'provider_reads_applied': 1, 'provider_review_choices': 0,
            'provider_other_dispositions': 1, 'fallback_choices': 1,
            'unattributed_dispatched_choices': 1,
        })
