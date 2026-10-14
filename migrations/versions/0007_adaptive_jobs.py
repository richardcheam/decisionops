"""Partitioned adaptive jobs and task-aware recommendations; no business changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None


def upgrade():
    metadata=sa.MetaData()
    sa.Table('commerce_adaptive_runs',metadata,autoload_with=op.get_bind())
    adaptive_jobs = sa.Table(
        'commerce_adaptive_jobs',metadata,
        sa.Column('id',sa.String,primary_key=True),
        sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),nullable=False,unique=True),
        sa.Column('action',sa.String,nullable=False,server_default='adaptive_investigate/v1'),
        sa.Column('status',sa.String,nullable=False,server_default='queued'),
        sa.Column('token',sa.String),sa.Column('lease_until',sa.DateTime(timezone=True)),
        sa.Column('claims',sa.Integer,nullable=False,server_default='0'),
        sa.Column('error',sa.String),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("action='adaptive_investigate/v1' AND status IN ('queued','running','completed','cancelled','failed') AND claims BETWEEN 0 AND 16"),
        sa.CheckConstraint("status!='running' OR (token IS NOT NULL AND lease_until IS NOT NULL)"),
    )
    adaptive_calls = sa.Table(
        'commerce_adaptive_calls',metadata,
        sa.Column('id',sa.String,primary_key=True),sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),nullable=False),
        sa.Column('task',sa.String,nullable=False),sa.Column('request',JSONB,nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('context_version',sa.BigInteger,nullable=False),sa.Column('state',sa.String,nullable=False),
        sa.Column('dispatch_count',sa.Integer,nullable=False,server_default='0'),
        sa.Column('reserved_ms',sa.Integer,nullable=False),sa.Column('actual_ms',sa.Integer),
        sa.Column('reserved_cost_usd',sa.Numeric(20,8),nullable=False,server_default='0'),sa.Column('actual_cost_usd',sa.Numeric(20,8)),
        sa.Column('pricing_version',sa.String,nullable=False),sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
        sa.Column('application_status',sa.String,nullable=False,server_default='pending'),
        sa.Column('result',JSONB),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("task='choose_investigation_action/v1' AND state IN ('reserved','dispatching','settled','uncertain')"),
        sa.CheckConstraint("application_status IN ('pending','applied','stale') AND dispatch_count BETWEEN 0 AND 1"),
        sa.CheckConstraint("reserved_ms BETWEEN 1 AND 20000 AND reserved_cost_usd=0 AND (actual_cost_usd IS NULL OR actual_cost_usd=0)"),
        sa.CheckConstraint("actual_ms IS NULL OR actual_ms BETWEEN 0 AND reserved_ms"),
        sa.CheckConstraint("state!='settled' OR (result IS NOT NULL AND actual_ms IS NOT NULL AND actual_cost_usd IS NOT NULL)"),
        sa.CheckConstraint("state!='uncertain' OR (actual_ms IS NULL AND actual_cost_usd IS NULL)"),
        sa.UniqueConstraint('run_id','context_version'),
    )
    sa.Index('uq_adaptive_pending_decision',adaptive_calls.c.run_id,unique=True,
             postgresql_where=sa.text("state IN ('reserved','dispatching') OR (state='settled' AND application_status='pending')"))
    adaptive_call_events = sa.Table(
        'commerce_adaptive_call_events',metadata,
        sa.Column('call_id',sa.String,sa.ForeignKey('commerce_adaptive_calls.id'),primary_key=True),
        sa.Column('sequence',sa.Integer,primary_key=True),sa.Column('kind',sa.String,nullable=False),
        sa.Column('data',JSONB,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    )

    for table in (adaptive_jobs,adaptive_calls,adaptive_call_events):table.create(op.get_bind())
    op.execute('CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON commerce_adaptive_call_events FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')
    op.execute("""CREATE FUNCTION commerce_guard_adaptive_call() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Recommendation history cannot be deleted'; END IF;
        IF ROW(NEW.id,NEW.run_id,NEW.task,NEW.request,NEW.request_hash,NEW.context_version,NEW.reserved_ms,NEW.reserved_cost_usd,NEW.pricing_version,NEW.deadline,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.task,OLD.request,OLD.request_hash,OLD.context_version,OLD.reserved_ms,OLD.reserved_cost_usd,OLD.pricing_version,OLD.deadline,OLD.created_at)
          THEN RAISE EXCEPTION 'Recommendation binding immutable'; END IF;
        IF NEW.dispatch_count<OLD.dispatch_count OR
          (OLD.state IN ('settled','uncertain') AND ROW(NEW.state,NEW.result,NEW.actual_ms,NEW.actual_cost_usd,NEW.dispatch_count)
            IS DISTINCT FROM ROW(OLD.state,OLD.result,OLD.actual_ms,OLD.actual_cost_usd,OLD.dispatch_count))
          OR (OLD.state='dispatching' AND NEW.state NOT IN ('dispatching','settled','uncertain'))
          OR (OLD.application_status!='pending' AND NEW.application_status!=OLD.application_status)
          THEN RAISE EXCEPTION 'Recommendation progress cannot reset'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER commerce_adaptive_call_binding BEFORE UPDATE OR DELETE ON commerce_adaptive_calls FOR EACH ROW EXECUTE FUNCTION commerce_guard_adaptive_call()')


def downgrade():
    for table in ('commerce_adaptive_call_events','commerce_adaptive_calls','commerce_adaptive_jobs'):op.drop_table(table)
    op.execute('DROP FUNCTION commerce_guard_adaptive_call()')
