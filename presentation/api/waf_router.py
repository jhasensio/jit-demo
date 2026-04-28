"""
WAF webhook API.

Receives alert webhooks from VCF Operations for Logs (Log Insight) triggered by
AVI WAF detection events. Looks up active sessions by offending client IP and
immediately revokes them via live enforcement — no auth required for this PoC.
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

    sessions = session_store.get_by_source_ip(payload.client_ip)
    if payload.target_app:
        sessions = [s for s in sessions if s.target_app == payload.target_app]

    if not sessions:
        await event_bus.publish(
            {
                "level": "WARN",
                "domain": "WAF",
                "message": f"No active session found for {payload.client_ip}",
                "payload": None,
            }
        )
        return WAFRevokeResult(revoked=0, sessions=[], details=[])

    details = []
    for s in sessions:
        session_store.mock_idsp_set_active(s.session_id, False)
        if session_store.mark_revoked(s.session_key) is None:
            continue  # idempotency: already revoked between lookup and now
        results = await execute_live_enforcement(
            username=s.username,
            source_ip=s.source_ip,
            target_app=s.target_app,
            action="LOGOUT",
            source="waf-revoke",
        )
        details.append({"session_key": s.session_key, "enforcement": results})

    ok_count = sum(
        1
        for d in details
        for r in d["enforcement"]
        if r.get("success")
    )
    total_enforcements = sum(len(d["enforcement"]) for d in details)
    level = "SUCCESS" if ok_count == total_enforcements else "ERROR"

    await event_bus.publish(
        {
            "level": level,
            "domain": "WAF",
            "message": (
                f"WAF revoked {len(details)} session(s) for {payload.client_ip} "
                f"— enforcement {ok_count}/{total_enforcements} system(s) updated"
            ),
            "payload": {"sessions": [d["session_key"] for d in details]},
        }
    )

    return WAFRevokeResult(
        revoked=len(details),
        sessions=[d["session_key"] for d in details],
        details=details,
    )
