from pydantic import BaseModel, field_validator


class NSXCredentials(BaseModel):
    host: str
    username: str
    password: str
    verify_ssl: bool = False

    @field_validator("host")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip().rstrip("/")


class AVICredentials(BaseModel):
    host: str
    username: str
    password: str
    tenant: str = "admin"
    verify_ssl: bool = False

    @field_validator("host")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip().rstrip("/")


class ConnectionStatus(BaseModel):
    nsx: str              # "ok" | "error" | "unconfigured"
    avi: str
    nsx_host: str | None = None
    avi_host: str | None = None
