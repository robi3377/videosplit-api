from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
import os

# Read database URL from .env file
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://videosplit:AlaBalaPortoCala@localhost:5432/videosplit"
)

# Create the async database engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,              # Set to True to see SQL queries in console
    pool_pre_ping=True,      # Check connection is alive before using
    pool_size=10,            # Keep 10 connections open
    max_overflow=20          # Allow up to 20 extra connections if busy
)

# Create session factory (makes database sessions)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Base class for all database models
class Base(DeclarativeBase):
    pass

# Dependency for FastAPI routes - provides database access
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()