"""Stage 3 recommendation contracts must import without optional dependencies."""
import unittest

class RecommendationTests(unittest.TestCase):
    def test_task_and_choice_are_validated(self):
        from decisionops.commerce.adaptive_recommendations import Request,Result,validate
        from decisionops.commerce.adaptive_policies import Action,PolicyRequest
        p=PolicyRequest('R',1,'report',{},(Action('read','order_manifest'),),(),{'tools':12,'decisions':15,'seconds':20},())
        r=Request('C','R',1,2,p,'fixed',20000)
        self.assertEqual(r.task,'choose_investigation_action/v1')
        self.assertEqual(validate(r,Result('C',{'kind':'read','tool':'order_manifest'},1)).action,{'kind':'read','tool':'order_manifest'})
        with self.assertRaises(ValueError):validate(r,Result('C',{'kind':'execute'},1))
        with self.assertRaises(ValueError):validate(r,Result('OTHER',{'kind':'read','tool':'order_manifest'},1))
        self.assertNotIn('run_id',r.policy.features())

    def test_fake_cancellation_is_cooperative(self):
        from threading import Event
        from decisionops.commerce.adaptive_recommendations import FakeAdapter,Cancelled
        e=Event();e.set()
        with self.assertRaises(Cancelled):FakeAdapter(delay=.1).choose(None,e)

if __name__=='__main__':unittest.main()
