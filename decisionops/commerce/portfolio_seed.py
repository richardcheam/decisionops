"""Seed the two-case portfolio demo, preserving existing delivery fixtures."""
import json

from .customer_seed import seed as seed_customers
from .database import database_engine
from .delivery_seed import COMPACT_ORDERS, COMPACT_SEED_ID, seed as seed_deliveries


def seed(engine, now=None):
    result = seed_deliveries(engine, now, compact=True)
    order_ids = COMPACT_ORDERS if result['seed_version'] == COMPACT_SEED_ID else None
    seed_customers(engine, order_ids=order_ids)
    return result


if __name__ == '__main__':
    engine = database_engine()
    try:
        print(json.dumps(seed(engine)))
    finally:
        engine.dispose()
