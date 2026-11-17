"""Role contracts reject authority and model-selected case scope."""
import unittest
import time

class RoleActionTests(unittest.TestCase):
    def test_typed_actions_reject_approval_identity_and_wrong_role(self):
        from decisionops.commerce.role_actions import CustomerAction,ModelActionAdapter
        for raw in ({'kind':'approve'},{'kind':'report_nonreceipt','customer_id':'alex'}, {'kind':'investigate'}):
            with self.assertRaises(ValueError):CustomerAction.from_record(raw)
        adapter=ModelActionAdapter(lambda request:{'kind':'execute'})
        self.assertEqual(adapter.customer().choose('delivery status').kind,'delivery_status')
        self.assertEqual(adapter.staff().choose('Fix this').kind,'investigate')

    def test_model_timeout_falls_back_and_cannot_choose_order(self):
        from decisionops.commerce.role_actions import ModelActionAdapter
        def stalled(_):time.sleep(.1);return {'kind':'report_nonreceipt'}
        adapter=ModelActionAdapter(stalled,timeout_seconds=.01)
        start=time.monotonic();action=adapter.customer().choose('delivery status')
        self.assertLess(time.monotonic()-start,.08);self.assertEqual(action.kind,'delivery_status')
        adapter=ModelActionAdapter(lambda _: {'kind':'investigate','order_id':'DEMO-OTHER'})
        self.assertIsNone(adapter.staff().choose('Fix this').order_id)

    def test_one_adapter_validates_read_tool_against_current_allowlist(self):
        from decisionops.commerce.role_actions import ModelActionAdapter
        from decisionops.commerce.adaptive_policies import Action,PolicyRequest
        request=PolicyRequest('server-run',1,'fictional report',{},(Action('read',tool='payment'),),(),{},())
        adapter=ModelActionAdapter(lambda _: {'kind':'read','tool':'payment'})
        self.assertEqual(adapter.choose(request),Action('read',tool='payment'))
        adapter=ModelActionAdapter(lambda _: {'kind':'read','tool':'inventory'})
        self.assertEqual(adapter.choose(request),Action('read',tool='payment'))

    def test_shared_adapter_accepts_specialist_request_without_authority(self):
        from decisionops.commerce.role_actions import ModelActionAdapter
        from decisionops.commerce.specialist_contracts import SpecialistRequest
        from decisionops.commerce.adaptive_policies import Action
        from datetime import datetime,timezone
        request=SpecialistRequest('server-run','call','order',1,'server-token',1,1,'fictional report',{},
            (Action('read',tool='payment'),),(),{'decisions':1,'remaining_ms':100})
        adapter=ModelActionAdapter(lambda _: {'kind':'read','tool':'payment'})
        self.assertEqual(adapter.choose(request,None),Action('read',tool='payment'))
