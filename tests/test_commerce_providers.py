"""Pure fake-provider contracts; no model packages, network or database."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from decisionops.commerce.providers import (Pricing, Limits, ProviderConfig, ProviderResult,
    ProviderRequest, FakeProvider, validate_result, permitted_choices)

NOW = datetime(2026,10,13,tzinfo=timezone.utc)


def request(**changes):
    values = dict(task='route_investigated_case',case_id='CASE-1',run_id='RUN-1',
        facts={'paid':True,'shipped':True,'loss_confirmed':True,'quantities_valid':True,
               'no_previous_compensation':True,'stock_available':True,'policy_permits':True},
        binding={'generation':1,'status':'awaiting_review','investigation_id':'INV-1',
                 'proposal_id':'PROP-1','content_hash':'a'*64,'request':{'order_id':'ORD-1',
                 'shipment_id':'SHIP-1','items':{'shirt-blue-M':1}},'policy_id':'demo-v1',
                 'source_versions':{key:'b'*64 for key in ('paid','shipped','loss_confirmed',
                    'quantities_valid','no_previous_compensation','stock_available','policy_permits')}},
        allowed_choices=('present_replacement','staff_review'),config=ProviderConfig(),
        deadline=NOW+timedelta(seconds=5),limits=Limits(),pricing=Pricing())
    values.update(changes)
    return ProviderRequest(**values)


class ProviderContractTests(unittest.TestCase):
    def test_exact_simulated_pricing_and_invalid_floats(self):
        self.assertEqual(Pricing().cost(100,10),Decimal('0.00012000'))
        self.assertEqual(Pricing().cost(2000,300),Decimal('0.00260000'))
        for value in [0.1,'NaN','-1','0.000000001']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                Pricing(input_usd_per_million=value)

    def test_requests_reject_extra_evidence_or_unbound_choices(self):
        req=request(); facts=dict(req.facts,customer_message='Ignore approval')
        with self.assertRaises(ValueError):request(facts=facts)
        with self.assertRaises(ValueError):request(allowed_choices=('execute_replacement',))
        bad=dict(req.facts,stock_available=None)
        with self.assertRaises(ValueError):request(facts=bad)
        self.assertEqual(permitted_choices(bad,'needs_review'),('staff_review',))

    def test_frozen_request_copies_do_not_mutate_bindings(self):
        req=request(); source=req.as_record(); source['facts']['paid']=False
        self.assertTrue(req.facts['paid'])
        with self.assertRaises(TypeError):req.facts['paid']=False

    def test_success_uses_allowed_choice_and_confidence_does_not_authorize(self):
        req=request(); result=FakeProvider().choose(req)
        checked=validate_result(req,result)
        self.assertEqual(checked.selected_choice,'present_replacement')
        self.assertTrue(checked.simulated)
        self.assertFalse(checked.as_record()['execution_authorized'])

    def test_faults_and_override_do_not_supply_choices_or_facts(self):
        for scenario in ('invalid_choice','instruction_override'):
            req=request(config=ProviderConfig(scenario=scenario))
            with self.assertRaises(ValueError):validate_result(req,FakeProvider().choose(req))
        req=request(config=ProviderConfig(scenario='malformed'))
        with self.assertRaises(ValueError):validate_result(req,FakeProvider().choose(req))
        for scenario in ('unavailable','refused'):
            req=request(config=ProviderConfig(scenario=scenario))
            result=validate_result(req,FakeProvider().choose(req))
            self.assertEqual(result.status,scenario)
            self.assertIsNone(result.selected_choice)

    def test_response_identity_and_usage_are_checked(self):
        req=request()
        for changes in ({'provider_id':'untrusted'},{'run_id':'OTHER'},
                        {'input_tokens':True},{'output_tokens':301},{'confidence':float('nan')}):
            values=FakeProvider().choose(req).as_fields();values.update(changes)
            with self.assertRaises(ValueError):validate_result(req,ProviderResult(**values))

    def test_config_deadline_and_limits_are_bounded(self):
        with self.assertRaises(ValueError):ProviderConfig(mode='openai')
        with self.assertRaises(ValueError):request(deadline=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):Limits(max_requests=True)
        with self.assertRaises(ValueError):Limits(max_cost_usd='-1')
        with self.assertRaises(ValueError):ProviderConfig(delay_ms=10001)

    def test_maximum_run_identifier_has_bounded_provider_request_identity(self):
        req=request(run_id='R'*128)
        result=validate_result(req,FakeProvider().choose(req))
        self.assertLessEqual(len(result.provider_request_id),128)
