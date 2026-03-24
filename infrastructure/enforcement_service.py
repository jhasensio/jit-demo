"""
Shared live enforcement logic.

Used by both POST /jit/enforce (interactive) and the session poller (auto-revocation).
"""
from datetime import datetime, timezone

from core.logger import event_bus
from domain.jit_middleware.models import JITRequest
from domain.jit_middleware.service import JITService
from infrastructure.avi_client import AVIClient
from infrastructure.credential_store import credential_store
from infrastructure.database import SessionLocal
from infrastructure.nsx_client import NSXClient
from infrastructure.policy_store import PolicyStore


async def execute_live_enforcement(
    username: str,
    source_ip: str,
    target_app: str,
    action: str,
    destination_ip: str = "",
    device_name: str = "",
    port: str = "",
    access_protocol: str = "",
    source: str = "auto-revoke",
) -> list[dict]:
    """
    Generate enforcement payloads and submit them to live NSX/AVI infrastructure
    (if connections are configured and healthy).

    Returns a list of result dicts, one per enforcement system.
    """
    ts = datetime.now(timezone.utc).isoformat()

    # Resolve the AVI IP address group name from the saved policy mapping.
    db = SessionLocal()
    try:
        mapping = PolicyStore(db).get_by_target_app(target_app)
        ipaddrgroup_name = (
            mapping.ipaddrgroup_name
            if mapping and mapping.ipaddrgroup_name
            else None
        )
    finally:
        db.close()

    jit_req = JITRequest(
        source=source,
        event_type="Auto-Revocation" if source == "auto-revoke" else "Live Enforcement",
        username=username,
        source_ip=source_ip,
        target_app=target_app,
        action=action,
        original_timestamp=ts,
        destination_ip=destination_ip,
        device_name=device_name,
        port=port,
        access_protocol=access_protocol,
    )
    nsx_creds = credential_store.get_nsx()
    avi_creds = credential_store.get_avi()
    enforcements = JITService.generate_enforcements(
        jit_req,
        ipaddrgroup_name=ipaddrgroup_name,
        nsx_host=nsx_creds.host if nsx_creds else None,
        avi_host=avi_creds.host if avi_creds else None,
    )

    results = []
    labels = ["[1/3] vDefend GFW", "[2/3] vDefend DFW", "[3/3] AVI LB"]

    for label, enforcement in zip(labels, enforcements):
        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "JIT",
                "message": f"{label} — {enforcement.method} {enforcement.system}",
                "payload": enforcement.model_dump(),
            }
        )

        if enforcement.system in ("vDefend Gateway Firewall", "vDefend Distributed Firewall"):
            if not nsx_creds or credential_store.get_nsx_status() != "ok":
                result: dict = {
                    "success": False,
                    "status_code": None,
                    "body": {},
                    "error": "NSX not connected — configure credentials in the Connections view",
                }
            else:
                await event_bus.publish(
                    {
                        "level": "INFO",
                        "domain": "CONNECTIONS",
                        "message": f"Submitting → NSX: {enforcement.method} {enforcement.url}",
                        "payload": None,
                    }
                )
                result = await NSXClient(nsx_creds).patch_policy_group(
                    enforcement.url, enforcement.payload
                )
        else:  # AVI Load Balancer
            if not avi_creds or credential_store.get_avi_status() != "ok":
                result = {
                    "success": False,
                    "status_code": None,
                    "body": {},
                    "error": "AVI not connected — configure credentials in the Connections view",
                }
            else:
                await event_bus.publish(
                    {
                        "level": "INFO",
                        "domain": "CONNECTIONS",
                        "message": f"Submitting → AVI: {enforcement.method} {enforcement.url}",
                        "payload": None,
                    }
                )
                result = await AVIClient(avi_creds).put_ipaddrgroup(
                    enforcement.url, enforcement.payload
                )

        level = "SUCCESS" if result.get("success") else "ERROR"
        if result.get("success"):
            verb = "provisioned" if result.get("provisioned") else "updated"
            msg = f"{enforcement.system} → {verb} (HTTP {result.get('status_code')})"
        else:
            msg = f"{enforcement.system} failed: {result.get('error', 'Unknown error')}"

        await event_bus.publish(
            {
                "level": level,
                "domain": "CONNECTIONS",
                "message": msg,
                "payload": result.get("body") or None,
            }
        )
        results.append({"system": enforcement.system, **result})

    return results
