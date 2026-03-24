from typing import Literal

from pydantic import BaseModel


class AuthRequest(BaseModel):
    username: str = "jsmith"
    source_ip: str = "127.0.0.1"   # overridden server-side if default is submitted
    target_app: str
    action: Literal["LOGIN", "LOGOUT"]
    destination_ip: str = "192.168.10.100"
    device_name: str = "linux-db-prod-01"
    port: str = "22"
    access_protocol: str = "SSH"
