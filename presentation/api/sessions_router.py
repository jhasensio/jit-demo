"""
Sessions management API.

Provides REST endpoints for listing active sessions, reading/updating settings,
and killing sessions (via the mock IDSP API).
"""
from fastapi import APIRouter, HTTPException, Query

from core.logger import event_bus
from domain.sessions.models import SessionSettings, SessionSummary
from infrastructure.session_store import session_store

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("/", response_model=list[SessionSummary])
async def list_sessions(
    exclude_demo: bool = Query(False, description="Exclude demo-sourced sessions"),
) -> list[SessionSummary]:
    """Return all sessions (all statuses). Pass exclude_demo=true to hide demo sessions."""
    sessions = session_store.get_all()
    if exclude_demo:
        sessions = [s for s in sessions if s.source != "demo"]
    return [session_store.to_summary(s) for s in sessions]


@router.get("/active", response_model=list[SessionSummary])
async def list_active_sessions() -> list[SessionSummary]:
    """Return only active sessions."""
    return [session_store.to_summary(s) for s in session_store.get_active()]


@router.get("/settings", response_model=SessionSettings)
async def get_settings() -> SessionSettings:
    return session_store.get_settings()


@router.post("/settings", response_model=SessionSettings)
async def update_settings(settings: SessionSettings) -> SessionSettings:
    session_store.update_settings(settings)
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "SESSION",
            "message": (
                f"Settings updated — mode: {settings.mode}, "
                f"TTL: {settings.ttl_seconds}s, "
                f"poll: {settings.poll_interval_seconds}s, "
                f"auto-enforce: {settings.auto_enforce}"
            ),
            "payload": settings.model_dump(),
        }
    )
    return settings


@router.post("/{session_id}/kill")
async def kill_session(session_id: str) -> dict:
    """
    Kill a session via the mock IDSP API.
    Sets the mock IDSP session to inactive — the poller detects this on its next cycle.
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
