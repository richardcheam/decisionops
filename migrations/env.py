"""Environment URL, avoiding credentials committed in alembic.ini."""

from alembic import context
from decisionops.commerce.database import database_engine
from decisionops.commerce.schema import metadata

def run(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = database_engine()
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
