"""Actor-owned conversation scope and follow-ups against isolated PostgreSQL."""
import os
import unittest
import uuid
import test_commerce_adaptive_core as core

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class ConversationTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    case=core.AdaptiveCoreTests.case

    def client(self, username='operator', store_id='demo-store'):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        client=TestClient(create_app(self.engine,password='fictional-test-password',store_id=store_id,
            staff_investigation_mode='mock-specialists',staff_accounts={'helper':{'password':'fictional-staff-password','role':'staff'}}),
            headers={'Authorization':'Basic '+__import__('base64').b64encode((username+':'+('fictional-staff-password' if username=='helper' else 'fictional-test-password')).encode()).decode()})
        return client

    def conversation(self, client):
        r=client.post('/api/conversations',json={});self.assertEqual(r.status_code,201);return r.json()['id']

    def say(self, client, identity, message, request_id=None):
        return client.post('/api/conversations/'+identity+'/messages',json={'message':message,'request_id':request_id or uuid.uuid4().hex})

    def test_sessions_and_actors_have_independent_selected_case(self):
        client=self.client();case=self.case();a=self.conversation(client);b=self.conversation(client)
        self.assertEqual(client.post('/api/conversations/'+a+'/select',json={'case_id':case['id']}).status_code,200)
        self.assertEqual(self.say(client,a,"What's still missing?").json()['selected_case_id'],case['id'])
        self.assertEqual(self.say(client,b,'Fix this').json()['intent'],'clarify')
        other=self.client('helper')
        self.assertEqual(self.say(other,a,'Fix this').status_code,404)

    def test_status_preserves_proposal_and_approval_without_new_run(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        result=self.say(client,identity,'Fix this','FIX-ONCE');self.assertEqual(result.status_code,200)
        work_once(self.engine)
        before=client.get('/api/cases/'+case['id']).json();proposal=before['proposal'];self.assertIsNotNone(proposal)
        approved=client.post('/api/cases/'+case['id']+'/review',json={'generation':before['generation'],
            'proposal_id':proposal['id'],'content_hash':proposal['content_hash'],'decision':'approve'}).json()
        for question in ("What's still missing?",'status','Fix this'):
            self.assertEqual(self.say(client,identity,question).status_code,200)
        after=client.get('/api/cases/'+case['id']).json()
        self.assertEqual(after['approval'],approved['approval']);self.assertEqual(after['proposal'],proposal)
        self.assertEqual(self.say(client,identity,'Fix this','FIX-ONCE').json(),result.json())
        self.assertEqual(self.say(client,identity,'status','FIX-ONCE').status_code,409)
        with self.engine.connect() as c:self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.adaptive_runs)).scalar_one(),1)

    def test_explicit_order_ambiguity_and_scope_authorization(self):
        client=self.client();one=self.case();two=self.case();identity=self.conversation(client)
        response=self.say(client,identity,'Fix ORD-1042').json()
        self.assertEqual(response['intent'],'clarify');self.assertEqual(len(response['case_links']),2)
        self.assertIsNone(response['selected_case_id'])
        outside=self.client(store_id='another-store');other=self.conversation(outside)
        self.assertEqual(outside.post('/api/conversations/'+other+'/select',json={'case_id':one['id']}).status_code,404)

    def test_staff_can_investigate_but_not_approve_or_execute(self):
        client=self.client('helper');case=self.case();identity=self.conversation(client)
        self.assertEqual(client.get('/api/session').json()['role'],'staff')
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.assertEqual(self.say(client,identity,'Fix this').status_code,200)
        self.assertEqual(client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':'fake'}).status_code,403)
        self.assertEqual(client.post('/api/cases/'+case['id']+'/review',json={'generation':1,'proposal_id':'fake','content_hash':'0'*64,'decision':'approve'}).status_code,403)

    def test_typed_router_rejects_scope_or_execution_arguments(self):
        from decisionops.commerce.conversations import DemoRouter,BoundedRouter
        self.assertEqual(DemoRouter().choose('How many deliveries did we complete this week?').kind,'weekly_deliveries')
        with self.assertRaises(ValueError):BoundedRouter(lambda _: {'kind':'execute','case_id':'forged'}).choose('Fix this')

    def test_status_and_detail_identify_source_drift_without_destroying_approval(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce import schema as db
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.say(client,identity,'Fix this');work_once(self.engine)
        before=client.get('/api/cases/'+case['id']).json();proposal=before['proposal']
        with self.engine.begin() as c:c.execute(db.inventory.update().values(on_hand=20))
        response=self.say(client,identity,"What's still missing?").json()
        self.assertFalse(response['evidence_current']);self.assertIn('changed',response['text'])
        after=client.get('/api/cases/'+case['id']).json()
        self.assertEqual(after['proposal'],proposal)
        evidence=after['shipment_investigation']['evidence']
        self.assertTrue(any(e['tool']=='inventory' and e['value'] is None and e['applicability']=='refresh_required' for e in evidence))
