from typing import Literal

from pydantic import BaseModel


class ParsedEvent(BaseModel):
    timestamp: str
    event_type: str
    username: str
    source_ip: str
    target_app: str
    action: str


class WebhookPayload(BaseModel):
    source: str = "aria-siem"
    event_type: str
    username: str
    source_ip: str
    target_app: str
    action: str
    original_timestamp: str
