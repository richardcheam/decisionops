"""Tenant identities, opaque sessions and single-use staff invitations."""
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE commerce_pilot_stores (
        id VARCHAR PRIMARY KEY, name VARCHAR(120) NOT NULL
    )""")
    op.execute("""CREATE TABLE commerce_pilot_users (
        id VARCHAR PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE,
        password_hash VARCHAR NOT NULL
    )""")
    op.execute("""CREATE TABLE commerce_pilot_memberships (
        store_id VARCHAR REFERENCES commerce_pilot_stores(id),
        user_id VARCHAR REFERENCES commerce_pilot_users(id),
        role VARCHAR NOT NULL CHECK (role IN ('staff', 'approver')),
        PRIMARY KEY (store_id, user_id)
    )""")
    op.execute("""CREATE TABLE commerce_pilot_sessions (
        token_hash VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR NOT NULL REFERENCES commerce_pilot_users(id),
        expires_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("""CREATE TABLE commerce_pilot_invites (
        token_hash VARCHAR(64) PRIMARY KEY,
        store_id VARCHAR NOT NULL REFERENCES commerce_pilot_stores(id),
        email VARCHAR(254) NOT NULL,
        role VARCHAR NOT NULL CHECK (role IN ('staff', 'approver')),
        expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ
    )""")
    op.execute("""CREATE TABLE commerce_pilot_login_limits (
        kind VARCHAR(16), subject_hash VARCHAR(64), window_id BIGINT,
        attempts INTEGER NOT NULL CHECK (attempts > 0),
        PRIMARY KEY (kind, subject_hash, window_id)
    )""")


def downgrade():
    for suffix in ('login_limits', 'invites', 'sessions', 'memberships', 'users', 'stores'):
        op.drop_table('commerce_pilot_' + suffix)
