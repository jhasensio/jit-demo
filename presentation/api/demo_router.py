"""
Stepped Architecture Demo endpoints.

Three stateless endpoints — each step fires independently and the frontend
passes data forward between steps. No server-side state is stored.
"""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request

from core.logger import event_bus
from domain.aria.models import WebhookPayload
from domain.aria.service import AriaService
from domain.idsp.models import AuthRequest
from domain.idsp.service import IDSPService
from domain.jit_middleware.models import JITRequest
from domain.jit_middleware.service import JITService
from domain.sessions.models import Session
from infrastructure.session_store import session_store

router = APIRouter(prefix="/demo", tags=["Architecture Demo"])


@router.post("/authenticate")
async def demo_authenticate(req: AuthRequest, request: Request) -> dict:
    """Step 1 — IDSP: build the Session Management syslog message."""
    if req.source_ip == "127.0.0.1" and request.client:
        req.source_ip = request.client.host
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "IDSP",
            "context": "demo",
            "message": f"Authentication event received: {req.action} for {req.username} from {req.source_ip}",
            "payload": None,
        }
    )

    syslog = IDSPService.build_idsp_syslog(req)

    await event_bus.publish(
        {
            "level": "PAYLOAD",
            "domain": "IDSP",
            "context": "demo",
            "message": "Session Management syslog generated — forwarding to VCF Operations via UDP :5140",
            "payload": {"syslog": syslog},
        }
    )

    return {"syslog": syslog, "request": req.model_dump()}


@router.post("/parse")
async def demo_parse(body: dict) -> dict:
    """Step 2 — VCF Operations: parse the syslog and build the JIT webhook payload."""
    syslog: str = body.get("syslog", "")

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "ARIA",
            "context": "demo",
            "message": "Syslog received from IDSP — applying regex parser",
            "payload": None,
        }
    )

    parsed = AriaService.parse_idsp_syslog(syslog)
    if parsed is None:
        await event_bus.publish(
            {
                "level": "ERROR",
                "domain": "ARIA",
                "context": "demo",
                "message": "Syslog parse failed — unrecognised message format",
                "payload": {"raw": syslog[:200]},
            }
        )
        return {"error": "parse_failed", "parsed": None, "webhook": None}

    await event_bus.publish(
        {
            "level": "PAYLOAD",
            "domain": "ARIA",
            "context": "demo",
            "message": "Syslog parsed successfully — structured event extracted",
            "payload": parsed.model_dump(),
        }
    )

    webhook = AriaService.build_webhook(parsed)

    await event_bus.publish(
        {
            "level": "PAYLOAD",
            "domain": "ARIA",
            "context": "demo",
            "message": "Webhook payload built — POST /jit/webhook",
            "payload": webhook.model_dump(),
        }
    )

    return {"parsed": parsed.model_dump(), "webhook": webhook.model_dump()}


@router.post("/enforce")
async def demo_enforce(webhook: WebhookPayload) -> dict:
    """Step 3 — L7 APIM: generate enforcement payloads for vDefend and AVI."""
    ts = datetime.now(timezone.utc).isoformat()

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "JIT",
            "context": "demo",
            "message": f"Webhook received: {webhook.action} for {webhook.username}@{webhook.target_app}",
            "payload": webhook.model_dump(),
        }
    )

    req = JITRequest(
        source=webhook.source,
        event_type=webhook.event_type,
        username=webhook.username,
        source_ip=webhook.source_ip,
        target_app=webhook.target_app,
        action=webhook.action,
        original_timestamp=webhook.original_timestamp or ts,
        destination_ip=webhook.destination_ip,
        device_name=webhook.device_name,
        port=webhook.port,
        access_protocol=webhook.access_protocol,
    )

    enforcements = JITService.generate_enforcements(req)

    labels = ["[1/2] vDefend Security Group", "[2/2] AVI LB"]
    for label, enforcement in zip(labels, enforcements):
        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "JIT",
                "context": "demo",
                "message": f"{label} — {enforcement.method} {enforcement.system}",
                "payload": enforcement.model_dump(),
            }
        )

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "JIT",
            "context": "demo",
            "message": f"SUCCESS: 3 enforcement payloads generated for {webhook.username} ({webhook.action})",
            "payload": None,
        }
    )

    # Register/deregister session
    key = f"{webhook.username}:{webhook.target_app}:{webhook.source_ip}"
    if webhook.action.upper() == "LOGIN":
        session = Session(
            session_id=str(uuid4()),
            username=webhook.username,
            source_ip=webhook.source_ip,
            target_app=webhook.target_app,
            login_timestamp=datetime.now(timezone.utc),
            enforcement_payloads=[e.model_dump() for e in enforcements],
            source="demo",
        )
        session_store.register(session)
    elif webhook.action.upper() == "LOGOUT":
        session_store.deregister(key)

    return {"enforcements": [e.model_dump() for e in enforcements]}
