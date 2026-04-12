from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from shared.config import settings

# Since PostgreSQL is requested, but for tests aiosqlite is used.
# If SQLALCHEMY_DATABASE_URL is not provided, fallback to an sqlite for testing
engine = create_async_engine(settings.DATABASE_URL, echo=False)

async_session_maker = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
