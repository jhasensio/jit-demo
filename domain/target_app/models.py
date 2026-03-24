"""Domain models for Target Application definitions."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, func

from infrastructure.database import Base


class TargetApp(Base):
    """Persisted Target Application definition."""

    __tablename__ = "target_apps"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String, nullable=False, unique=True)   # e.g. "HR_APP_01"
    ip_address  = Column(String, nullable=False)                # e.g. "10.114.209.72"
    description = Column(String, nullable=True)
    created_at  = Column(DateTime, server_default=func.now())


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class TargetAppCreate(BaseModel):
    name:        str
    ip_address:  str
    description: Optional[str] = None


class TargetAppUpdate(BaseModel):
    name:        Optional[str] = None
    ip_address:  Optional[str] = None
    description: Optional[str] = None


class TargetAppResponse(BaseModel):
    id:          int
    name:        str
    ip_address:  str
    description: Optional[str] = None
    created_at:  Optional[datetime] = None

    model_config = {"from_attributes": True}
