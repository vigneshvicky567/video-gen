from typing import Optional, Dict
from sqlmodel import SQLModel, Field, JSON, Column
from sqlalchemy import String

class JobRecord(SQLModel, table=True):
    job_id: str = Field(default=None, primary_key=True)
    topic: str
    status: str = "pending"
    # We serialize the state as JSON
    state: Optional[Dict] = Field(default={}, sa_column=Column(JSON))
    overall_error: Optional[str] = None
