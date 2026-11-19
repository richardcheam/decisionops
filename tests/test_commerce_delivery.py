"""Real PostgreSQL delivery ingestion, reporting, queue and migration checks."""
from datetime import datetime, timedelta, timezone
import os
import importlib.util
from pathlib import Path
import unittest
import uuid

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('sqlalchemy'), 'Requires Commerce SQL profile')
class ParisWeekTests(unittest.TestCase):
    def test_local_monday_starts_sunday_utc_and_handles_dst(self):
        from decisionops.commerce.delivery import week_bounds
        start, end = week_bounds(datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(start.isoformat(), '2026-10-26T00:00:00+01:00')
        self.assertEqual(end.isoformat(), '2026-11-02T00:00:00+01:00')
        start, end = week_bounds(datetime(2026, 3, 25, 12, tzinfo=timezone.utc))
        self.assertEqual((end.astimezone(timezone.utc)-start.astimezone(timezone.utc)).total_seconds(), 167*3600)


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class DeliveryTests(unittest.TestCase):
    def setUp(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        self.admin = database_engine(os.environ['COMMERCE_TEST_DATABASE_URL'])
        self.schema = 'delivery_test_' + uuid.uuid4().hex
        with self.admin.begin() as c:
            c.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self.cleanup)
        self.engine = database_engine(make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+self.schema}))
        self.config = Config(str(ROOT / 'alembic.ini'))
        with self.engine.begin() as c:
            self.config.attributes['connection'] = c
            command.upgrade(self.config, 'head')

    def cleanup(self):
        self.engine.dispose()
        with self.admin.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()

    def seeded(self):
        from decisionops.commerce.delivery_seed import seed
        return seed(self.engine, NOW)

    def test_portfolio_seed_has_two_cases_and_keeps_existing_fixture_profile(self):
        from decisionops.commerce.delivery import queue
        from decisionops.commerce.delivery_seed import seed as full_seed
        from decisionops.commerce.portfolio_seed import seed
        from decisionops.commerce.read_tools import AssessmentRequest, read_assessment
        from decisionops.commerce import schema as db
        import sqlalchemy as sa

        seed(self.engine, NOW)
        seed(self.engine, NOW)
        full_seed(self.engine, NOW)
        with self.engine.connect() as c:
            cases = queue(c, 'demo-store', NOW)
            self.assertEqual({row['order_id'] for row in cases}, {'DEMO-LYON', 'DEMO-OVERDUE'})
            self.assertEqual(set(c.execute(sa.select(db.orders.c.id)).scalars()),
                             {'DEMO-LYON', 'DEMO-OVERDUE'})
            owners = set(c.execute(sa.select(db.customer_orders.c.customer_id,
                                             db.customer_orders.c.order_id)))
            self.assertEqual(owners, {('camille', 'DEMO-LYON'), ('alex', 'DEMO-OVERDUE')})
            decisions = {row['order_id']: read_assessment(c, AssessmentRequest(
                row['order_id'], row['shipment_id'], {'demo-tote': 1}), NOW)['decision']['status']
                for row in cases}
            self.assertEqual(decisions['DEMO-LYON'], 'eligible_to_propose')
            self.assertNotEqual(decisions['DEMO-OVERDUE'], 'eligible_to_propose')

    def test_portfolio_seed_preserves_existing_full_delivery_fixture(self):
        from decisionops.commerce.delivery import queue
        from decisionops.commerce.portfolio_seed import seed

        self.seeded()
        with self.engine.connect() as c:
            before = queue(c, 'demo-store', NOW)
        seed(self.engine, NOW)
        with self.engine.connect() as c:
            self.assertEqual(queue(c, 'demo-store', NOW), before)

    def test_seed_replay_known_totals_and_eligible_lyon(self):
        from decisionops.commerce.delivery import report, queue
        from decisionops.commerce.read_tools import read_assessment, AssessmentRequest
        self.seeded()
        with self.engine.begin() as c:
            before = report(c, 'demo-store', NOW)
            links = queue(c, 'demo-store', NOW)
            self.assertEqual((before['completed'], before['open'], before['overdue']), (3, 9, 8))
            lyon = next(row for row in links if row['order_id']=='DEMO-LYON')
            self.assertEqual(lyon['city'], 'Lyon')
            result = read_assessment(c, AssessmentRequest('DEMO-LYON', lyon['shipment_id'], {'demo-tote':1}), NOW)
            self.assertEqual(result['decision']['status'], 'eligible_to_propose')
        self.seeded()
        with self.engine.begin() as c:
            self.assertEqual(report(c, 'demo-store', NOW), before)
            self.assertEqual(queue(c, 'demo-store', NOW), links)
            self.assertEqual(report(c, 'another-store', NOW)['completed'], 0)
            self.assertEqual(queue(c, 'another-store', NOW), [])

    def test_nonreceipt_and_overdue_deduplicate_recover_without_status_reset(self):
        from decisionops.commerce.delivery import report_nonreceipt, scan, queue, ingest_event
        self.seeded()
        with self.engine.begin() as c:
            original = next(r for r in queue(c,'demo-store',NOW) if r['order_id']=='DEMO-LYON')
            report_nonreceipt(c,'demo-store',original['shipment_id'],NOW)
            scan(c,'demo-store',NOW)
            row = next(r for r in queue(c,'demo-store',NOW) if r['case_id']==original['case_id'])
            self.assertEqual(row['triggers'], ['nonreceipt','overdue'])
            delivered = next(r for r in queue(c,'demo-store',NOW) if r['order_id']=='DEMO-NONRECEIPT')
            self.assertEqual(delivered['carrier_status'], 'delivered')
            self.assertEqual(delivered['triggers'], ['nonreceipt'])
            with self.assertRaises(ValueError):
                report_nonreceipt(c,'another-store',original['shipment_id'],NOW)
            transit = next(r for r in queue(c,'demo-store',NOW) if r['order_id']=='DEMO-OVERDUE')
            ingest_event(c,'demo-store',transit['shipment_id'],'fixture','recovery','delivered',NOW,{'verified':True},now=NOW)
            scan(c,'demo-store',NOW)
            self.assertNotIn(transit['case_id'],[r['case_id'] for r in queue(c,'demo-store',NOW)])
            kinds = c.exec_driver_sql('SELECT kind FROM commerce_case_events WHERE case_id=%s',(transit['case_id'],)).scalars().all()
            self.assertIn('delivery_recovered',kinds)

    def test_events_preserve_conflicting_identity_and_cannot_be_mutated(self):
        from decisionops.commerce.delivery import ingest_event, timeline
        import sqlalchemy as sa
        from sqlalchemy.exc import DBAPIError
        from decisionops.commerce import schema as db
        self.seeded()
        with self.engine.begin() as c:
            shipment = 'PARCEL-DEMO-LYON'
            before = timeline(c,'demo-store',shipment)
            same = ingest_event(c,'demo-store',shipment,'fixture','lyon-loss','lost',NOW-timedelta(hours=1),{'verified':True},now=NOW)
            self.assertFalse(same['inserted'])
            self.assertEqual(timeline(c,'demo-store',shipment),before)
            ingest_event(c,'demo-store',shipment,'fixture','late-transit','in_transit',NOW-timedelta(days=3),{'verified':True},now=NOW)
            self.assertEqual(c.execute(sa.select(db.shipments.c.carrier_status).where(db.shipments.c.id==shipment)).scalar_one(),'lost')
            ingest_event(c,'demo-store',shipment,'fixture','lyon-loss','delivered',NOW-timedelta(hours=1),{'verified':True},now=NOW)
            self.assertEqual(c.execute(sa.select(db.shipments.c.carrier_status).where(db.shipments.c.id==shipment)).scalar_one(),'unknown')
            self.assertEqual(len(timeline(c,'demo-store',shipment)),len(before)+2)
            with self.assertRaises(DBAPIError):
                with c.begin_nested():
                    c.execute(db.carrier_events.update().values(status='lost'))

    def test_report_clock_excludes_records_not_received_yet(self):
        from decisionops.commerce.delivery import report
        self.seeded()
        with self.engine.begin() as c:
            earlier=report(c,'demo-store',NOW-timedelta(hours=2))
            self.assertEqual(earlier['completed'],0)
            self.assertEqual(earlier['open'],12)
            self.assertIsNone(earlier['latest_carrier_receipt'])

    def test_local_week_completion_boundary_uses_verified_event_time(self):
        from decisionops.commerce.delivery import ingest_event,report,week_bounds
        self.seeded()
        with self.engine.begin() as c:
            start,_=week_bounds(NOW)
            ingest_event(c,'demo-store','PARCEL-DEMO-FLIGHT','fixture','sunday-before','delivered',
                start-timedelta(microseconds=1),{'verified':True},now=NOW)
            self.assertEqual(report(c,'demo-store',NOW)['completed'],3)
            ingest_event(c,'demo-store','PARCEL-DEMO-FLIGHT','fixture','monday-at','delivered',
                start,{'verified':True},now=NOW)
            self.assertEqual(report(c,'demo-store',NOW)['completed'],4)

    def test_outage_replay_split_scope_and_staff_resolution(self):
        from decisionops.commerce.delivery import SimulatedCarrier,queue,scan
        from decisionops.commerce.read_tools import AssessmentRequest,read_assessment
        from decisionops.commerce.cases import escalate_case
        self.seeded()
        with self.engine.begin() as c:
            adapter=SimulatedCarrier()
            self.assertEqual(adapter.set_available(c,'demo-store','PARCEL-DEMO-LYON',False,NOW)['status'],'unknown')
            self.assertIsNone(read_assessment(c,AssessmentRequest('DEMO-LYON','PARCEL-DEMO-LYON',{'demo-tote':1}),NOW)['facts']['loss_confirmed'])
            self.assertEqual(adapter.set_available(c,'demo-store','PARCEL-DEMO-LYON',True,NOW)['status'],'lost')
            split=read_assessment(c,AssessmentRequest('DEMO-SPLIT','PARCEL-DEMO-SPLIT-A',{'demo-tote':1}),NOW)
            self.assertEqual(split['decision']['status'],'needs_review')
            self.assertIn('split_shipment',split['scope_reasons'])
            item=next(r for r in queue(c,'demo-store',NOW) if r['order_id']=='DEMO-LYON')
            escalate_case(c,item['case_id'],'Staff reviewing carrier dispute',NOW)
            scan(c,'demo-store',NOW)
            self.assertNotIn(item['case_id'],[r['case_id'] for r in queue(c,'demo-store',NOW)])
            self.assertEqual(c.exec_driver_sql('SELECT count(*) FROM commerce_case_events WHERE case_id=%s AND kind=%s',
                (item['case_id'],'delivery_resolved')).scalar_one(),1)

    def test_concurrent_scanners_create_one_case_and_trigger(self):
        import sqlalchemy as sa
        from concurrent.futures import ThreadPoolExecutor
        from decisionops.commerce import schema as db
        from decisionops.commerce.delivery import scan
        self.seeded()
        with self.engine.begin() as c:
            c.execute(db.delivery_parcels.update().where(db.delivery_parcels.c.shipment_id=='PARCEL-DEMO-FLIGHT').values(promised_at=NOW-timedelta(hours=1)))
        def run_scan(_):
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                return scan(c,'demo-store',NOW)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run_scan,range(2)))
        self.assertEqual(results[0],results[1])
        with self.engine.begin() as c:
            self.assertEqual(c.exec_driver_sql("SELECT count(*) FROM commerce_delivery_case_links WHERE shipment_id='PARCEL-DEMO-FLIGHT'").scalar_one(),1)
            self.assertEqual(c.exec_driver_sql("SELECT count(*) FROM commerce_case_events e JOIN commerce_delivery_case_links l ON e.case_id=l.case_id WHERE l.shipment_id='PARCEL-DEMO-FLIGHT' AND e.kind='delivery_trigger_added'").scalar_one(),1)

    def test_terminal_conflict_is_independent_of_receipt_order(self):
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        from decisionops.commerce.delivery import ingest_event,timeline
        self.seeded()
        with self.engine.begin() as c:
            for shipment,statuses in [('PARCEL-DEMO-FLIGHT',('lost','delivered')),('PARCEL-DEMO-OVERDUE',('delivered','lost'))]:
                for status in statuses:
                    ingest_event(c,'demo-store',shipment,'fixture',shipment+'-'+status,status,
                        NOW-timedelta(minutes=30),{'verified':True},now=NOW)
                self.assertEqual(c.execute(sa.select(db.shipments.c.carrier_status).where(db.shipments.c.id==shipment)).scalar_one(),'unknown')
                self.assertEqual(len(timeline(c,'demo-store',shipment)),3)

    def test_seed_first_hour_of_paris_week_still_has_three_completions(self):
        from decisionops.commerce.delivery_seed import seed
        from decisionops.commerce.delivery import report
        monday=datetime(2026,11,8,23,30,tzinfo=timezone.utc)
        seed(self.engine,monday)
        with self.engine.begin() as c:
            result=report(c,'demo-store',monday)
            self.assertEqual(result['completed'],3)
            self.assertEqual(result['start'],'2026-11-09T00:00:00+01:00')

    def test_upgrade_0009_preserves_existing_fixture_and_readiness(self):
        from alembic import command
        from decisionops.commerce.seed import seed as legacy_seed
        from decisionops.commerce.schema_readiness import validate_readiness
        # A second independent schema runs the actual supported 0009 upgrade.
        upgrade_schema = 'delivery_upgrade_' + uuid.uuid4().hex
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        with self.admin.begin() as c:
            c.exec_driver_sql(f'CREATE SCHEMA "{upgrade_schema}"')
        engine = database_engine(make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+upgrade_schema}))
        try:
            with engine.begin() as c:
                self.config.attributes['connection']=c
                command.upgrade(self.config,'0009')
            legacy_seed(engine, observed_at=NOW)
            with engine.begin() as c:
                snapshot = c.exec_driver_sql('SELECT * FROM shipments ORDER BY id').all()
                self.config.attributes['connection']=c
                command.upgrade(self.config,'head')
                validate_readiness(c)
                self.assertEqual(c.exec_driver_sql('SELECT * FROM shipments ORDER BY id').all(),snapshot)
            from decisionops.commerce.delivery_seed import seed
            seed(engine,NOW)
            with engine.begin() as c:
                self.assertEqual(c.exec_driver_sql("SELECT * FROM shipments WHERE id LIKE %s ORDER BY id", ("SHIP-%",)).all(),snapshot)
        finally:
            engine.dispose()
            with self.admin.begin() as c:
                c.exec_driver_sql(f'DROP SCHEMA "{upgrade_schema}" CASCADE')

    def test_incomplete_parcel_manifest_cannot_stall_other_staff_work(self):
        from decisionops.commerce import schema as db
        from decisionops.commerce.delivery import scan
        from decisionops.commerce.staff_investigations import work_once,enqueue
        from decisionops.commerce.seed import seed
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        from decisionops.commerce.delivery_seed import seed as fr_seed
        from datetime import datetime,timezone
        current=datetime.now(timezone.utc)
        seed(self.engine,current);fr_seed(self.engine,current)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            c.execute(db.delivery_triggers.delete().where(db.delivery_triggers.c.shipment_id=='PARCEL-DEMO-LYON'))
            c.execute(db.delivery_case_links.delete().where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-LYON'))
            c.execute(db.shipment_lines.delete().where(db.shipment_lines.c.shipment_id=='PARCEL-DEMO-LYON'))
            case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
            enqueue(c,self.engine,case['id'],'Missing parcel','UNRELATED',case['generation'],'rules')
            rows=scan(c,'demo-store',current)
            self.assertTrue(any(r['order_id']=='DEMO-LYON' for r in rows))
        self.assertEqual(work_once(self.engine)['state'],'proposed')

    def test_scanner_locks_existing_split_cases_before_new_order_fk(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        import sqlalchemy as sa
        from decisionops.commerce import schema as db
        from decisionops.commerce.delivery import scan
        from decisionops.commerce.cases import lock_case,lock_business
        from decisionops.commerce.read_tools import AssessmentRequest
        self.seeded()
        with self.engine.begin() as c:
            peer=c.execute(sa.select(db.delivery_case_links.c.case_id).where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-SPLIT-B')).scalar_one()
            c.execute(db.delivery_triggers.delete().where(db.delivery_triggers.c.shipment_id=='PARCEL-DEMO-SPLIT-A'))
            c.execute(db.delivery_case_links.delete().where(db.delivery_case_links.c.shipment_id=='PARCEL-DEMO-SPLIT-A'))
        held,attempted=Event(),Event()
        def observe(c,cursor,statement,parameters,context,many):
            if c.info.get('scan_probe') and 'commerce_cases' in statement and 'FOR UPDATE' in statement:attempted.set()
        sa.event.listen(self.engine,'before_cursor_execute',observe)
        def reviewer():
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                lock_case(c,peer);held.set()
                self.assertTrue(attempted.wait(4),'Scanner did not reach case lock')
                lock_business(c,AssessmentRequest('DEMO-SPLIT','PARCEL-DEMO-SPLIT-B',{'demo-tote':1}))
        def scanner():
            self.assertTrue(held.wait(4))
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
                c.info['scan_probe']=True
                try:return scan(c,'demo-store',NOW)
                finally:c.info.pop('scan_probe',None)
        try:
            with ThreadPoolExecutor(2) as pool:
                a=pool.submit(reviewer);b=pool.submit(scanner)
                a.result(10);self.assertTrue(b.result(10))
        finally:sa.event.remove(self.engine,'before_cursor_execute',observe)
