"""
AVI Load Balancer client.

Uses the official avisdk (pip install avisdk) wrapped in asyncio.to_thread()
so that synchronous SDK I/O never blocks the event loop.

Falls back to a clear error message if avisdk is not installed — the rest
of the application continues to work (payload preview, event stream, etc.).
"""
import asyncio
import urllib.parse

from domain.connections.models import AVICredentials

try:
    from avi.sdk.avi_api import ApiSession  # type: ignore[import]
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False

_INSTALL_MSG = (
    "avisdk is not installed. "
    "Run:  pip install avisdk  (then restart the server)"
)


class AVIClient:
    def __init__(self, creds: AVICredentials) -> None:
        self._creds = creds

    def _host(self) -> str:
        """Strip scheme — avisdk expects bare hostname or IP."""
        h = self._creds.host
        for pfx in ("https://", "http://"):
            if h.startswith(pfx):
                h = h[len(pfx):]
        return h.rstrip("/")

    def _session(self) -> "ApiSession":
        return ApiSession.get_session(
            self._host(),
            self._creds.username,
            self._creds.password,
            tenant=self._creds.tenant,
            verify=self._creds.verify_ssl,
        )

    # ── async public interface ────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Returns {"success", "version", "error"}"""
        if not _HAS_SDK:
            return {"success": False, "version": None, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_test)

    async def put_ipaddrgroup(self, original_url: str, payload: dict) -> dict:
        """
        Create-or-update an AVI IP Address Group (upsert).

        Given a URL like https://avi.lab/api/ipaddrgroup?name=JIT_APP_Allowed:
          1. GET by name — if found, PUT /api/ipaddrgroup/{uuid} with payload
          2. If not found, POST /api/ipaddrgroup to provision the group first
        Returns {"success", "status_code", "body", "error", "provisioned"}
          provisioned=True  → group did not exist and was created
          provisioned=False → group already existed and was updated
        """
        if not _HAS_SDK:
            return {"success": False, "status_code": None, "body": {}, "error": _INSTALL_MSG,
                    "provisioned": False}

        qs = urllib.parse.parse_qs(urllib.parse.urlparse(original_url).query)
        name_list = qs.get("name", [])
        if not name_list:
            return {
                "success": False,
                "status_code": None,
                "body": {},
                "error": f"Could not extract group name from URL: {original_url}",
                "provisioned": False,
            }
        group_name = name_list[0]
        return await asyncio.to_thread(self._sync_put, group_name, payload)

    # ── sync helpers (run in thread pool) ────────────────────────────────────

    def _sync_test(self) -> dict:
        try:
            session = self._session()
            r = session.get("cluster/runtime")
            if r.status_code == 200:
                body = r.json()
                version = None
                try:
                    version = body["node_states"][0]["node_info"]["version"]
                except (KeyError, IndexError, TypeError):
                    pass
                return {"success": True, "version": version, "error": None}
            return {
                "success": False,
                "version": None,
                "error": f"HTTP {r.status_code}: {r.text[:200]}",
            }
        except Exception as exc:
            return {"success": False, "version": None, "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_put(self, group_name: str, payload: dict) -> dict:
        try:
            session = self._session()

            # Extract operation hints before cleaning the payload
            new_addrs   = payload.get("addrs", [])          # IPs to add (LOGIN)
            remove_addr = payload.get("remove_addr")         # IP to remove (LOGOUT)
            # Strip internal hint — never sent to AVI
            clean = {k: v for k, v in payload.items() if k != "remove_addr"}

            # Step 1 — GET by name to check existence and fetch current state
            get_r = session.get("ipaddrgroup", params={"name": group_name})
            if get_r.status_code != 200:
                return {
                    "success": False,
                    "status_code": get_r.status_code,
                    "body": {},
                    "error": f"GET ipaddrgroup?name={group_name} → HTTP {get_r.status_code}",
                    "provisioned": False,
                }

            results = get_r.json().get("results", [])

            if results:
                # Group exists — merge or surgically remove
                uuid           = results[0]["uuid"]
                existing_addrs = results[0].get("addrs") or []

                if remove_addr:
                    # LOGOUT: remove only the specific IP, leave all others intact
                    merged = [a for a in existing_addrs if a.get("addr") != remove_addr]
                else:
                    # LOGIN: add new IPs that are not already present (deduplicate)
                    existing_ips = {a.get("addr") for a in existing_addrs}
                    to_add       = [a for a in new_addrs if a.get("addr") not in existing_ips]
                    merged       = existing_addrs + to_add

                clean["addrs"] = merged
                resp           = session.put(f"ipaddrgroup/{uuid}", data=clean)
                provisioned    = False
            else:
                # Group absent — POST to provision it
                # LOGOUT on a non-existent group: create empty (nothing to remove)
                if remove_addr:
                    clean["addrs"] = []
                resp        = session.post("ipaddrgroup", data=clean)
                provisioned = True

            success = resp.status_code in (200, 201)
            body: dict = {}
            try:
                body = resp.json()
            except Exception:
                pass
            return {
                "success": success,
                "status_code": resp.status_code,
                "body": body,
                "error": None if success else resp.text[:300],
                "provisioned": provisioned,
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc),
                    "provisioned": False}
        finally:
            self._clear_sessions()

    def _clear_sessions(self) -> None:
        """Flush avisdk's global session cache to prevent stale-token reuse."""
        try:
            ApiSession.clear_cached_sessions()
        except Exception:
            pass
