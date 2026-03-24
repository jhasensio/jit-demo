from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request

from core.logger import event_bus
from domain.aria.models import WebhookPayload
from domain.jit_middleware.models import DirectJITRequest, JITRequest
from domain.jit_middleware.service import JITService
from domain.sessions.models import Session
from infrastructure.enforcement_service import execute_live_enforcement
from infrastructure.session_store import session_store

router = APIRouter(prefix="/jit", tags=["L7 APIM"])


def _register_session(req: JITRequest, enforcements: list, source: str) -> None:
    """Register or deregister a session based on action."""
    key = f"{req.username}:{req.target_app}:{req.source_ip}"
    if req.action.upper() == "LOGIN":
        session = Session(
            session_id=str(uuid4()),
            username=req.username,
            source_ip=req.source_ip,
            target_app=req.target_app,
            login_timestamp=datetime.now(timezone.utc),
            enforcement_payloads=[e.model_dump() for e in enforcements],
            source=source,
        )
        session_store.register(session)
    elif req.action.upper() == "LOGOUT":
        session_store.deregister(key)


@router.post("/webhook")
async def jit_webhook(payload: WebhookPayload) -> dict:
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "JIT",
            "message": f"Webhook received from VCF Operations: {payload.action} for {payload.username}@{payload.target_app}",
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
        destination_ip=payload.destination_ip,
        device_name=payload.device_name,
        port=payload.port,
        access_protocol=payload.access_protocol,
    )

    enforcements = JITService.generate_enforcements(req)

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

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "JIT",
            "message": f"SUCCESS: 3 enforcement payloads dispatched for {payload.username} ({payload.action})",
            "payload": None,
        }
    )

    _register_session(req, enforcements, source="webhook")

    return {"status": "enforced", "count": len(enforcements), "action": payload.action}


@router.post("/direct")
async def jit_direct(req: DirectJITRequest, request: Request) -> dict:
    """Direct external call to the L7 APIM — bypasses IDSP/VCF Operations pipeline."""
    if req.source_ip == "127.0.0.1" and request.client:
        req.source_ip = request.client.host
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
        destination_ip=req.destination_ip,
        device_name=req.device_name,
        port=req.port,
        access_protocol=req.access_protocol,
    )

    enforcements = JITService.generate_enforcements(jit_req)

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

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "JIT",
            "message": f"SUCCESS: 3 enforcement payloads generated for {req.username} ({req.action})",
            "payload": None,
        }
    )

    _register_session(jit_req, enforcements, source="direct-api")

    return {
        "status": "enforced",
        "request": req.model_dump(),
        "enforcements": [e.model_dump() for e in enforcements],
    }


@router.post("/enforce")
async def jit_enforce(req: DirectJITRequest, request: Request) -> dict:
    """Generate enforcements and submit them to live NSX/AVI infrastructure."""
    if req.source_ip == "127.0.0.1" and request.client:
        req.source_ip = request.client.host
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

    results = await execute_live_enforcement(
        username=req.username,
        source_ip=req.source_ip,
        target_app=req.target_app,
        action=req.action,
        destination_ip=req.destination_ip,
        device_name=req.device_name,
        port=req.port,
        access_protocol=req.access_protocol,
        source="live-enforce",
    )

    # Register session using a JITRequest for the helper
    ts = datetime.now(timezone.utc).isoformat()
    jit_req = JITRequest(
        source="live-enforce",
        event_type="Live Enforcement",
        username=req.username,
        source_ip=req.source_ip,
        target_app=req.target_app,
        action=req.action,
        original_timestamp=ts,
        destination_ip=req.destination_ip,
        device_name=req.device_name,
        port=req.port,
        access_protocol=req.access_protocol,
    )
    from domain.jit_middleware.service import JITService as _JITService
    _enf = _JITService.generate_enforcements(jit_req)
    _register_session(jit_req, _enf, source="live-enforce")

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
