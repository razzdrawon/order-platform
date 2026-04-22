from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# The engine manages the connection pool to PostgreSQL.
# echo=False in production — set to True temporarily if you want to see SQL queries.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

# Session factory — call this to get a new session for each request.
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # don't expire objects after commit — avoids lazy load errors
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass
