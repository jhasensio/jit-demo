from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel


class Session(BaseModel):
    session_id: str
    username: str
    source_ip: str
    target_app: str
    login_timestamp: datetime
    last_checked: Optional[datetime] = None
    status: Literal["active", "expired", "revoked", "logged_out"] = "active"
    enforcement_payloads: list[dict] = []
    source: str = "webhook"   # "webhook" | "direct-api" | "demo" | "live-enforce"

    @property
    def session_key(self) -> str:
        return f"{self.username}:{self.target_app}:{self.source_ip}"

    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.login_timestamp).total_seconds()


class SessionSettings(BaseModel):
    ttl_seconds: int = 300
    poll_interval_seconds: int = 30
    mode: Literal["ttl_only", "polling_only", "both"] = "both"
    auto_enforce: bool = False


class SessionSummary(BaseModel):
    session_id: str
    username: str
    source_ip: str
    target_app: str
    status: str
    elapsed_seconds: float
    login_timestamp: str
    source: str
