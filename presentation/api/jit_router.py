from datetime import datetime, timezone

from fastapi import APIRouter

from core.logger import event_bus
from domain.aria.models import WebhookPayload
from domain.jit_middleware.models import DirectJITRequest, JITRequest
from domain.jit_middleware.service import JITService
from infrastructure.avi_client import AVIClient
from infrastructure.credential_store import credential_store
from infrastructure.nsx_client import NSXClient

router = APIRouter(prefix="/jit", tags=["JIT Middleware"])


@router.post("/webhook")
async def jit_webhook(payload: WebhookPayload) -> dict:
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "JIT",
            "message": f"Webhook received from Aria SIEM: {payload.action} for {payload.username}@{payload.target_app}",
            "payload": payload.model_dump(),
        }
    )

    req = JITRequest(
        source=payload.source,
        event_type=payload.event_type,
        username=payload.username,
        source_ip=payload.source_ip,
        target_app=payload.target_app,
        action=payload.action,
        original_timestamp=payload.original_timestamp,
    )

    enforcements = JITService.generate_enforcements(req)

    labels = ["[1/3] NSX GFW", "[2/3] NSX DFW", "[3/3] AVI LB"]
    for label, enforcement in zip(labels, enforcements):
        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "JIT",
                "message": f"{label} — {enforcement.method} {enforcement.system}",
                "payload": enforcement.model_dump(),
            }
        )

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "JIT",
            "message": f"SUCCESS: 3 enforcement payloads dispatched for {payload.username} ({payload.action})",
            "payload": None,
        }
    )

    return {"status": "enforced", "count": len(enforcements), "action": payload.action}


@router.post("/direct")
async def jit_direct(req: DirectJITRequest) -> dict:
    """Direct external call to the JIT Middleware — bypasses IDSP/Aria pipeline."""
    ts = datetime.now(timezone.utc).isoformat()

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "JIT",
            "message": f"Direct API call: {req.action} for {req.username}@{req.target_app} from {req.source_ip}",
            "payload": req.model_dump(),
        }
    )

    jit_req = JITRequest(
        source="direct-api",
        event_type="Direct API Call",
        username=req.username,
        source_ip=req.source_ip,
        target_app=req.target_app,
        action=req.action,
        original_timestamp=ts,
    )

    enforcements = JITService.generate_enforcements(jit_req)

    labels = ["[1/3] NSX GFW", "[2/3] NSX DFW", "[3/3] AVI LB"]
    for label, enforcement in zip(labels, enforcements):
        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "JIT",
                "message": f"{label} — {enforcement.method} {enforcement.system}",
                "payload": enforcement.model_dump(),
            }
        )

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "JIT",
            "message": f"SUCCESS: 3 enforcement payloads generated for {req.username} ({req.action})",
            "payload": None,
        }
    )

    return {
        "status": "enforced",
        "request": req.model_dump(),
        "enforcements": [e.model_dump() for e in enforcements],
    }


@router.post("/enforce")
async def jit_enforce(req: DirectJITRequest) -> dict:
    """Generate enforcements and submit them to live NSX/AVI infrastructure."""
    ts = datetime.now(timezone.utc).isoformat()

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "JIT",
            "message": (
                f"ENFORCE: {req.action} for {req.username}@{req.target_app}"
                f" from {req.source_ip}"
            ),
            "payload": req.model_dump(),
        }
    )

    jit_req = JITRequest(
        source="live-enforce",
        event_type="Live Enforcement",
        username=req.username,
        source_ip=req.source_ip,
        target_app=req.target_app,
        action=req.action,
        original_timestamp=ts,
    )
    enforcements = JITService.generate_enforcements(jit_req)

    nsx_creds = credential_store.get_nsx()
    avi_creds = credential_store.get_avi()

    results = []
    labels = ["[1/3] NSX GFW", "[2/3] NSX DFW", "[3/3] AVI LB"]

    for label, enforcement in zip(labels, enforcements):
        # Publish what we're about to send
        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "JIT",
                "message": f"{label} — {enforcement.method} {enforcement.system}",
                "payload": enforcement.model_dump(),
            }
        )

        if enforcement.system in ("NSX Gateway Firewall", "NSX Distributed Firewall"):
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

    all_ok = all(r.get("success") for r in results)
    ok_count = sum(1 for r in results if r.get("success"))

    await event_bus.publish(
        {
            "level": "SUCCESS" if all_ok else "ERROR",
            "domain": "JIT",
            "message": (
                f"ENFORCE COMPLETE: {ok_count}/{len(results)} succeeded"
                f" for {req.username} ({req.action})"
            ),
            "payload": None,
        }
    )

    return {
        "status": "ok" if all_ok else "partial",
        "action": req.action,
        "username": req.username,
        "results": results,
    }
