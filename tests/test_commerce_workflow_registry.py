"""Workflow authority and model transport boundaries; no paid endpoints."""
import importlib.util
from dataclasses import replace
from threading import Event
import unittest


class WorkflowRegistryTests(unittest.TestCase):
    def test_lost_shipment_routes_reads_to_the_correct_owner(self):
        from decisionops.commerce.workflow_registry import workflow
        lost = workflow('lost_shipment')
        self.assertEqual(lost.allowed_tools('shipment'), ('fulfilment', 'carrier_loss'))
        self.assertEqual(lost.allowed_tools('order'), ('payment', 'compensation_history'))
        self.assertEqual(lost.prerequisites, ('order_manifest', 'replacement_policy'))
        self.assertEqual(lost.allowed_tools('coordinator'), ('order_manifest', 'replacement_policy', 'inventory'))
        with self.assertRaises(ValueError): lost.allowed_tools('approver')

    @unittest.skipUnless(importlib.util.find_spec('sqlalchemy'), 'Requires commerce SQL adapters')
    def test_sql_adapters_match_registered_dependencies(self):
        from decisionops.commerce.workflow_registry import LOST_SHIPMENT
        from decisionops.commerce.adaptive_tools import DEPENDENCIES
        self.assertEqual(dict(LOST_SHIPMENT.dependencies), DEPENDENCIES)

    def test_paper_returns_uses_same_scope_contract_but_cannot_execute(self):
        from decisionops.commerce.workflow_registry import workflow
        returns = workflow('returns', executable=False)
        self.assertEqual(returns.scope_fields, ('case_id', 'order_id', 'shipment_id', 'items', 'generation', 'case_revision'))
        self.assertIn('return_policy', returns.allowed_tools('coordinator'))
        self.assertIn('needs_review', returns.outcomes)
        with self.assertRaisesRegex(ValueError, 'paper'): workflow('returns')
        with self.assertRaises(ValueError): workflow('unknown')

    def test_registration_rejects_unowned_tools_and_dependency_cycles(self):
        from decisionops.commerce.workflow_registry import workflow
        lost = workflow('lost_shipment')
        with self.assertRaises(ValueError): replace(lost, coordinator_tools=('inventory',))
        dependencies = dict(lost.dependencies, order_manifest=('payment',))
        with self.assertRaises(ValueError): replace(lost, dependencies=tuple(dependencies.items()))
        with self.assertRaises(ValueError): replace(lost, branches=(('order', ('approve',)),))


class ModelAdapterTests(unittest.TestCase):
    def request(self):
        from decisionops.commerce.specialist_contracts import SpecialistRequest, Action
        return SpecialistRequest('R', 'C', 'order', 1, 'TOKEN', 2, 3, 'check payment',
                                 {'observations': []}, (Action('read', 'payment'),), (),
                                 {'decisions': 4, 'remaining_ms': 5000})

    def adapter(self, reply=None, transform=None):
        from decisionops.commerce.specialist_contracts import ModelDirectedSpecialist
        def transport(payload, *, timeout_ms, cancel):
            self.assertLessEqual(timeout_ms, 5000)
            self.assertNotIn('TOKEN', str(payload))
            result = {**payload['binding'], 'action': {'kind': 'read', 'tool': 'payment'}}
            return transform(result) if transform else (reply if reply is not None else result)
        return ModelDirectedSpecialist(transport, enabled=True)

    def test_fixture_transport_selects_one_listed_action(self):
        self.assertEqual(self.adapter().choose(self.request()).record(), {'kind': 'read', 'tool': 'payment'})
        from decisionops.commerce.specialist_contracts import ModelDirectedSpecialist
        with self.assertRaisesRegex(ValueError, 'explicit'): ModelDirectedSpecialist(lambda x: x)

    def test_invalid_scope_authority_stale_and_oversized_replies_are_rejected(self):
        transforms = [lambda r: dict(r, call_id='OTHER'), lambda r: dict(r, generation=1),
                      lambda r: dict(r, action={'kind': 'execute'}),
                      lambda r: dict(r, action={'kind': 'read', 'tool': 'fulfilment'}),
                      lambda r: dict(r, extra='bad'), lambda r: dict(r, action={'kind': 'read', 'tool': 'payment', 'scope': 'OTHER'})]
        for transform in transforms:
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                self.adapter(transform=transform).choose(self.request())
        for reply in ('x' * 8193, '{bad', [], {'value': float('nan')}):
            with self.subTest(reply=type(reply)), self.assertRaises(ValueError):
                self.adapter(reply).choose(self.request())

    def test_cancel_and_exhaustion_prevent_transport(self):
        from decisionops.commerce.specialist_contracts import ModelDirectedSpecialist
        def forbidden(*args, **kwargs): raise AssertionError('Transport must not run')
        adapter = ModelDirectedSpecialist(forbidden, enabled=True)
        cancel = Event(); cancel.set()
        with self.assertRaises(RuntimeError): adapter.choose(self.request(), cancel)
        with self.assertRaises(RuntimeError):
            adapter.choose(replace(self.request(), budgets={'decisions': 0, 'remaining_ms': 5000}))

    def test_transport_return_after_deadline_is_rejected(self):
        from unittest.mock import patch
        with patch('time.monotonic', side_effect=[0, 6]):
            with self.assertRaises(TimeoutError): self.adapter().choose(self.request())
