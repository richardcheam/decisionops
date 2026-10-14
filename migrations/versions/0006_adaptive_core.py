"""Durable optional model-free adaptive reads and server-fenced case revision."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('commerce_cases',sa.Column('case_revision',sa.BigInteger,nullable=False,server_default='0'))
    op.execute("""CREATE FUNCTION commerce_bump_case_revision() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN NEW.case_revision := OLD.case_revision + 1; RETURN NEW; END $$""")
    op.execute('CREATE TRIGGER commerce_case_revision BEFORE UPDATE ON commerce_cases FOR EACH ROW EXECUTE FUNCTION commerce_bump_case_revision()')
    op.create_table('commerce_adaptive_runs',
        sa.Column('id',sa.String,primary_key=True),
        sa.Column('case_id',sa.String,sa.ForeignKey('commerce_cases.id'),nullable=False),
        sa.Column('generation',sa.Integer,nullable=False),sa.Column('case_revision',sa.BigInteger,nullable=False),
        sa.Column('request',JSONB,nullable=False),sa.Column('report',sa.Text,nullable=False),sa.Column('contracts',JSONB,nullable=False),
        sa.Column('state',sa.String,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
        sa.Column('context_version',sa.BigInteger,nullable=False,server_default='0'),
        sa.Column('decision_attempts',sa.Integer,nullable=False,server_default='0'),
        sa.Column('tool_attempts',sa.Integer,nullable=False,server_default='0'),
        sa.Column('pending_token',sa.String),sa.Column('pending_context',sa.BigInteger),sa.Column('terminal',JSONB),
        sa.CheckConstraint('generation > 0 AND case_revision >= 0 AND context_version >= 0'),
        sa.CheckConstraint("state IN ('active','proposed','blocker_reported','review','stale')"),
        sa.CheckConstraint('decision_attempts BETWEEN 0 AND 16 AND tool_attempts BETWEEN 0 AND 12'),
        sa.CheckConstraint("octet_length(report) <= 2000 AND deadline > created_at AND deadline <= created_at + INTERVAL '240 seconds'"),
        sa.CheckConstraint("state = 'active' OR (terminal IS NOT NULL AND pending_token IS NULL)"),
    sa.CheckConstraint("(pending_token IS NULL AND pending_context IS NULL) OR (pending_token IS NOT NULL AND pending_context BETWEEN 1 AND context_version)"))
    op.create_index('uq_adaptive_active_case','commerce_adaptive_runs',['case_id'],unique=True,postgresql_where=sa.text("state='active'"))
    op.create_table('commerce_adaptive_steps',
        sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),primary_key=True),
        sa.Column('sequence',sa.BigInteger,primary_key=True),sa.Column('kind',sa.String,nullable=False),
        sa.Column('data',JSONB,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.CheckConstraint('sequence > 0'))
    op.create_table('commerce_adaptive_observations',
        sa.Column('id',sa.String,primary_key=True),sa.Column('run_id',sa.String,nullable=False),
        sa.Column('step_sequence',sa.BigInteger,nullable=False),sa.Column('record',JSONB,nullable=False),sa.Column('applied',sa.Boolean,nullable=False),
        sa.UniqueConstraint('run_id','id'),
        sa.ForeignKeyConstraint(['run_id','step_sequence'],['commerce_adaptive_steps.run_id','commerce_adaptive_steps.sequence']))
    op.create_table('commerce_adaptive_supersessions',
        sa.Column('run_id',sa.String,primary_key=True),sa.Column('old_id',sa.String,primary_key=True),sa.Column('new_id',sa.String,nullable=False),
        sa.ForeignKeyConstraint(['run_id','old_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']),
        sa.ForeignKeyConstraint(['run_id','new_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']))
    op.create_table('commerce_adaptive_active',
        sa.Column('run_id',sa.String,primary_key=True),sa.Column('tool',sa.String,primary_key=True),
        sa.Column('stream',sa.String,primary_key=True),sa.Column('observation_id',sa.String,nullable=False),
        sa.ForeignKeyConstraint(['run_id','observation_id'],['commerce_adaptive_observations.run_id','commerce_adaptive_observations.id']))
    op.create_table('commerce_adaptive_tool_counts',
        sa.Column('run_id',sa.String,sa.ForeignKey('commerce_adaptive_runs.id'),primary_key=True),
        sa.Column('tool',sa.String,primary_key=True),sa.Column('attempts',sa.Integer,nullable=False),sa.CheckConstraint('attempts BETWEEN 1 AND 2'))
    for table in ('commerce_adaptive_steps','commerce_adaptive_observations','commerce_adaptive_supersessions'):
        op.execute(f'CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')
    op.execute("""CREATE FUNCTION commerce_guard_adaptive_run() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Adaptive runs cannot be deleted'; END IF;
        IF ROW(NEW.id,NEW.case_id,NEW.generation,NEW.case_revision,NEW.request,NEW.report,NEW.contracts,NEW.created_at,NEW.deadline)
          IS DISTINCT FROM ROW(OLD.id,OLD.case_id,OLD.generation,OLD.case_revision,OLD.request,OLD.report,OLD.contracts,OLD.created_at,OLD.deadline)
          THEN RAISE EXCEPTION 'Adaptive run binding is immutable'; END IF;
        IF NEW.context_version != OLD.context_version + 1 OR NEW.decision_attempts < OLD.decision_attempts
          OR NEW.tool_attempts < OLD.tool_attempts OR OLD.state != 'active'
          THEN RAISE EXCEPTION 'Adaptive progress cannot reset or rewrite terminal runs'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER commerce_adaptive_binding BEFORE UPDATE OR DELETE ON commerce_adaptive_runs FOR EACH ROW EXECUTE FUNCTION commerce_guard_adaptive_run()')
    op.execute("""CREATE FUNCTION commerce_guard_adaptive_counter() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' OR NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.tool IS DISTINCT FROM OLD.tool
          OR NEW.attempts != OLD.attempts + 1 THEN RAISE EXCEPTION 'Tool counter cannot reset'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER commerce_adaptive_counter BEFORE UPDATE OR DELETE ON commerce_adaptive_tool_counts FOR EACH ROW EXECUTE FUNCTION commerce_guard_adaptive_counter()')


def downgrade():
    for table in ('commerce_adaptive_tool_counts','commerce_adaptive_active','commerce_adaptive_supersessions',
                  'commerce_adaptive_observations','commerce_adaptive_steps','commerce_adaptive_runs'):
        op.drop_table(table)
    op.execute('DROP FUNCTION commerce_guard_adaptive_counter()')
    op.execute('DROP FUNCTION commerce_guard_adaptive_run()')
    op.execute('DROP TRIGGER commerce_case_revision ON commerce_cases')
    op.execute('DROP FUNCTION commerce_bump_case_revision()')
    op.drop_column('commerce_cases','case_revision')
