from typing import Literal

from pydantic import BaseModel, ConfigDict


class WAFWebhookPayload(BaseModel):
    """
    Log Insight webhook payload from an AVI WAF alert.

    Field names match Log Insight's default template output directly — no aliases
    needed. Extra keys (custom Log Insight fields) are preserved via extra="allow".
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Required: the offending source IP (Log Insight field name)
    source_ip: str

    # Standard Log Insight alert fields
    alert_name: str | None = None
    description: str | None = None
    timestamp: str | None = None      # Log Insight event timestamp
    all_tags: str | None = None
    custom_fields_block: str | None = None

    # Optional context — populate via Log Insight template or other WAF sources
    target_app: str | None = None     # narrow revocation to one app
    rule_id: str | None = None        # WAF rule ID, e.g. CRS-942100
    attack_type: str | None = None    # human label: SQLi, XSS, RCE
    severity: Literal["low", "medium", "high", "critical"] | None = None
    virtual_service: str | None = None
    event_id: str | None = None


class WAFRevokeResult(BaseModel):
    revoked: int
    sessions: list[str]
    details: list[dict]
