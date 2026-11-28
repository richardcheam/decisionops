"""Tenant-scoped Shopify installations, imports, decisions and durable send claims."""
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE commerce_shopify_connections (
        store_id VARCHAR PRIMARY KEY REFERENCES commerce_pilot_stores(id),
        shop VARCHAR NOT NULL UNIQUE, shop_gid VARCHAR NOT NULL UNIQUE,
        sealed_token VARCHAR NOT NULL, status VARCHAR NOT NULL
            CHECK (status IN ('connected', 'revoked'))
    )""")
    op.execute("""CREATE TABLE commerce_shopify_oauth (
        state_hash VARCHAR(64) PRIMARY KEY,
        store_id VARCHAR NOT NULL REFERENCES commerce_pilot_stores(id),
        actor_id VARCHAR NOT NULL REFERENCES commerce_pilot_users(id),
        shop VARCHAR NOT NULL, expires_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("""CREATE TABLE commerce_shopify_orders (
        store_id VARCHAR NOT NULL REFERENCES commerce_shopify_connections(store_id),
        order_id VARCHAR NOT NULL, snapshot JSONB NOT NULL,
        PRIMARY KEY (store_id, order_id)
    )""")
    op.execute("""CREATE TABLE commerce_shopify_cases (
        store_id VARCHAR NOT NULL REFERENCES commerce_shopify_connections(store_id),
        id VARCHAR NOT NULL, order_id VARCHAR NOT NULL, fulfillment_line_id VARCHAR NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity = 1), status VARCHAR NOT NULL
            CHECK (status IN ('draft','proposed','approved','pending','verified','needs_review')),
        reason VARCHAR NOT NULL, evidence JSONB, proposal_hash VARCHAR(64),
        approved_by VARCHAR REFERENCES commerce_pilot_users(id),
        confirmed_by VARCHAR REFERENCES commerce_pilot_users(id),
        dispatch_marker VARCHAR UNIQUE, external_return_id VARCHAR,
        created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (store_id, id), UNIQUE (store_id, order_id, fulfillment_line_id),
        UNIQUE (store_id, external_return_id),
        FOREIGN KEY (store_id, order_id) REFERENCES commerce_shopify_orders(store_id, order_id),
        CHECK (status <> 'verified' OR external_return_id IS NOT NULL),
        CHECK ((dispatch_marker IS NOT NULL) = (confirmed_by IS NOT NULL))
    )""")
    op.execute("""CREATE TABLE commerce_shopify_webhooks (
        store_id VARCHAR NOT NULL REFERENCES commerce_shopify_connections(store_id),
        delivery_id VARCHAR NOT NULL, body_digest VARCHAR(64) NOT NULL,
        PRIMARY KEY (store_id, delivery_id)
    )""")


def downgrade():
    op.drop_table('commerce_shopify_webhooks')
    op.drop_table('commerce_shopify_cases')
    op.drop_table('commerce_shopify_orders')
    op.drop_table('commerce_shopify_oauth')
    op.drop_table('commerce_shopify_connections')
