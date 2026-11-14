"""Staff API + durable investigation, real DB and mocked Decisions only."""
import os,unittest,json
import test_commerce_adaptive_core as core
from concurrent.futures import ThreadPoolExecutor

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class StaffInvestigationTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup
    case=core.AdaptiveCoreTests.case
    def client(self,mode='rules'):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        client=TestClient(create_app(self.engine,password='fictional-test-password',username='staff',staff_investigation_mode=mode))
        client.auth=('staff','fictional-test-password');return client
    def start(self,client,case,request='REQ-one'):
        return client.post('/api/cases/'+case['id']+'/shipment-investigation',json={'report':'My parcel did not arrive','request_id':request,'expected_generation':case['generation']})
    def test_duplicate_admission_refresh_and_rules_proposal(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce import schema as db
        case=self.case();client=self.client()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.start(client,case),range(2)))
        self.assertTrue(all(r.status_code==202 for r in results));self.assertEqual(results[0].json()['run_id'],results[1].json()['run_id'])
        for _ in range(2):self.assertEqual(client.get('/api/cases/'+case['id']).json()['shipment_investigation']['state'],'active')
        work_once(self.engine)
        detail=client.get('/api/cases/'+case['id']).json();self.assertEqual(detail['status'],'awaiting_review');self.assertTrue(detail['assessment']['facts']['stock_available']);self.assertIsNotNone(detail['proposal'])
        self.assertEqual(self.start(client,case).json()['run_id'],results[0].json()['run_id'])
        with self.engine.connect() as c:
            self.assertEqual(len(c.execute(db.adaptive_runs.select()).all()),1);self.assertEqual(c.execute(db.operations.select()).all(),[])
        self.assertEqual(client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':'unapproved'}).status_code,409)
    def test_mock_early_review_continues_with_separate_audit(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce import adaptive_investigations as service,schema as db
        client=self.client('mock-decisions');case=self.case();r=self.start(client,case);self.assertEqual(r.status_code,202)
        work_once(self.engine)
        saved=service.inspect(self.engine,r.json()['run_id']);self.assertEqual(saved['state'],'proposed');self.assertEqual(saved['tool_counts']['inventory'],1)
        self.assertTrue(any(s['kind']=='deterministic_continuation' for s in saved['steps']))
        with self.engine.connect() as c:
            calls=c.execute(db.adaptive_calls.select()).mappings().all()
            self.assertTrue(all(x['result']['metadata']['simulated_transport'] for x in calls))
            self.assertTrue(any(x['result']['action']['kind']=='request_review' for x in calls))
    def test_missing_history_reviews_and_no_execution(self):
        from decisionops.commerce.staff_investigations import work_once
        case=self.case('HISTORY');client=self.client();self.assertEqual(self.start(client,case).status_code,202);work_once(self.engine)
        detail=client.get('/api/cases/'+case['id']).json();self.assertEqual(detail['status'],'needs_review');self.assertIsNone(detail['proposal']);self.assertIsNone(detail['assessment']['facts']['no_previous_compensation'])
    def test_mode_cannot_enable_paid_provider_and_report_is_bounded(self):
        from decisionops.commerce.api import create_app
        with self.assertRaises(ValueError):create_app(self.engine,password='fictional-test-password',staff_investigation_mode='live')
        client=self.client();case=self.case();body={'report':'é'*1001,'request_id':'x','expected_generation':0}
        self.assertEqual(client.post('/api/cases/'+case['id']+'/shipment-investigation',json=body).status_code,422)
        response=self.start(client,case);body={'report':'changed','request_id':'REQ-one','expected_generation':0}
        self.assertEqual(client.post('/api/cases/'+case['id']+'/shipment-investigation',json=body).status_code,409)
    def test_legitimate_manual_and_refusal_reviews_are_not_continued(self):
        from decisionops.commerce import adaptive_jobs as jobs,adaptive_investigations as service
        for index,reason in enumerate(('manual_review','policy_refused')):
            client=self.client();case=self.case();run_id=self.start(client,case,'manual-'+str(index)).json()['run_id'];owner=jobs.claim(self.engine,job_id=service.inspect(self.engine,run_id)['job']['id']);fence=jobs.Fence(owner['id'],owner['token'])
            saved=service.advance(self.engine,run_id,{'kind':'request_review','reason':reason},expected_context=service.inspect(self.engine,run_id)['context_version'],fence=fence)
            self.assertEqual(saved['state'],'review');self.assertEqual(saved['tool_attempts'],0);self.assertFalse(any(s['kind']=='deterministic_continuation' for s in saved['steps']))
    def test_exhausted_decision_budget_explains_no_continuation(self):
        from decisionops.commerce import schema as db,adaptive_investigations as service
        from decisionops.commerce.staff_investigations import work_once
        client=self.client('mock-decisions');case=self.case();run_id=self.start(client,case).json()['run_id']
        from decisionops.commerce import adaptive_jobs as jobs
        from decisionops.commerce.staff_investigations import adapter_for
        from decisionops.commerce.adaptive_runner import tick
        owned=jobs.claim(self.engine,job_id=service.inspect(self.engine,run_id)['job']['id']);fence=jobs.Fence(owned['id'],owned['token'])
        for _ in range(15):
            current=service.inspect(self.engine,run_id)
            service.advance(self.engine,run_id,{'kind':'not_an_allowed_action'},expected_context=current['context_version'],fence=fence)
        tick(self.engine,fence,adapter=adapter_for(service.inspect(self.engine,run_id)));saved=service.inspect(self.engine,run_id)
        self.assertEqual(saved['state'],'review');self.assertEqual(saved['tool_attempts'],0);self.assertEqual(saved['decision_attempts'],16)
        self.assertTrue(any(s['kind']=='continuation_unavailable' and s['data']['reason']=='decision_budget' for s in saved['steps']))
    def test_duplicate_execution_queues_one_job_after_exact_approval(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce.worker import work_once as execute_once
        from decisionops.commerce import schema as db
        client=self.client();case=self.case();self.start(client,case);work_once(self.engine)
        detail=client.get('/api/cases/'+case['id']).json();proposal=detail['proposal']
        approved=client.post('/api/cases/'+case['id']+'/review',json={'generation':detail['generation'],'proposal_id':proposal['id'],'content_hash':proposal['content_hash'],'decision':'approve'})
        self.assertEqual(approved.status_code,200);operation=approved.json()['approval']['operation_id']
        first=client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation});second=client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation})
        self.assertEqual(first.status_code,202);self.assertEqual(second.status_code,202);self.assertEqual(first.json()['id'],second.json()['id'])
        from decisionops.commerce.workflow import setup_checkpoints
        setup_checkpoints(self.engine);execute_once(self.engine)
        self.assertEqual(client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation}).status_code,409)
        with self.engine.connect() as c:self.assertEqual(len(c.execute(db.operations.select()).all()),1);self.assertEqual(len(c.execute(db.reservations.select()).all()),1)
    def test_all_accepted_request_ids_replay_after_completion(self):
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce import schema as db
        c=self.case();client=self.client();a=self.start(client,c,'ID-A');b=self.start(client,c,'ID-B');self.assertEqual(a.json()['run_id'],b.json()['run_id'])
        work_once(self.engine)
        again=self.start(client,c,'ID-B');self.assertEqual(again.status_code,202);self.assertEqual(again.json()['run_id'],b.json()['run_id'])
        with self.engine.connect() as connection:self.assertEqual(len(connection.execute(db.adaptive_runs.select()).all()),1)
    def test_expired_staff_job_becomes_review_not_permanently_active(self):
        from unittest.mock import patch
        import time
        from decisionops.commerce import adaptive_investigations as service
        from decisionops.commerce.staff_investigations import work_once
        original=service.start
        def short(*args,**kw):return original(*args,deadline_seconds=.1,**kw)
        client=self.client();case=self.case()
        with patch.object(service,'start',side_effect=short):r=self.start(client,case)
        time.sleep(.15);work_once(self.engine)
        saved=service.inspect(self.engine,r.json()['run_id']);self.assertEqual(saved['state'],'review');self.assertEqual(saved['job']['status'],'failed')
        current=client.get('/api/cases/'+case['id']).json();self.assertEqual(current['shipment_investigation']['reason'],'run_deadline')
        self.assertEqual(self.start(client,current,'EXPLICIT-NEW-REQUEST').status_code,202)
    def test_discarded_true_read_is_not_displayed_as_confirmed(self):
        from unittest.mock import patch
        from decisionops.commerce import adaptive_investigations as service
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce.cases import escalate_case
        client=self.client();case=self.case();self.start(client,case);original=service.read_tool
        def changed(*args,**kw):
            value=original(*args,**kw)
            with self.engine.begin() as c:escalate_case(c,case['id'],'Staff took over before admission')
            return value
        with patch.object(service,'read_tool',side_effect=changed):work_once(self.engine)
        result=client.get('/api/cases/'+case['id']).json()['shipment_investigation'];self.assertEqual(result['state'],'stale')
        self.assertEqual(result['evidence'][0]['applicability'],'discarded');self.assertIsNone(result['evidence'][0]['value']);self.assertTrue(result['evidence'][0]['recorded_value'])
    def test_staff_and_ordinary_workers_do_not_claim_operator_api_jobs(self):
        from decisionops.commerce.openai_decisions import DecisionsConfig
        from decisionops.commerce.api_accounting import create_budget
        from decisionops.commerce import adaptive_jobs as jobs,schema as db,adaptive_investigations as service
        from decisionops.commerce.staff_investigations import work_once
        from decisionops.commerce.worker import work_once as ordinary_once
        cfg=DecisionsConfig('MANUAL-OPERATOR-ONLY',execution='live')
        with self.engine.begin() as c:create_budget(c,cfg.record())
        job=jobs.enqueue(self.engine,self.case()['id'],'Operator-only fictional report',api=cfg.record())
        self.assertEqual(work_once(self.engine)['event'],'idle');self.assertEqual(ordinary_once(self.engine)['event'],'idle')
        self.assertEqual(service.inspect(self.engine,job['run_id'])['job']['status'],'queued')
        with self.engine.connect() as c:self.assertEqual(c.execute(db.provider_calls.select()).all(),[])
    def test_different_report_cannot_compete_with_active_request(self):
        from decisionops.commerce import schema as db
        case=self.case();client=self.client();first=self.start(client,case,'FIRST')
        changed=client.post('/api/cases/'+case['id']+'/shipment-investigation',json={
            'report':'A different report','request_id':'SECOND','expected_generation':case['generation']})
        self.assertEqual(first.status_code,202);self.assertEqual(changed.status_code,409)
        with self.engine.connect() as c:
            self.assertEqual(len(c.execute(db.adaptive_runs.select()).all()),1)
            self.assertEqual(len(c.execute(db.adaptive_jobs.select()).all()),1)
    def test_new_staff_request_revokes_exact_old_proposal_approval(self):
        from decisionops.commerce.staff_investigations import work_once
        client=self.client();case=self.case();self.start(client,case);work_once(self.engine)
        previous=client.get('/api/cases/'+case['id']).json();proposal=previous['proposal']
        review={'generation':previous['generation'],'proposal_id':proposal['id'],
                'content_hash':proposal['content_hash'],'decision':'approve'}
        approved=client.post('/api/cases/'+case['id']+'/review',json=review)
        self.assertEqual(approved.status_code,200);operation=approved.json()['approval']['operation_id']
        current=client.get('/api/cases/'+case['id']).json()
        started=self.start(client,current,'GENUINELY-NEW')
        self.assertEqual(started.status_code,202)
        invalidated=client.get('/api/cases/'+case['id']).json()
        self.assertGreater(invalidated['generation'],previous['generation'])
        self.assertIsNone(invalidated['proposal']);self.assertIsNone(invalidated['approval'])
        self.assertEqual(client.post('/api/cases/'+case['id']+'/review',json=review).status_code,409)
        self.assertEqual(client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation}).status_code,409)
        work_once(self.engine)
        renewed=client.get('/api/cases/'+case['id']).json()
        self.assertIsNotNone(renewed['proposal']);self.assertNotEqual(renewed['proposal']['id'],proposal['id'])
        self.assertIsNone(renewed['approval'])
        self.assertEqual(client.post('/api/cases/'+case['id']+'/execute',json={'operation_id':operation}).status_code,409)
