"""Synthetic France delivery scenarios; historical commerce-demo-v1 is untouched.

Run against an isolated migrated demo database. Repeating seed never resets staff
work, reservations, events or the original clock. Reset by creating a new database.
"""
import argparse
from datetime import datetime, timedelta
import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock
from .delivery import SimulatedCarrier, aware, ingest_event, scan, report, week_bounds, _lock
from .database import database_engine

SEED_ID='commerce-delivery-fr-v1'
COMPACT_SEED_ID='commerce-delivery-fr-compact-v1'
COMPACT_ORDERS=('DEMO-LYON', 'DEMO-OVERDUE')
STORE_ID='demo-store'


def seed(engine, now=None, *, compact=False):
    with engine.connect().execution_options(isolation_level='READ COMMITTED') as c, c.begin():
        _lock(c,STORE_ID)
        existing = c.execute(sa.select(db.seed_versions.c.id).where(
            db.seed_versions.c.id.in_((SEED_ID, COMPACT_SEED_ID)))).scalar_one_or_none()
        if existing:
            return {'event':'already_seeded','seed_version':existing}
        seed_id = COMPACT_SEED_ID if compact else SEED_ID
        now=aware(clock(c,now))
        start,_=week_bounds(now)
        c.execute(db.policies.insert().values(id='demo-fr-policy-v1',store_id=STORE_ID,version=100,
            allow_confirmed_loss=True,max_units=10,carrier_max_age_seconds=86400))
        c.execute(insert(db.inventory).values(store_id=STORE_ID,variant_id='demo-tote',on_hand=100,reserved=0).on_conflict_do_nothing())
        specs=[
            ('ONTIME','Paris','delivered',False),
            ('SAINTDENIS','Saint-Denis','delivered',False),
            ('NONRECEIPT','Marseille','delivered',True),
            ('LYON','Lyon','lost',False),
            ('OVERDUE','Lille','in_transit',False),
            ('SPLIT','Nantes','lost',False),
            ('HISTORY','Paris','lost',False),
            ('REPLACED','Marseille','lost',False),
            ('OUTAGE','Lille','unknown',False),
            ('CONFLICT','Saint-Denis','lost',False),
            ('FLIGHT','Nantes','in_transit',False),
        ]
        for suffix,city,status,nonreceipt in specs:
            order='DEMO-'+suffix
            if compact and order not in COMPACT_ORDERS:
                continue
            quantity=2 if suffix=='SPLIT' else 1
            c.execute(db.orders.insert().values(id=order,store_id=STORE_ID,policy_id='demo-fr-policy-v1',currency='EUR',
                resolution_history_complete=suffix!='HISTORY'))
            c.execute(db.order_lines.insert().values(order_id=order,variant_id='demo-tote',quantity=quantity,unit_price_minor=2900))
            c.execute(db.payments.insert().values(order_id=order,status='paid',amount_minor=2900*quantity,currency='EUR'))
            for parcel_suffix in ('-A','-B') if suffix=='SPLIT' else ('',):
                shipment='PARCEL-'+order+parcel_suffix
                c.execute(db.shipments.insert().values(id=shipment,order_id=order,fulfilment_status='shipped',
                    carrier_status='unknown',carrier_observed_at=now))
                c.execute(db.shipment_lines.insert().values(shipment_id=shipment,order_id=order,variant_id='demo-tote',quantity=1))
                c.execute(db.delivery_parcels.insert().values(shipment_id=shipment,order_id=order,store_id=STORE_ID,city=city,
                    dispatch_origin='Paris',dispatched_at=now-timedelta(days=8),
                    promised_at=now+timedelta(days=1) if suffix=='FLIGHT' or status=='delivered' else now-timedelta(days=1),
                    reported_nonreceipt=nonreceipt))
                external='lyon-loss' if suffix=='LYON' else suffix.lower()+parcel_suffix+'-event'
                ingest_event(c,STORE_ID,shipment,'fixture',external,status,
                    max(now-timedelta(hours=1),start) if status=='delivered' else now-timedelta(hours=1),
                    {'verified':suffix!='OUTAGE'},now=now)
                if suffix=='LYON':
                    ingest_event(c,STORE_ID,shipment,'fixture','lyon-late-transit','in_transit',now-timedelta(days=3),
                                 {'verified':True,'note':'Received after confirmed loss; earlier carrier event time'},now=now)
                if suffix=='CONFLICT':
                    ingest_event(c,STORE_ID,shipment,'fixture','conflicting-delivery','delivered',start-timedelta(hours=2),
                        {'verified':True,'note':'Opposing authoritative terminal record'},now=now)
                if suffix=='OUTAGE':
                    SimulatedCarrier().set_available(c,STORE_ID,shipment,False,now)
            if suffix=='REPLACED':
                c.execute(db.resolutions.insert().values(id='DEMO-PRIOR-REPLACEMENT',order_id=order,variant_id='demo-tote',quantity=1,kind='replacement'))
        c.execute(db.seed_versions.insert().values(id=seed_id))
        scan(c,STORE_ID,now)
        summary=report(c,STORE_ID,now)
        return {'event':'seeded','seed_version':seed_id,'clock':now.isoformat(),
                'completed':summary['completed'],'open':summary['open'],'overdue':summary['overdue'],'exceptions':summary['exceptions']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--now',help='Explicit ISO demo clock with timezone; default database clock')
    args=parser.parse_args()
    engine=database_engine()
    try:
        print(json.dumps(seed(engine,datetime.fromisoformat(args.now) if args.now else None)))
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
