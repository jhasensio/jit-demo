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
            tenant="admin",
            api_version=self._creds.avi_version,
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
            # Connect WITHOUT X-Avi-Version so the controller always accepts the
            # request and returns its own real version.  The configured api_version
            # is only used for subsequent data-plane API calls via _session().
            session = ApiSession.get_session(
                self._host(),
                self._creds.username,
                self._creds.password,
                tenant="admin",
                verify=self._creds.verify_ssl,
            )
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

    # ── Network Security Policy methods ───────────────────────────────────────

    async def list_networksecuritypolicies(self) -> dict:
        """GET api/networksecuritypolicy — returns {"success", "results", "error"}."""
        if not _HAS_SDK:
            return {"success": False, "results": [], "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_list_nsp)

    async def create_networksecuritypolicy(self, name: str, ipaddrgroup_ref: str) -> dict:
        """POST a new NetworkSecurityPolicy with allow-whitelist + deny-cleanup rules."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_create_nsp, name, ipaddrgroup_ref)

    async def create_networksecuritypolicy_advanced(self, name: str, rules: list) -> dict:
        """POST a new NetworkSecurityPolicy with a caller-supplied rules array."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_create_nsp_advanced, name, rules)

    async def list_virtualservices(self) -> dict:
        """GET api/virtualservice — returns {"success", "results", "error"}."""
        if not _HAS_SDK:
            return {"success": False, "results": [], "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_list_vs)

    async def attach_policy_to_vs(self, vs_uuid: str, policy_ref: str) -> dict:
        """GET VS by uuid, then PUT with network_security_policy_ref set."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_attach_policy, vs_uuid, policy_ref)

    async def list_ipaddrgroups(self) -> dict:
        """GET api/ipaddrgroup — returns {"success", "results", "error"}."""
        if not _HAS_SDK:
            return {"success": False, "results": [], "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_list_ipgroups)

    # ── sync helpers for new methods ──────────────────────────────────────────

    def _sync_list_nsp(self) -> dict:
        try:
            session = self._session()
            r = session.get("networksecuritypolicy")
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_create_nsp(self, name: str, ipaddrgroup_ref: str) -> dict:
        payload = {
            "name": name,
            "rules": [
                {
                    "name": "authorized_users_ip_whitelist",
                    "action": "NETWORK_SECURITY_POLICY_ACTION_TYPE_ALLOW",
                    "enable": True,
                    "index": 0,
                    "log": True,
                    "match": {
                        "client_ip": {
                            "group_refs": [ipaddrgroup_ref],
                            "match_criteria": "IS_IN",
                        }
                    },
                },
                {
                    "name": "cleanup-rule",
                    "action": "NETWORK_SECURITY_POLICY_ACTION_TYPE_DENY",
                    "enable": True,
                    "index": 1,
                    "log": True,
                    "match": {
                        "client_ip": {
                            "match_criteria": "IS_IN",
                            "prefixes": [
                                {"ip_addr": {"addr": "0.0.0.0", "type": "V4"}, "mask": 0}
                            ],
                        }
                    },
                },
            ],
        }
        try:
            session = self._session()
            r = session.post("networksecuritypolicy", data=payload)
            success = r.status_code in (200, 201)
            body: dict = {}
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
        finally:
            self._clear_sessions()

    def _sync_create_nsp_advanced(self, name: str, rules: list) -> dict:
        payload = {"name": name, "rules": rules}
        try:
            session = self._session()
            r = session.post("networksecuritypolicy", data=payload)
            success = r.status_code in (200, 201)
            body: dict = {}
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
        finally:
            self._clear_sessions()

    def _sync_list_vs(self) -> dict:
        try:
            session = self._session()
            r = session.get("virtualservice")
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_attach_policy(self, vs_uuid: str, policy_ref: str) -> dict:
        try:
            session = self._session()
            # GET current VS state
            get_r = session.get(f"virtualservice/{vs_uuid}")
            if get_r.status_code != 200:
                return {
                    "success": False,
                    "body": {},
                    "error": f"GET virtualservice/{vs_uuid} → HTTP {get_r.status_code}",
                }
            vs_data = get_r.json()
            vs_data["network_security_policy_ref"] = policy_ref
            put_r = session.put(f"virtualservice/{vs_uuid}", data=vs_data)
            success = put_r.status_code in (200, 201)
            body: dict = {}
            try:
                body = put_r.json()
            except Exception:
                pass
            return {
                "success": success,
                "status_code": put_r.status_code,
                "body": body,
                "error": None if success else put_r.text[:300],
            }
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_list_ipgroups(self) -> dict:
        try:
            session = self._session()
            r = session.get("ipaddrgroup")
            if r.status_code == 200:
                return {"success": True, "results": r.json().get("results", []), "error": None}
            return {"success": False, "results": [], "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "results": [], "error": str(exc)}
        finally:
            self._clear_sessions()

    # ── new helpers: get/update/delete NSP + create ipgroup ──────────────────

    def _sync_get_nsp(self, uuid: str) -> dict:
        try:
            session = self._session()
            r = session.get(f"networksecuritypolicy/{uuid}")
            if r.status_code == 200:
                return {"success": True, "result": r.json(), "error": None}
            return {"success": False, "result": {}, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "result": {}, "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_update_nsp(self, uuid: str, payload: dict) -> dict:
        try:
            session = self._session()
            r = session.put(f"networksecuritypolicy/{uuid}", data=payload)
            success = r.status_code in (200, 201)
            body: dict = {}
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
        finally:
            self._clear_sessions()

    def _sync_delete_nsp(self, uuid: str) -> dict:
        try:
            session = self._session()
            r = session.delete(f"networksecuritypolicy/{uuid}")
            success = r.status_code in (200, 204)
            return {"success": success, "error": None if success else f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_create_ipgroup(self, name: str, addrs: list) -> dict:
        payload: dict = {"name": name}
        filtered = [{"addr": ip.strip(), "type": "V4"} for ip in addrs if ip.strip()]
        if filtered:
            payload["addrs"] = filtered
        try:
            session = self._session()
            r = session.post("ipaddrgroup", data=payload)
            success = r.status_code in (200, 201)
            body: dict = {}
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
        finally:
            self._clear_sessions()

    async def get_networksecuritypolicy(self, uuid: str) -> dict:
        """GET api/networksecuritypolicy/{uuid} — returns full NSP object with rules."""
        if not _HAS_SDK:
            return {"success": False, "result": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_get_nsp, uuid)

    async def update_networksecuritypolicy(self, uuid: str, payload: dict) -> dict:
        """PUT api/networksecuritypolicy/{uuid} — full read-modify-write update."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_update_nsp, uuid, payload)

    async def delete_networksecuritypolicy(self, uuid: str) -> dict:
        """DELETE api/networksecuritypolicy/{uuid}."""
        if not _HAS_SDK:
            return {"success": False, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_delete_nsp, uuid)

    async def create_ipaddrgroup(self, name: str, addrs: list) -> dict:
        """POST api/ipaddrgroup — create a new IP address group."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_create_ipgroup, name, addrs)

    async def delete_ipaddrgroup(self, uuid: str) -> dict:
        """DELETE api/ipaddrgroup/{uuid}."""
        if not _HAS_SDK:
            return {"success": False, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_delete_ipgroup, uuid)

    def _sync_delete_ipgroup(self, uuid: str) -> dict:
        try:
            session = self._session()
            r = session.delete(f"ipaddrgroup/{uuid}")
            success = r.status_code in (200, 204)
            return {"success": success, "error": None if success else f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        finally:
            self._clear_sessions()

    async def detach_policy_from_vs(self, vs_uuid: str) -> dict:
        """GET VS → remove network_security_policy_ref → PUT back."""
        if not _HAS_SDK:
            return {"success": False, "body": {}, "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_detach_policy, vs_uuid)

    async def get_nsp_referred_by(self, uuid: str) -> dict:
        """GET NSP with referred_by=virtualservice to discover attached VS objects."""
        if not _HAS_SDK:
            return {"success": False, "result": {}, "referred_by_vs": [], "error": _INSTALL_MSG}
        return await asyncio.to_thread(self._sync_get_nsp_referred_by, uuid)

    def _sync_detach_policy(self, vs_uuid: str) -> dict:
        try:
            session = self._session()
            get_r = session.get(f"virtualservice/{vs_uuid}")
            if get_r.status_code != 200:
                return {"success": False, "body": {}, "error": f"GET virtualservice/{vs_uuid} → HTTP {get_r.status_code}"}
            vs_data = get_r.json()
            vs_data.pop("network_security_policy_ref", None)
            put_r = session.put(f"virtualservice/{vs_uuid}", data=vs_data)
            success = put_r.status_code in (200, 201)
            body: dict = {}
            try:
                body = put_r.json()
            except Exception:
                pass
            return {"success": success, "status_code": put_r.status_code, "body": body,
                    "error": None if success else put_r.text[:300]}
        except Exception as exc:
            return {"success": False, "status_code": None, "body": {}, "error": str(exc)}
        finally:
            self._clear_sessions()

    def _sync_get_nsp_referred_by(self, uuid: str) -> dict:
        """Get NSP object and find VSes that reference it.

        AVI's `referred_by` query param is not reliably embedded in the response
        body for individual object GETs.  Instead we query virtualservice with
        a filter on network_security_policy_ref so AVI does the lookup for us.
        """
        try:
            session = self._session()

            # 1. Fetch the NSP object itself
            r_nsp = session.get(f"networksecuritypolicy/{uuid}")
            if r_nsp.status_code != 200:
                return {"success": False, "result": {}, "referred_by_vs": [],
                        "error": f"HTTP {r_nsp.status_code}: {r_nsp.text[:200]}"}
            nsp_data = r_nsp.json()

            # 2. Find VSes that have network_security_policy_ref pointing at this NSP.
            #    AVI accepts ?refers_to=networksecuritypolicy:<uuid> to filter VS list.
            r_vs = session.get(
                "virtualservice",
                params={"refers_to": f"networksecuritypolicy:{uuid}",
                        "fields": "name,uuid,url,network_security_policy_ref"},
            )
            vs_refs = []
            if r_vs.status_code == 200:
                vs_data = r_vs.json()
                for vs in vs_data.get("results", []):
                    vs_refs.append({
                        "url":  vs.get("url", ""),
                        "uuid": vs.get("uuid", ""),
                        "name": vs.get("name", vs.get("uuid", "")),
                    })

            return {"success": True, "result": nsp_data, "referred_by_vs": vs_refs, "error": None}
        except Exception as exc:
            return {"success": False, "result": {}, "referred_by_vs": [], "error": str(exc)}
        finally:
            self._clear_sessions()

    def _clear_sessions(self) -> None:
        """Flush avisdk's global session cache to prevent stale-token reuse."""
        try:
            ApiSession.clear_cached_sessions()
        except Exception:
            pass
