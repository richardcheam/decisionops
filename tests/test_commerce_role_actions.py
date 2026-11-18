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

    def test_reporting_instructions_and_negated_history_never_file(self):
        from decisionops.commerce.role_actions import clear_report_intent,DemoCustomerRouter
        negatives=('How to report my parcel missing?','I did not report my parcel missing.',
            'The help page says "My parcel never arrived. Please report it missing." What does that mean?',
            'Please report my parcel missing is an example in the help page.',
            'My parcel never arrived. This is an example from a guide.',
            'How can I report my parcel missing?','Can you check whether my parcel never arrived?',
            'I never said my parcel never arrived.','Please do not report my parcel missing.',
            'Please report my parcel missing only if the carrier confirms it.',
            'Should I report my parcel missing?')
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(clear_report_intent(text))
                self.assertNotEqual(DemoCustomerRouter().choose(text).kind,'report_nonreceipt')
        for text in ('My parcel never arrived. Please report it missing.',
                     'Please report DEMO-LYON missing.','Can you report my parcel missing?',
                     'I have not received my parcel.','My parcel has not arrived.'):
            with self.subTest(text=text):self.assertTrue(clear_report_intent(text))
