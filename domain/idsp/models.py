import re
from typing import Literal

from pydantic import BaseModel, field_validator


class AuthRequest(BaseModel):
    username: str
    source_ip: str
    target_app: str
    action: Literal["LOGIN", "LOGOUT"]

    @field_validator("source_ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
        if not re.match(pattern, v):
            raise ValueError("source_ip must be a valid IPv4 address")
        return v
