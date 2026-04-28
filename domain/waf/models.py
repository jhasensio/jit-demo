from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class WAFWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Accepts: client_ip, src_ip, source_ip, clientIP — whichever Log Insight sends
    client_ip: str = Field(
        ...,
        validation_alias=AliasChoices("client_ip", "src_ip", "source_ip", "clientIP"),
    )
    target_app: str | None = None
    rule_id: str | None = None
    attack_type: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    virtual_service: str | None = None
    original_timestamp: str | None = None
    event_id: str | None = None
    alert_name: str | None = None
    raw: dict | None = None


class WAFRevokeResult(BaseModel):
    revoked: int
    sessions: list[str]
    details: list[dict]
