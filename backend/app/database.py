"""
Database configuration and session management.

Sets up async SQLAlchemy engine, session maker, and base model class.
Provides dependency injection for database sessions in FastAPI endpoints.

Author: AI Textbook Generator Team
Date: 2026-04-26
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


# ==================== Database Engine Configuration ====================

# Create async engine
# - echo=True in development for SQL query logging
# - poolclass=NullPool prevents connection pool issues in async context
engine = create_async_engine(
    settings.DATABASE_URL.replace("mysql+pymysql", "mysql+aiomysql"),
    echo=settings.ENVIRONMENT == "development",
    poolclass=NullPool,
)

# Create async session maker
# - expire_on_commit=False prevents issues with accessing model attributes
#   after commit in async context
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ==================== Base Model Class ====================

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    All models should inherit from this class to be included
    in the metadata and migration system.
    
    Example:
        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
    """
    pass


# ==================== Database Session Dependency ====================

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.
    
    Creates a new async session for each request and ensures
    proper cleanup after the request completes.
    
    Usage in FastAPI endpoints:
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    
    Yields:
        AsyncSession: Active database session
        
    Raises:
        Exception: If database connection fails
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise
        finally:
            await session.close()


# ==================== Database Utilities ====================

async def init_db() -> None:
    """
    Initialize database tables.
    
    Creates all tables defined in Base.metadata if they don't exist.
    This is called during application startup in main.py lifespan.
    
    Note:
        In production, use Alembic migrations instead of create_all.
        This function is primarily for development and testing.
    """
    async with engine.begin() as conn:
        # Import all models here to ensure they're registered
        # before create_all is called
        from app.models import user, payment, textbook  # noqa: F401
        
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """
    Drop all database tables.
    
    WARNING: This will delete all data! Use only in development/testing.
    
    Usage:
        # In tests
        await drop_db()
        await init_db()  # Fresh database
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ==================== Database Health Check ====================

async def check_db_connection() -> bool:
    """
    Check if database connection is healthy.
    
    Returns:
        bool: True if connection successful, False otherwise
        
    Example:
        healthy = await check_db_connection()
        if not healthy:
            raise Exception("Database connection failed")
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute("SELECT 1") #type: ignore
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False