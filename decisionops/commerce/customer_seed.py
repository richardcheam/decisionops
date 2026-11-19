"""Two fictional customers with different orders; no credentials in business data."""
from sqlalchemy.dialects.postgresql import insert
from . import schema as db
from .database import database_engine

OWNERS = {
    'camille': ('Camille Martin', ('DEMO-LYON','DEMO-SPLIT','DEMO-CONFLICT','DEMO-HISTORY','DEMO-ONTIME','DEMO-NONRECEIPT')),
    'alex': ('Alex Bernard', ('DEMO-FLIGHT','DEMO-OVERDUE','DEMO-OUTAGE','DEMO-REPLACED','DEMO-SAINTDENIS')),
}

def seed(engine, *, order_ids=None):
    with engine.begin() as c:
        for identity,(name,orders) in OWNERS.items():
            c.execute(insert(db.customers).values(id=identity,store_id='demo-store',display_name=name).on_conflict_do_nothing())
            for order in orders:
                if order_ids is not None and order not in order_ids:
                    continue
                c.execute(insert(db.customer_orders).values(customer_id=identity,store_id='demo-store',order_id=order).on_conflict_do_nothing())

if __name__=='__main__':
    engine=database_engine()
    try:seed(engine)
    finally:engine.dispose()
