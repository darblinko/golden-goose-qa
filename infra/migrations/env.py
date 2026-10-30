"""Alembic environment. Migrations run as the admin role (owns schemas and the
audit table); the runtime gg_app role receives only the grants defined in the
migrations themselves."""

from alembic import context
from gg_common.settings import get_settings, require_admin_credentials
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = None


def _database_url() -> str:
    return require_admin_credentials(get_settings())


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
