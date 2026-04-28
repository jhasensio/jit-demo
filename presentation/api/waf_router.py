"""
WAF webhook API.

Receives alert webhooks from VCF Operations for Logs (Log Insight) triggered by
AVI WAF detection events. Looks up active sessions by offending client IP and
immediately revokes them via live enforcement — no auth required for this PoC.

Log Insight's default webhook payload carries no source_ip at the top level.
To include it, configure a custom webhook template in Log Insight and add:
  "source_ip": "{{source_ip}}"
If absent, the endpoint attempts to extract the IP from the 'messages' entries.
"""
from fastapi import APIRouter

from core.logger import event_bus
from domain.waf.models import WAFRevokeResult, WAFWebhookPayload
from domain.waf.service import summarize
from infrastructure.enforcement_service import execute_live_enforcement
from infrastructure.session_store import session_store

router = APIRouter(prefix="/waf", tags=["WAF"])


@router.post("/webhook", response_model=WAFRevokeResult)
async def waf_webhook(payload: WAFWebhookPayload) -> WAFRevokeResult:
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "WAF",
            "message": summarize(payload),
            "payload": payload.model_dump(),
        }
    )

    # If no IP could be resolved, return early with a clear explanation
    if not payload.source_ip:
        note = (
            "No source_ip found in payload or messages. "
            "Add \"source_ip\": \"{{source_ip}}\" to the Log Insight webhook template."
        )
        await event_bus.publish(
            {
                "level": "WARN",
                "domain": "WAF",
                "message": f"WAF alert received but no client IP could be resolved — {note}",
                "payload": payload.model_dump(),
            }
        )
        return WAFRevokeResult(revoked=0, sessions=[], details=[], note=note)

    sessions = session_store.get_by_source_ip(payload.source_ip)
    if payload.target_app:
        sessions = [s for s in sessions if s.target_app == payload.target_app]

    if not sessions:
        await event_bus.publish(
            {
                "level": "WARN",
                "domain": "WAF",
                "message": f"No active session found for {payload.source_ip}",
                "payload": None,
            }
        )
        return WAFRevokeResult(revoked=0, sessions=[], details=[], source_ip=payload.source_ip)

    details = []
    for s in sessions:
        session_store.mock_idsp_set_active(s.session_id, False)
        if session_store.mark_revoked(s.session_key, reason="waf-block") is None:
            continue  # idempotency: already revoked between lookup and now
        results = await execute_live_enforcement(
            username=s.username,
            source_ip=s.source_ip,
            target_app=s.target_app,
            action="LOGOUT",
            source="waf-revoke",
        )
        details.append({"session_key": s.session_key, "enforcement": results})

    ok_count = sum(1 for d in details for r in d["enforcement"] if r.get("success"))
    total_enforcements = sum(len(d["enforcement"]) for d in details)
    level = "SUCCESS" if ok_count == total_enforcements else "ERROR"

    await event_bus.publish(
        {
            "level": level,
            "domain": "WAF",
            "message": (
                f"WAF revoked {len(details)} session(s) for {payload.source_ip} "
                f"— enforcement {ok_count}/{total_enforcements} system(s) updated"
            ),
            "payload": {
                "sessions": [d["session_key"] for d in details],
                "source_ip": payload.source_ip,
                "reason": "waf-block",
            },
        }
    )

    return WAFRevokeResult(
        revoked=len(details),
        sessions=[d["session_key"] for d in details],
        details=details,
        source_ip=payload.source_ip,
    )
