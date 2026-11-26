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
        guidance=self.say(client,identity,'What can you help me?').json()
        self.assertEqual(guidance['intent'],'help')
        self.assertEqual(guidance['selected_case_id'],case['id'])
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

    def test_bounded_routing_transport_times_out_and_rejects_late_result(self):
        from decisionops.commerce.conversations import BoundedRouter
        import time
        def late(_):time.sleep(.1);return {'kind':'investigate'}
        with self.assertRaises(TimeoutError):BoundedRouter(late,timeout_seconds=.01).choose('Fix this')

    def test_older_run_generation_is_never_current_in_detail_or_chat(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce.cases import investigate_case
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.say(client,identity,'Fix this');work_once(self.engine)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():current=investigate_case(c,case['id'])
        detail=client.get('/api/cases/'+case['id']).json()['shipment_investigation']
        self.assertTrue(detail['historical']);self.assertFalse(detail['evidence_current'])
        self.assertTrue(all(e['value'] is None for e in detail['evidence']))
        self.assertTrue(all(v is None for v in detail['facts'].values()))
        reply=self.say(client,identity,'status').json()
        self.assertTrue(reply['evidence_current']);self.assertEqual(reply['proposal_id'],current['proposal_id'])
        self.assertNotIn('investigation',reply)

    def test_expired_persisted_evidence_is_explicit_in_followup(self):
        from datetime import datetime,timedelta,timezone
        from unittest.mock import patch
        from decisionops.commerce.staff_investigations import work_once
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.say(client,identity,'Fix this');work_once(self.engine)
        before=client.get('/api/cases/'+case['id']).json()
        future=datetime.now(timezone.utc)+timedelta(days=2)
        with patch('decisionops.commerce.conversations.clock',return_value=future),patch('decisionops.commerce.staff_investigations.clock',return_value=future):
            response=self.say(client,identity,"What's still missing?").json()
        self.assertFalse(response['evidence_current']);self.assertIn('expired',response['text'])
        self.assertTrue(all(e['value'] is None for e in response['investigation']['evidence']))
        after=client.get('/api/cases/'+case['id']).json()
        self.assertEqual(before['generation'],after['generation']);self.assertEqual(before['proposal'],after['proposal'])

    def test_baseline_proposal_and_approval_are_recognized_without_new_run(self):
        from decisionops.commerce.cases import investigate_case,review_case
        from decisionops.commerce import schema as db
        client=self.client();case=self.case();identity=self.conversation(client)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():saved=investigate_case(c,case['id'])
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        response=self.say(client,identity,'status').json()
        self.assertIn('proposal ready',response['text']);self.assertTrue(response['evidence_current'])
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            review_case(c,saved['id'],saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
        response=self.say(client,identity,'status').json()
        self.assertIn('Separate confirmation',response['text'])
        with self.engine.connect() as c:self.assertEqual(len(c.execute(db.adaptive_runs.select()).all()),0)

    def test_active_progress_never_labels_changed_payment_current(self):
        from decisionops.commerce import adaptive_jobs as jobs,multi_agent as multi,schema as db
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.say(client,identity,'Fix this')
        owned=jobs.claim(self.engine,staff_only=True,action=jobs.SPECIALIST_ACTION)
        fence=jobs.Fence(owned['id'],owned['token']);multi.support(self.engine,fence);multi.branch(self.engine,fence,'order')
        with self.engine.begin() as c:c.execute(db.payments.update().where(db.payments.c.order_id=='ORD-1042').values(status='failed'))
        investigation=client.get('/api/cases/'+case['id']).json()['shipment_investigation']
        self.assertEqual(investigation['state'],'active');self.assertFalse(investigation['evidence_current'])
        payment=next(e for e in investigation['evidence'] if e['tool']=='payment')
        self.assertIsNone(payment['value']);self.assertEqual(payment['applicability'],'refresh_required')
        self.assertIn('paid',investigation['unknowns']);self.assertNotIn('paid',investigation['blockers'])
        self.assertFalse(self.say(client,identity,'status').json()['evidence_current'])

    def test_distinct_order_references_require_authorized_clarification_before_routing(self):
        from decisionops.commerce import schema as db
        client=self.client();one=self.case();two=self.case('STOCK',{'shirt-red-M':1})
        identity=self.conversation(client)
        # Even an existing selection and an alternative intent router cannot
        # silently choose between two explicit orders in the staff message.
        client.post('/api/conversations/'+identity+'/select',json={'case_id':two['id']})
        result=self.say(client,identity,'Fix ORD-1042 or ORD-STOCK','AMBIGUOUS').json()
        self.assertEqual(result['intent'],'clarify');self.assertIsNone(result['selected_case_id'])
        self.assertEqual({r['case_id'] for r in result['case_links']},{one['id'],two['id']})
        self.assertEqual(self.say(client,identity,'Fix ORD-1042 or ORD-STOCK','AMBIGUOUS').json(),result)
        self.assertEqual(self.say(client,identity,'Fix this').json()['intent'],'clarify')
        with self.engine.connect() as c:
            self.assertEqual(len(c.execute(db.adaptive_runs.select()).all()),0)
        from decisionops.commerce.conversations import BoundedRouter
        from decisionops.commerce.api import create_app
        from fastapi.testclient import TestClient
        router=BoundedRouter(lambda _: {'kind':'investigate','order_id':'ORD-1042'})
        routed=TestClient(create_app(self.engine,password='fictional-test-password',conversation_router=router),headers=client.headers)
        other=self.conversation(routed)
        response=self.say(routed,other,'Fix ORD-1042 or ORD-STOCK').json()
        self.assertEqual(response['intent'],'clarify');self.assertIsNone(response['selected_case_id'])
        outside=self.client(store_id='another-store');foreign=self.conversation(outside)
        response=self.say(outside,foreign,'Fix ORD-1042 or ORD-STOCK').json()
        self.assertEqual(response['intent'],'clarify');self.assertEqual(response['case_links'],[])

    def test_repeated_reference_to_one_order_does_not_create_false_ambiguity(self):
        client=self.client();case=self.case();identity=self.conversation(client)
        response=self.say(client,identity,'Fix ORD-1042; I mean ord-1042').json()
        self.assertEqual(response['intent'],'investigate');self.assertEqual(response['selected_case_id'],case['id'])

    def test_rules_refresh_supersedes_historical_specialist_guidance(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce.worker import work_once as rules_once
        from decisionops.commerce.workflow import setup_checkpoints
        from decisionops.commerce import schema as db
        from decisionops.commerce.investigations import recheck
        from decisionops.commerce.cases import clock
        client=self.client();case=self.case();identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':case['id']})
        self.say(client,identity,'Fix this');work_once(self.engine)
        before=client.get('/api/cases/'+case['id']).json()
        with self.engine.begin() as c:c.execute(db.inventory.update().where(db.inventory.c.variant_id=='shirt-blue-M').values(on_hand=20))
        self.assertFalse(self.say(client,identity,'status').json()['evidence_current'])
        started=client.post('/api/cases/'+case['id']+'/investigate',json={})
        self.assertEqual(started.status_code,202)
        setup_checkpoints(self.engine);rules_once(self.engine)
        current=client.get('/api/cases/'+case['id']).json()
        self.assertEqual(current['status'],'awaiting_review')
        self.assertGreater(current['generation'],before['generation'])
        self.assertNotEqual(current['proposal']['id'],before['proposal']['id'])
        with self.engine.connect() as c:self.assertEqual(recheck(c,current['proposal']['id'],clock(c))['status'],'valid_for_review')
        history=current['shipment_investigation']
        self.assertTrue(history.get('historical',False));self.assertFalse(history['evidence_current'])
        self.assertTrue(all(e['value'] is None for e in history['evidence']))
        reply=self.say(client,identity,'status').json()
        self.assertTrue(reply['evidence_current']);self.assertEqual(reply['proposal_id'],current['proposal']['id'])
        approved=client.post('/api/cases/'+case['id']+'/review',json={'generation':current['generation'],
            'proposal_id':current['proposal']['id'],'content_hash':current['proposal']['content_hash'],'decision':'approve'})
        self.assertEqual(approved.status_code,200)
        self.assertTrue(self.say(client,identity,'status').json()['evidence_current'])
        self.assertEqual(client.get('/api/cases/'+case['id']).json()['approval'],approved.json()['approval'])

    def test_router_cannot_replace_or_omit_staff_explicit_order_scope(self):
        from decisionops.commerce.conversations import BoundedRouter
        from decisionops.commerce.api import create_app
        from fastapi.testclient import TestClient
        from decisionops.commerce import schema as db
        one=self.case();two=self.case('STOCK',{'shirt-red-M':1});base=self.client()
        for action in ({'kind':'investigate','order_id':'ORD-STOCK'},{'kind':'investigate'}):
            with self.subTest(action=action):
                client=TestClient(create_app(self.engine,password='fictional-test-password',staff_investigation_mode='mock-specialists',
                    conversation_router=BoundedRouter(lambda _,action=action:action)),headers=base.headers)
                identity=self.conversation(client)
                client.post('/api/conversations/'+identity+'/select',json={'case_id':two['id']})
                response=self.say(client,identity,'Fix ORD-1042').json()
                self.assertEqual(response['selected_case_id'],one['id'])
        client=TestClient(create_app(self.engine,password='fictional-test-password',staff_investigation_mode='mock-specialists',
            conversation_router=BoundedRouter(lambda _:{'kind':'status','order_id':'ORD-STOCK'})),headers=base.headers)
        identity=self.conversation(client)
        client.post('/api/conversations/'+identity+'/select',json={'case_id':one['id']})
        self.assertEqual(self.say(client,identity,'status').json()['selected_case_id'],one['id'])
        outside=TestClient(create_app(self.engine,password='fictional-test-password',store_id='another-store',
            conversation_router=BoundedRouter(lambda _:{'kind':'investigate','order_id':'ORD-STOCK'})),headers=base.headers)
        foreign=self.conversation(outside)
        response=self.say(outside,foreign,'Fix ORD-1042').json()
        self.assertEqual(response['intent'],'clarify');self.assertIsNone(response['selected_case_id'])
        self.assertEqual(response['case_links'],[])
        with self.engine.connect() as c:
            rows=c.execute(db.adaptive_runs.select()).mappings().all()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['request']['order_id'],'ORD-1042')
