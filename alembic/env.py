from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
import asyncio
import os
import sys

# Add parent directory to Python path
# This allows us to import from app/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Import Base and all models
# This is CRITICAL - Alembic needs to see all models to create tables
from app.saas_layer.db.base import Base
from app.saas_layer.db.models import User, OAuthAccount, APIKey, UsageLog, Job

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for migrations
# This tells Alembic which tables to create
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This generates migration files without connecting to database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    """
    Run migrations with an existing database connection.
    """
    context.configure(
        connection=connection, 
        target_metadata=target_metadata
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode (async).
    
    This actually connects to the database and applies changes.
    Uses async engine for non-blocking operations.
    """
    # Get configuration section
    configuration = config.get_section(config.config_ini_section)
    
    # Override database URL from environment variable
    # This is KEY - uses DATABASE_URL from .env instead of alembic.ini
    configuration["sqlalchemy.url"] = os.getenv(
        "DATABASE_URL",
        configuration["sqlalchemy.url"]
    )
    
    # Create async engine
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Connect and run migrations
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    Called when you run: alembic upgrade head
    """
    asyncio.run(run_async_migrations())


# Determine mode and run
if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        run_migrations_online()
    except Exception as e:
        # If database connection fails, fallback to offline mode
        print(f"⚠️  Could not connect to database: {e}")
        print("📝 Generating migration in offline mode (no database needed)...")
        run_migrations_offline()