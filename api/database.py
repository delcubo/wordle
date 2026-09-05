"""
Подключение к БД. Используем async SQLAlchemy — и API, и бот (через shared session
factory) обращаются к одной и той же базе.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/wordle",
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    """FastAPI dependency — выдаёт сессию на время запроса."""
    async with async_session_factory() as session:
        yield session
