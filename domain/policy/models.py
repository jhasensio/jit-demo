"""Domain models for AVI Policy Configuration."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, func

from infrastructure.database import Base


class PolicyMapping(Base):
    """Persisted mapping: target_app ↔ VirtualService ↔ NetworkSecurityPolicy."""

    __tablename__ = "policy_mappings"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    target_app       = Column(String, nullable=False)
    vs_name          = Column(String, nullable=False)
    vs_uuid          = Column(String, nullable=False)
    policy_name      = Column(String, nullable=False)
    policy_uuid      = Column(String, nullable=False)
    ipaddrgroup_name = Column(String, nullable=True)
    ipaddrgroup_ref  = Column(String, nullable=True)
    created_at       = Column(DateTime, server_default=func.now())


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class PolicyMappingCreate(BaseModel):
    target_app:       str
    vs_name:          str
    vs_uuid:          str
    policy_name:      str
    policy_uuid:      str
    ipaddrgroup_name: Optional[str] = None
    ipaddrgroup_ref:  Optional[str] = None


class PolicyMappingResponse(PolicyMappingCreate):
    id:         int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
