from typing import Optional

from domain.connections.models import AVICredentials, NSXCredentials


class CredentialStore:
    """In-memory singleton holding current NSX and AVI credentials + test status."""

    def __init__(self) -> None:
        self._nsx: Optional[NSXCredentials] = None
        self._avi: Optional[AVICredentials] = None
        self._nsx_status: str = "unconfigured"   # "ok" | "error" | "unconfigured"
        self._avi_status: str = "unconfigured"

    # ── NSX ──────────────────────────────────────────────────────────────────
    def set_nsx(self, creds: NSXCredentials) -> None:
        self._nsx = creds

    def get_nsx(self) -> Optional[NSXCredentials]:
        return self._nsx

    def set_nsx_status(self, status: str) -> None:
        self._nsx_status = status

    def get_nsx_status(self) -> str:
        return self._nsx_status if self._nsx else "unconfigured"

    # ── AVI ──────────────────────────────────────────────────────────────────
    def set_avi(self, creds: AVICredentials) -> None:
        self._avi = creds

    def get_avi(self) -> Optional[AVICredentials]:
        return self._avi

    def set_avi_status(self, status: str) -> None:
        self._avi_status = status

    def get_avi_status(self) -> str:
        return self._avi_status if self._avi else "unconfigured"


# Module-level singleton — imported everywhere
credential_store = CredentialStore()
