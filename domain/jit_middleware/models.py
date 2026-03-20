import re
from typing import Literal

from pydantic import BaseModel, field_validator


class DirectJITRequest(BaseModel):
    """Simplified payload for direct external calls to the JIT Middleware API."""

    username: str
    source_ip: str
    target_app: str
    action: Literal["LOGIN", "LOGOUT"]

    @field_validator("source_ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", v):
            raise ValueError("source_ip must be a valid IPv4 address")
        return v


class JITRequest(BaseModel):
    source: str
    event_type: str
    username: str
    source_ip: str
    target_app: str
    action: str
    original_timestamp: str


class EnforcementPayload(BaseModel):
    system: str
    method: str
    url: str
    payload: dict
