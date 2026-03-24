import asyncio
import socket
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from core.logger import event_bus
from domain.idsp.models import AuthRequest
from domain.idsp.service import IDSPService
from infrastructure.session_store import session_store

router = APIRouter(prefix="/idsp", tags=["IDSP"])


@router.post("/submit")
async def submit_auth_event(req: AuthRequest) -> dict:
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "IDSP",
            "message": f"Authentication event received: {req.action} by {req.username} from {req.source_ip} → {req.target_app}",
            "payload": req.model_dump(),
        }
    )

    syslog = IDSPService.build_idsp_syslog(req)

    await event_bus.publish(
        {
            "level": "PAYLOAD",
            "domain": "IDSP",
            "message": "IDSP syslog message generated",
            "payload": {"syslog": syslog},
        }
    )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_udp, syslog.encode("utf-8"))

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "IDSP",
            "message": "IDSP syslog sent via UDP → 127.0.0.1:5140 (VCF Operations)",
            "payload": None,
        }
    )

    return {"status": "sent", "action": req.action, "username": req.username}


def _send_udp(data: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(data, ("127.0.0.1", 5140))


# ── Mock IDSP Session API (Symantec PAM 4.x simulation) ──────────────────────


@router.get("/sessions/{session_id}", tags=["IDSP Session API"])
async def idsp_get_session(session_id: str) -> dict:
    """
    Simulates Symantec PAM 4.x GET /CAWS/PasswordVault/v4/Sessions/{sessionId}.
    Returns session alive/dead status and metadata.
    """
    session = session_store.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    return {
        "active": session_store.mock_idsp_is_active(session_id),
        "username": session.username,
        "created_at": session.login_timestamp.isoformat(),
        "last_activity": session.last_checked.isoformat() if session.last_checked else session.login_timestamp.isoformat(),
        "target_app": session.target_app,
        "source_ip": session.source_ip,
        "checked_at": now,
    }


@router.post("/sessions/{session_id}/kill", tags=["IDSP Session API"])
async def idsp_kill_session(session_id: str) -> dict:
    """
    Kill a simulated IDSP session. Sets mock session to inactive.
    The session poller will detect this on its next cycle and trigger revocation.
    """
    session = session_store.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    session_store.mock_idsp_set_active(session_id, False)

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "SESSION",
            "message": (
                f"IDSP session killed (mock): {session.username}@{session.target_app} "
                f"— poller will revoke on next cycle"
            ),
            "payload": {"session_id": session_id, "username": session.username},
        }
    )

    return {"status": "killed", "session_id": session_id, "username": session.username}
