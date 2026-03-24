from typing import Literal

from pydantic import BaseModel


class ParsedEvent(BaseModel):
    timestamp: str
    event_type: str
    username: str
    source_ip: str
    target_app: str
    action: str
    destination_ip: str = ""
    device_name: str = ""
    port: str = ""
    access_protocol: str = ""


class WebhookPayload(BaseModel):
    source: str = "aria-siem"
    event_type: str
    username: str
    source_ip: str
    target_app: str
    action: str
    original_timestamp: str
    destination_ip: str = ""
    device_name: str = ""
    port: str = ""
    access_protocol: str = ""
