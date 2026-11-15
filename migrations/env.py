"""Alembic configuration; connection credentials are read only from environment."""

from alembic import context

from app.memory.config import MemorySettings
from app.memory.database import Database, metadata

url = MemorySettings().database_url.get_secret_value()
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    database = Database(url)
    with database.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    database.close()
