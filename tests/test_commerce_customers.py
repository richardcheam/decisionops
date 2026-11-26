"""Customer principal and owned customer/staff workflow, isolated PostgreSQL."""
import os
import unittest
from unittest.mock import patch
import test_commerce_adaptive_core as core

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL')
class CustomerTests(unittest.TestCase):
    setUp=core.AdaptiveCoreTests.setUp
    cleanup=core.AdaptiveCoreTests.cleanup

    def test_customer_session_has_separate_server_bound_identity(self):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        with patch.dict(os.environ, {'COMMERCE_CUSTOMER_CAMILLE_PASSWORD':'fictional-camille-test-only',
                                     'COMMERCE_CUSTOMER_ALEX_PASSWORD':'fictional-alex-test-only'}):
            app=create_app(self.engine,password='fictional-staff-test-only')
        client=TestClient(app)
        response=client.get('/customer-api/session',auth=('camille','fictional-camille-test-only'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['customer_id'],'camille')
        self.assertEqual(client.get('/api/session',auth=('camille','fictional-camille-test-only')).status_code,401)

    def fixture(self, router=None):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        from decisionops.commerce.delivery_seed import seed
        from decisionops.commerce.customer_seed import seed as customers
        seed(self.engine);customers(self.engine)
        with patch.dict(os.environ, {'COMMERCE_CUSTOMER_CAMILLE_PASSWORD':'fictional-camille-test-only',
                                     'COMMERCE_CUSTOMER_ALEX_PASSWORD':'fictional-alex-test-only'}):
            app=create_app(self.engine,password='fictional-staff-test-only',customer_router=router,
                staff_investigation_mode='mock-specialists',staff_accounts={'helper':{'password':'fictional-helper-test-only','role':'staff'}})
        return TestClient(app)

    def conversation(self,client,owner='camille',order='DEMO-LYON',parcel='PARCEL-DEMO-LYON'):
        auth=(owner,'fictional-'+owner+'-test-only')
        response=client.post('/customer-api/conversations',json={},auth=auth)
        self.assertEqual(response.status_code,201,response.text)
        identity=response.json()['id']
        response=client.post('/customer-api/conversations/'+identity+'/select',json={'order_id':order,'shipment_id':parcel},auth=auth)
        self.assertEqual(response.status_code,200,response.text)
        return identity

    def say(self,client,identity,message='My parcel never arrived. Please report it missing.',key=None,owner='camille'):
        import uuid
        return client.post('/customer-api/conversations/'+identity+'/messages',json={'message':message,'request_id':key or uuid.uuid4().hex},auth=(owner,'fictional-'+owner+'-test-only'))

    def test_shop_guidance_and_order_summary_use_owned_data(self):
        client=self.fixture()
        auth=('camille','fictional-camille-test-only')
        identity=client.post('/customer-api/conversations',json={},auth=auth).json()['id']
        for question, intent, phrase in (
            ('How do I return an item?', 'returns_help', 'return instructions'),
            ('Can I get a refund?', 'refund_help', 'refund status'),
            ('Can I change my shipping address?', 'order_change_help', 'contact the shop'),
            ('How can I talk to someone?', 'support_help', 'order reference'),
        ):
            with self.subTest(question=question):
                reply=self.say(client,identity,question)
                self.assertEqual(reply.status_code,200)
                self.assertEqual(reply.json()['intent'],intent)
                self.assertIn(phrase,reply.json()['text'])
        split=self.say(client,identity,'What did I order in DEMO-SPLIT?').json()
        self.assertEqual(split['intent'],'order_summary')
        self.assertIn('2 parcels',split['text'])
        blocked=self.say(client,identity,'What did I order in DEMO-OVERDUE?')
        self.assertEqual(blocked.status_code,404)

    def test_owned_routes_reject_same_store_second_customer_and_cross_role_actions(self):
        client=self.fixture();identity=self.conversation(client)
        result=self.say(client,identity);self.assertEqual(result.status_code,200,result.text)
        case=result.json()['case_id'];other=('alex','fictional-alex-test-only')
        for path in ('orders/DEMO-LYON','parcels/PARCEL-DEMO-LYON','cases/'+case,'conversations/'+identity):
            self.assertEqual(client.get('/customer-api/'+path,auth=other).status_code,404,path)
        self.assertEqual(self.say(client,identity,owner='alex').status_code,404)
        self.assertEqual(client.post('/customer-api/conversations/'+identity+'/select',json={'order_id':'DEMO-FLIGHT','shipment_id':'PARCEL-DEMO-FLIGHT'},auth=other).status_code,404)
        self.assertEqual(client.get('/api/cases/'+case,auth=('camille','fictional-camille-test-only')).status_code,401)
        for endpoint,body in [('review',{'generation':1,'proposal_id':'guess','content_hash':'0'*64,'decision':'approve'}),('execute',{'operation_id':'guess'})]:
            self.assertEqual(client.post('/api/cases/'+case+'/'+endpoint,json=body,auth=('helper','fictional-helper-test-only')).status_code,403)
        self.assertEqual(client.get('/customer-api/orders',auth=('operator','fictional-staff-test-only')).status_code,401)

    def test_reports_reuse_overdue_case_and_replay_preserves_distinct_records(self):
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture();identity=self.conversation(client)
        with self.engine.connect() as c:
            existing=c.execute(sa.select(db.delivery_case_links.c.case_id).where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-LYON')).scalar_one()
        first=self.say(client,identity,key='REPORT-1');self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['case_id'],existing)
        self.assertEqual(self.say(client,identity,key='REPORT-1').json(),first.json())
        second=self.conversation(client);self.assertEqual(self.say(client,second).json()['case_id'],existing)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports)).scalar_one(),2)
            self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.delivery_case_links).where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-LYON')).scalar_one(),1)
            self.assertGreater(c.execute(sa.select(sa.func.count()).select_from(db.carrier_events)).scalar_one(),0)
            kinds=c.execute(sa.select(db.delivery_triggers.c.kind).where(db.delivery_triggers.c.shipment_id=='PARCEL-DEMO-LYON')).scalars().all()
            self.assertIn('overdue',kinds);self.assertIn('nonreceipt',kinds)

    def test_split_status_hypothetical_and_model_scope_cannot_file_report(self):
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture();identity=self.conversation(client,order='DEMO-SPLIT',parcel=None)
        response=self.say(client,identity)
        self.assertEqual(response.json()['intent'],'clarify');self.assertEqual(len(response.json()['parcels']),2)
        lyon=self.conversation(client)
        for text in ('What is the delivery status?','What if my parcel never arrived?','Do not report my parcel missing.','How to report my parcel missing?',
                     'I did not report my parcel missing.','I never said my parcel never arrived.',
                     'The help page says "My parcel never arrived. Please report it missing." What does that mean?',
                     'My parcel never arrived. This is an example from a guide.'):
            response=self.say(client,lyon,text);self.assertNotIn('case_id',response.json())
        response=self.say(client,lyon,'Please report DEMO-FLIGHT missing')
        self.assertEqual(response.status_code,404)
        with self.engine.connect() as c:self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports)).scalar_one(),0)

    def test_original_conversation_projects_verified_replacement_without_internal_records(self):
        from decisionops.commerce.cases import investigate_case,review_case
        from decisionops.commerce.execution import execute
        client=self.fixture();identity=self.conversation(client);case=self.say(client,identity).json()['case_id']
        auth=('camille','fictional-camille-test-only')
        before=client.get('/customer-api/conversations/'+identity,auth=auth).json()
        self.assertFalse(before['cases'][0]['replacement_created'])
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            saved=investigate_case(c,case)
            saved=review_case(c,case,saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
            self.assertEqual(execute(c,case,saved['approval']['operation_id'])['status'],'verified')
        after=client.get('/customer-api/conversations/'+identity,auth=auth).json()
        self.assertTrue(after['cases'][0]['replacement_created']);self.assertFalse(after['cases'][0]['shipped'])
        self.assertIn('replacement',after['cases'][0]['text'].lower())
        for forbidden in ('compensation','inventory','content_hash','observations','reservations','approval_id'):
            self.assertNotIn(forbidden,__import__('json').dumps(after))

    def test_concurrent_reports_and_scan_keep_one_case(self):
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce.delivery import scan
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture()
        ids=[self.conversation(client) for _ in range(3)]
        def report(identity):return self.say(client,identity).json()['case_id']
        def scanner():
            with self.engine.begin() as c:scan(c,'demo-store')
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(report,i) for i in ids];job=pool.submit(scanner)
            cases=[j.result(timeout=20) for j in jobs];job.result(timeout=20)
        self.assertEqual(len(set(cases)),1)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.cases).where(db.cases.c.order_id=='DEMO-LYON')).scalar_one(),1)

    def test_ambiguity_clears_prior_selection_and_questions_do_not_file(self):
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture();identity=self.conversation(client)
        response=self.say(client,identity,'Report DEMO-LYON or DEMO-SPLIT missing')
        self.assertEqual(response.json()['intent'],'clarify')
        response=self.say(client,identity)
        self.assertEqual(response.json()['intent'],'clarify')
        self.assertNotIn('case_id',response.json())
        other=self.conversation(client)
        self.assertNotIn('case_id',self.say(client,other,'Can you check whether my parcel never arrived?').json())
        with self.engine.connect() as c:self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports)).scalar_one(),0)

    def test_conversation_store_binding_even_without_report(self):
        from fastapi.testclient import TestClient
        from decisionops.commerce.api import create_app
        client=self.fixture();identity=client.post('/customer-api/conversations',json={},auth=('camille','fictional-camille-test-only')).json()['id']
        self.say(client,identity,'Hello from my private conversation')
        with patch.dict(os.environ, {'COMMERCE_CUSTOMER_CAMILLE_PASSWORD':'fictional-camille-test-only'}):
            other=TestClient(create_app(self.engine,password='fictional-staff-test-only',store_id='another-shop'))
        auth=('camille','fictional-camille-test-only')
        self.assertEqual(other.get('/customer-api/conversations/'+identity,auth=auth).status_code,404)
        self.assertEqual(other.post('/customer-api/conversations/'+identity+'/messages',auth=auth,json={'message':'status','request_id':'WRONG-STORE'}).status_code,404)

    def test_model_report_choice_cannot_turn_status_question_into_report(self):
        from decisionops.commerce.role_actions import ModelActionAdapter
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        adapter=ModelActionAdapter(lambda _: {'kind':'report_nonreceipt'})
        client=self.fixture(router=adapter.customer());identity=self.conversation(client)
        self.assertEqual(self.say(client,identity,'delivery status').json()['intent'],'delivery_status')
        self.assertEqual(self.say(client,identity,'Can you check whether my parcel never arrived?').json()['intent'],'clarify')
        with self.engine.connect() as c:self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports)).scalar_one(),0)

    def test_explicit_split_replaces_previous_parcel_before_clarification(self):
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture();identity=self.conversation(client)
        self.assertEqual(self.say(client,identity,'Report DEMO-SPLIT missing').json()['intent'],'clarify')
        self.assertEqual(self.say(client,identity).json()['intent'],'clarify')
        view=client.get('/customer-api/conversations/'+identity,auth=('camille','fictional-camille-test-only')).json()
        self.assertEqual(view['selected_order_id'],'DEMO-SPLIT');self.assertIsNone(view['selected_shipment_id'])
        with self.engine.connect() as c:self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports)).scalar_one(),0)

    def test_first_admission_races_report_scan_and_replays_after_app_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from datetime import datetime,timedelta,timezone
        from decisionops.commerce.delivery import scan
        from decisionops.commerce import schema as db
        import sqlalchemy as sa
        client=self.fixture()
        ids=[self.conversation(client,owner='alex',order='DEMO-FLIGHT',parcel='PARCEL-DEMO-FLIGHT') for _ in range(2)]
        with self.engine.begin() as c:
            self.assertIsNone(c.execute(sa.select(db.delivery_case_links.c.case_id).where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-FLIGHT')).scalar_one_or_none())
            c.execute(db.delivery_parcels.update().where(db.delivery_parcels.c.shipment_id=='PARCEL-DEMO-FLIGHT').values(promised_at=datetime.now(timezone.utc)-timedelta(hours=1)))
        barrier=Barrier(3)
        def submit(identity):
            barrier.wait();return self.say(client,identity,key='FIRST',owner='alex').json()['case_id']
        def scanning():
            barrier.wait()
            with self.engine.begin() as c:scan(c,'demo-store')
        with ThreadPoolExecutor(3) as pool:
            futures=[pool.submit(submit,i) for i in ids];other=pool.submit(scanning)
            cases=[f.result(20) for f in futures];other.result(20)
        self.assertEqual(cases[0],cases[1])
        from fastapi.testclient import TestClient
        restarted=TestClient(client.app)
        self.assertEqual(self.say(restarted,ids[0],key='FIRST',owner='alex').json()['case_id'],cases[0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.cases).where(db.cases.c.order_id=='DEMO-FLIGHT')).scalar_one(),1)
            self.assertEqual(c.execute(sa.select(sa.func.count()).select_from(db.customer_reports).where(db.customer_reports.c.case_id==cases[0])).scalar_one(),2)

    def test_approval_is_not_customer_success_and_inconsistent_counter_revokes_success_view(self):
        from decisionops.commerce import schema as db
        from decisionops.commerce.cases import investigate_case,review_case
        from decisionops.commerce.execution import execute
        client=self.fixture();identity=self.conversation(client);case=self.say(client,identity).json()['case_id']
        auth=('camille','fictional-camille-test-only')
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            saved=investigate_case(c,case)
            approved=review_case(c,case,saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
        self.assertFalse(client.get('/customer-api/cases/'+case,auth=auth).json()['replacement_created'])
        with self.engine.begin() as c:execute(c,case,approved['approval']['operation_id'])
        self.assertTrue(client.get('/customer-api/cases/'+case,auth=auth).json()['replacement_created'])
        with self.engine.begin() as c:c.execute(db.inventory.update().where(db.inventory.c.variant_id=='demo-tote').values(reserved=0))
        result=client.get('/customer-api/conversations/'+identity,auth=auth).json()['cases'][0]
        self.assertFalse(result['replacement_created']);self.assertFalse(result['shipped']);self.assertEqual(result['status'],'in_review')

    def test_upgrade_0010_preserves_orders_and_adds_owned_customer_schema(self):
        from alembic import command
        from alembic.config import Config
        from decisionops.commerce.schema_readiness import validate_readiness
        from decisionops.commerce.customer_seed import seed
        config=Config('alembic.ini')
        with self.engine.begin() as c:
            count=c.exec_driver_sql('SELECT count(*) FROM orders').scalar_one()
            config.attributes['connection']=c;command.downgrade(config,'0010');command.upgrade(config,'head')
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM orders').scalar_one(),count)
            validate_readiness(c)
        from decisionops.commerce.delivery_seed import seed as delivery
        delivery(self.engine);seed(self.engine)
        with self.engine.connect() as c:self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_customers').scalar_one(),2)

    def test_customer_report_cannot_bind_foreign_case_and_parcel_in_database(self):
        from decisionops.commerce import schema as db
        from sqlalchemy.exc import IntegrityError
        import sqlalchemy as sa
        client=self.fixture();identity=self.conversation(client);result=self.say(client,identity).json()
        with self.engine.begin() as c:
            saved=dict(c.execute(sa.select(db.customer_reports)).mappings().one());saved['id']='FORGED-REPORT';saved['request_id']='FORGED'
            saved['shipment_id']='PARCEL-DEMO-SPLIT-A'
            with self.assertRaises(IntegrityError):
                with c.begin_nested():c.execute(db.customer_reports.insert().values(**saved))

    def test_explicit_case_reference_is_owned_and_cannot_silently_use_selection(self):
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        client=self.fixture();identity=self.conversation(client)
        with self.engine.connect() as c:
            cases={r['order_id']:r['case_id'] for r in c.execute(sa.select(db.delivery_case_links)).mappings()}
        self.assertEqual(self.say(client,identity,'What is the status of '+cases['DEMO-OVERDUE']+'?').status_code,404)
        response=self.say(client,identity,'What is the status of '+cases['DEMO-CONFLICT']+'?')
        self.assertEqual(response.status_code,200,response.text)
        view=client.get('/customer-api/conversations/'+identity,auth=('camille','fictional-camille-test-only')).json()
        self.assertEqual(view['selected_order_id'],'DEMO-CONFLICT')
        self.assertEqual(self.say(client,identity,'Check '+cases['DEMO-LYON']+' or '+cases['DEMO-CONFLICT']).json()['intent'],'clarify')

    def test_customer_text_is_untrusted_staff_context_not_loss_evidence(self):
        from decisionops.commerce.staff_investigations import enqueue,work_once
        from decisionops.commerce import adaptive_investigations as service
        client=self.fixture();identity=self.conversation(client,owner='alex',order='DEMO-OVERDUE',parcel='PARCEL-DEMO-OVERDUE')
        text='My parcel never arrived. Please report it missing.'
        case_id=self.say(client,identity,text,owner='alex').json()['case_id']
        with self.engine.begin() as c:
            run=enqueue(c,self.engine,case_id,'Fix this','STAFF-CUSTOMER-CONTEXT',0,'mock-specialists')
        self.assertIn(text,run['report']);self.assertIn('untrusted',run['report'].lower())
        work_once(self.engine)
        saved=service.inspect(self.engine,run['id'])
        self.assertEqual(saved['state'],'review');self.assertIsNone(saved['terminal'].get('proposal_id'))
        with self.engine.begin() as c:
            replay=enqueue(c,self.engine,case_id,'Fix this','STAFF-CUSTOMER-CONTEXT',0,'mock-specialists')
        self.assertEqual(replay['id'],run['id'])
