"""Pure Stage 2 action/policy contracts, never inference."""
import importlib.util
import unittest

class AdaptivePolicyTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('decisionops.commerce.adaptive_policies'),
                             'Stage 2 action contract is not implemented')
        from decisionops.commerce import adaptive_policies
        return adaptive_policies

    def request(self, report='', actions=None):
        p=self.api()
        return p.PolicyRequest('run',1,report,{'requested_items':{'blue':1},'observations':[]},
                               tuple(actions or (p.Action('read','payment'),p.Action('read','inventory'))),
                               (),{'tools':12,'decisions':16},())

    def test_strict_action_contract(self):
        p=self.api(); self.assertEqual(p.Action.from_record({'kind':'read','tool':'payment'}),p.Action('read','payment'))
        for raw in ({'kind':'execute'},{'kind':'read','tool':'all'}, {'kind':'propose','override':True}):
            with self.subTest(raw=raw),self.assertRaises(ValueError): p.Action.from_record(raw)

    def test_fixed_and_cue_only_select_allowed(self):
        p=self.api(); req=self.request('Please check stock')
        self.assertEqual(p.FixedOrder().choose(req),p.Action('read','payment'))
        self.assertEqual(p.CueRules().choose(req),p.Action('read','inventory'))
        forced=self.request(actions=(p.Action('request_review',reason='unknown_evidence'),))
        self.assertEqual(p.FixedOrder().choose(forced),forced.allowed[0])

    def test_features_exclude_audit_binding(self):
        p=self.api(); req=self.request()
        self.assertNotIn('run',req.features()); self.assertNotIn('context_version',req.features())
        self.assertEqual(req.features()['allowed_actions'],[a.record() for a in req.allowed])

    def test_fake_override_and_unavailable_are_explicit(self):
        p=self.api(); req=self.request()
        self.assertEqual(p.FakePolicy('override').choose(req)['kind'],'execute')
        with self.assertRaises(RuntimeError): p.FakePolicy('unavailable').choose(req)
        self.assertEqual(p.FakePolicy('refuse').choose(req),p.Action('request_review',reason='policy_refused'))

if __name__=='__main__': unittest.main()
