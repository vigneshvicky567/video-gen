from sqlmodel import Field, SQLModel, create_engine, Session, JSON
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import sqlalchemy as sa

DATABASE_URL = "postgresql+asyncpg://user:password@db:5432/manim_db"
engine = create_async_engine(DATABASE_URL, echo=True, future=True)

class PipelineJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    prompt: str
    status: str = Field(default="processing")
    scenes: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=sa.Column(sa.JSON))
    global_errors: Optional[List[str]] = Field(default=None, sa_column=sa.Column(sa.JSON))
    final_video_path: Optional[str] = None

async def init_db():
    async with engine.begin() as conn:
        # Create all tables
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
