import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Alembic Config object — provides access to values within alembic.ini
config = context.config

# Interpret the config file for Python logging, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from the DATABASE_URL environment variable so that
# alembic upgrade head works in CI and production without editing alembic.ini.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# No SQLAlchemy metadata object — all DDL is written as raw SQL in the
# migration file itself (offline/online raw SQL approach).
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL, not an Engine.  Calls to
    context.execute() emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
