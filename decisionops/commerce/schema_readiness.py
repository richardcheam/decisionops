"""Read-only readiness for this source's explicit PostgreSQL schema contract.

Revision 0008 plus mapped column shapes and enabled mutation guards. This is not a
migration engine or a complete adversarial schema-definition integrity verifier.
"""
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from .schema import metadata

SUPPORTED_REVISION='0008'
class SchemaNotReady(RuntimeError):pass

GUARDS={
    ('commerce_cases','commerce_case_revision'):'commerce_bump_case_revision',
    ('commerce_cases','commerce_case_request'):'commerce_guard_case_request',
    ('resolutions','commerce_compensation_limit'):'commerce_guard_compensation',
    ('commerce_provider_calls','commerce_provider_binding'):'commerce_guard_provider_request',
    ('commerce_adaptive_runs','commerce_adaptive_binding'):'commerce_guard_adaptive_run',
    ('commerce_adaptive_tool_counts','commerce_adaptive_counter'):'commerce_guard_adaptive_counter',
    ('commerce_adaptive_calls','commerce_adaptive_call_binding'):'commerce_guard_adaptive_call',
    ('commerce_adaptive_sessions','commerce_session_binding'):'commerce_guard_session',
}
for table in ('commerce_investigations','commerce_proposals','commerce_reviews','commerce_case_events',
              'commerce_operations','commerce_replacement_orders','commerce_replacement_lines',
              'commerce_reservations','policy_versions','resolutions','commerce_provider_budgets',
              'commerce_adaptive_steps','commerce_adaptive_observations','commerce_adaptive_supersessions',
              'commerce_adaptive_call_events','commerce_adaptive_session_events'):
    GUARDS[(table,'commerce_immutable')]='commerce_reject_audit_mutation'

def expected_type(column):
    t=column.type
    for cls,name in ((sa.BigInteger,'int8'),(sa.Integer,'int4'),(sa.Boolean,'bool'),
                     (sa.DateTime,'timestamptz'),(sa.Numeric,'numeric'),(sa.String,'varchar')):
        if isinstance(t,cls):return name
    if str(t)=='JSONB':return 'jsonb'
    raise SchemaNotReady('Unspecified source column type')

def validate_readiness(connection):
    try:
        versions=connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalars().all()
        if versions!=[SUPPORTED_REVISION]:raise SchemaNotReady('Unsupported business schema revision')
        rows=connection.exec_driver_sql('''SELECT table_name,column_name,udt_name,is_nullable,
            character_maximum_length,numeric_precision,numeric_scale
            FROM information_schema.columns WHERE table_schema=current_schema()''').mappings()
        actual={(r['table_name'],r['column_name']):r for r in rows}
        for table in metadata.tables.values():
            for column in table.columns:
                row=actual.get((table.name,column.name));kind=expected_type(column)
                compatible=row is not None and (row['udt_name']==kind or kind=='varchar' and column.type.length is None and row['udt_name']=='text')
                if not compatible or (row['is_nullable']=='YES')!=column.nullable:
                    raise SchemaNotReady(f'Required column {table.name}.{column.name} missing or incompatible: {row}, expected {kind}/{column.nullable}')
                if kind=='varchar' and row['character_maximum_length']!=column.type.length:
                    raise SchemaNotReady('Required string bound incompatible')
                if kind=='numeric' and (row['numeric_precision'],row['numeric_scale'])!=(column.type.precision,column.type.scale):
                    raise SchemaNotReady('Required decimal shape incompatible')
        guards=connection.exec_driver_sql('''SELECT c.relname,t.tgname,p.proname,t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid
            WHERE n.nspname=current_schema() AND NOT t.tgisinternal''').all()
        enabled={(table,name):function for table,name,function,state in guards if state in ('O','A')}
        if any(enabled.get(key)!=function for key,function in GUARDS.items()):
            raise SchemaNotReady('Required mutation guard missing or disabled: '+repr([key for key,function in GUARDS.items() if enabled.get(key)!=function]))
    except SQLAlchemyError as error:
        raise SchemaNotReady('Business schema unavailable') from error
