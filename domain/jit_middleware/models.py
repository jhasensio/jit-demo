from typing import Literal

from pydantic import BaseModel


class DirectJITRequest(BaseModel):
    """Simplified payload for direct external calls to the L7 APIM API."""

    username: str = "jsmith"
    source_ip: str = "127.0.0.1"   # overridden server-side from request.client.host
    target_app: str
    action: Literal["LOGIN", "LOGOUT"]
    destination_ip: str = "192.168.10.100"
    device_name: str = "linux-db-prod-01"
    port: str = "22"
    access_protocol: str = "SSH"


class JITRequest(BaseModel):
    source: str
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


class EnforcementPayload(BaseModel):
    system: str
    method: str
    url: str
    payload: dict
