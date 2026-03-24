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
        GET the current group, merge/remove the IP surgically, and PATCH.

        LOGIN  — adds source IP to existing ip_addresses (deduplicates).
        LOGOUT — removes only the specific IP identified by remove_ip hint,
                 leaving all other IPs intact.

        Returns {"success", "status_code", "body", "error"}.
        """
        path = urlparse(original_url).path
        url = f"{self._base()}{path}"

        # Extract remove_ip hint and strip it from the outgoing payload
        merged_payload = {k: v for k, v in payload.items() if k != "expression"}
        expressions = payload.get("expression", [])

        remove_ip: str | None = None
        new_ips: list[str] = []
        clean_expressions = []
        for expr in expressions:
            if isinstance(expr, dict) and expr.get("resource_type") == "IPAddressExpression":
                remove_ip = expr.get("remove_ip")
                new_ips = [ip for ip in expr.get("ip_addresses", []) if ip]
                clean_expressions.append({k: v for k, v in expr.items() if k != "remove_ip"})
            else:
                clean_expressions.append(expr)

        try:
            async with self._mk_client() as c:
                # GET current group to read existing ip_addresses AND tags
                existing_ips: list[str] = []
                existing_tags: list[dict] = []
                get_r = await c.get(url)
                if get_r.status_code == 200:
                    try:
                        current = get_r.json()
                        for expr in current.get("expression", []):
                            if isinstance(expr, dict) and expr.get("resource_type") == "IPAddressExpression":
                                existing_ips = [ip for ip in expr.get("ip_addresses", []) if ip]
                                break
                        existing_tags = current.get("tags", [])
                    except Exception:
                        pass

                # Merge or remove
                if remove_ip:
                    # LOGOUT: remove only this IP
                    merged_ips = [ip for ip in existing_ips if ip != remove_ip]
                else:
                    # LOGIN: add new IPs, deduplicate
                    merged_ips = list(dict.fromkeys(existing_ips + new_ips))

                if merged_ips:
                    # Write merged list back into the expression
                    for expr in clean_expressions:
                        if isinstance(expr, dict) and expr.get("resource_type") == "IPAddressExpression":
                            expr["ip_addresses"] = merged_ips
                            break
                    merged_payload["expression"] = clean_expressions
                else:
                    # LOGOUT emptied the group — drop IPAddressExpression entirely.
                    # NSX rejects ip_addresses:[] (minimum size 1); an empty expression
                    # list is valid and leaves the group intact with no members.
                    merged_payload["expression"] = [
                        e for e in clean_expressions
                        if not (isinstance(e, dict) and e.get("resource_type") == "IPAddressExpression")
                    ]
                # Preserve existing tags so a PATCH never strips them
                if existing_tags:
                    merged_payload.setdefault("tags", existing_tags)

                r = await c.patch(url, json=merged_payload)

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

    async def create_group(
        self,
        group_id: str,
        display_name: str,
        ip_addresses: list[str],
        tags: list[dict] | None = None,
    ) -> dict:
        """PATCH .../groups/{group_id} — upsert an IPAddressExpression group (creates if absent)."""
        url = f"{self._base()}/policy/api/v1/infra/domains/default/groups/{group_id}"
        expression = (
            [{"resource_type": "IPAddressExpression", "ip_addresses": ip_addresses}]
            if ip_addresses else []
        )
        payload: dict = {
            "display_name": display_name,
            "expression": expression,
        }
        if tags:
            payload["tags"] = tags
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
                "error": None if success else r.text,
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc)}

    # ── Policy API read methods ───────────────────────────────────────────────

    async def list_groups(self) -> dict:
        """GET /policy/api/v1/infra/domains/default/groups → {"success", "results", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(
                    f"{self._base()}/policy/api/v1/infra/domains/default/groups",
                    params={"page_size": 1000},
                )
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}

    async def list_gateway_policies(self) -> dict:
        """GET /policy/api/v1/infra/domains/default/gateway-policies → {"success", "results", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(
                    f"{self._base()}/policy/api/v1/infra/domains/default/gateway-policies",
                    params={"page_size": 1000},
                )
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}

    async def get_gateway_policy(self, policy_id: str) -> dict:
        """GET .../gateway-policies/{policy_id} → {"success", "result", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(
                    f"{self._base()}/policy/api/v1/infra/domains/default/gateway-policies/{policy_id}"
                )
            if r.status_code == 200:
                return {"success": True, "result": r.json(), "error": None}
            return {"success": False, "result": None, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "result": None, "error": str(exc)}

    async def create_or_update_gateway_policy(self, policy_id: str, payload: dict) -> dict:
        """PATCH /{id} — NSX intent-based upsert (creates or updates, no prior object needed)."""
        url = f"{self._base()}/policy/api/v1/infra/domains/default/gateway-policies/{policy_id}"
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
                "error": None if success else r.text,
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc)}

    async def delete_gateway_policy(self, policy_id: str) -> dict:
        """DELETE .../gateway-policies/{policy_id}"""
        try:
            async with self._mk_client() as c:
                r = await c.delete(
                    f"{self._base()}/policy/api/v1/infra/domains/default/gateway-policies/{policy_id}"
                )
            success = r.status_code in (200, 204)
            return {
                "success": success,
                "status_code": r.status_code,
                "error": None if success else r.text[:300],
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "error": str(exc)}

    async def list_tier0s(self) -> dict:
        """GET /policy/api/v1/infra/tier-0s → {"success", "results", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(f"{self._base()}/policy/api/v1/infra/tier-0s")
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}

    async def list_tier1s(self) -> dict:
        """GET /policy/api/v1/infra/tier-1s → {"success", "results", "error"}"""
        try:
            async with self._mk_client() as c:
                r = await c.get(f"{self._base()}/policy/api/v1/infra/tier-1s")
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}
