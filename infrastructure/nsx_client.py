"""NSX 4.2.2 Policy API async client (httpx)."""
from urllib.parse import urlparse

import httpx

from domain.connections.models import NSXCredentials


class NSXClient:
    def __init__(self, creds: NSXCredentials) -> None:
        self._creds = creds

    def _base(self) -> str:
        h = self._creds.host
        if not h.startswith("http"):
            h = f"https://{h}"
        return h.rstrip("/")

    def _mk_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=(self._creds.username, self._creds.password),
            verify=self._creds.verify_ssl,
            timeout=15.0,
        )

    async def test_connection(self) -> dict:
        """GET /api/v1/node → {"success", "version", "node_type", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(f"{self._base()}/api/v1/node")
            if r.status_code == 200:
                body = r.json()
                return {
                    "success": True,
                    "version": body.get("product_version"),
                    "node_type": body.get("node_type"),
                    "error": None,
                }
            return {
                "success": False,
                "version": None,
                "node_type": None,
                "error": f"HTTP {r.status_code}: {r.text[:200]}",
            }
        except Exception as exc:
            return {"success": False, "version": None, "node_type": None, "error": str(exc)}

    async def patch_policy_group(self, original_url: str, payload: dict) -> dict:
        """
        Rewrite the host in original_url to the configured one, then
        PATCH the NSX Policy group.
        Returns {"success", "status_code", "body", "error"}.
        """
        path = urlparse(original_url).path
        url = f"{self._base()}{path}"
        try:
            async with self._mk_client() as c:
                r = await c.patch(url, json=payload)
            success = r.status_code in (200, 201)
            body = {}
            try:
                body = r.json()
            except Exception:
                pass
            return {
                "success": success,
                "status_code": r.status_code,
                "body": body,
                "error": None if success else r.text[:300],
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc)}
