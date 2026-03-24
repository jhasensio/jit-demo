"""
Session lifecycle poller.

Background asyncio task that periodically:
  1. Polls mock IDSP session state for all active sessions (polling mode)
  2. Checks TTL expiry for all active sessions (TTL mode)

On expiry/revocation, optionally calls live NSX/AVI enforcement if auto_enforce is enabled.
"""
import asyncio

from core.logger import event_bus
from domain.jit_middleware.service import JITService
from domain.jit_middleware.models import JITRequest
from datetime import datetime, timezone


async def start_session_poller() -> None:
    """Entry point started as an asyncio task from main.py lifespan."""
    # Import here to avoid module-level circular import risks
    from infrastructure.session_store import session_store

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "SESSION",
            "message": "Session lifecycle poller started",
            "payload": None,
        }
    )

    try:
        while True:
            settings = session_store.get_settings()
            await asyncio.sleep(settings.poll_interval_seconds)

            if settings.mode in ("polling_only", "both"):
                await _poll_idsp_sessions(session_store)

            if settings.mode in ("ttl_only", "both"):
                await _check_ttl_expiry(session_store)

    except asyncio.CancelledError:
        await event_bus.publish(
            {
                "level": "INFO",
                "domain": "SESSION",
                "message": "Session lifecycle poller stopped",
                "payload": None,
            }
        )
        raise


async def _poll_idsp_sessions(session_store) -> None:
    """Check each active session against the mock IDSP API."""
    active = session_store.get_active()
    if not active:
        return

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "SESSION",
            "message": f"IDSP poll: checking {len(active)} active session(s)",
            "payload": None,
        }
    )

    for session in active:
        session.last_checked = datetime.now(timezone.utc)
        idsp_alive = session_store.mock_idsp_is_active(session.session_id)

        if not idsp_alive:
            await event_bus.publish(
                {
                    "level": "INFO",
                    "domain": "SESSION",
                    "message": (
                        f"IDSP session dead: {session.username}@{session.target_app} "
                        f"({session.source_ip}) — triggering revocation"
                    ),
                    "payload": None,
                }
            )
            await _revoke_session(session_store, session, reason="idsp-poll")


async def _check_ttl_expiry(session_store) -> None:
    """Expire sessions that have exceeded the configured TTL."""
    settings = session_store.get_settings()
    active = session_store.get_active()

    for session in active:
        elapsed = session.elapsed_seconds()
        if elapsed > settings.ttl_seconds:
            await event_bus.publish(
                {
                    "level": "INFO",
                    "domain": "SESSION",
                    "message": (
                        f"TTL expired: {session.username}@{session.target_app} "
                        f"({elapsed:.0f}s > {settings.ttl_seconds}s TTL) — triggering revocation"
                    ),
                    "payload": None,
                }
            )
            await _revoke_session(session_store, session, reason="ttl")


async def _revoke_session(session_store, session, reason: str) -> None:
    """
    Mark session as revoked/expired and optionally enforce live LOGOUT.
    Guard: mark_* returns None if already non-active, preventing duplicate revocations.
    """
    if reason == "ttl":
        revoked = session_store.mark_expired(session.session_key)
    else:
        revoked = session_store.mark_revoked(session.session_key)

    if revoked is None:
        return  # already handled by another concurrent check

    await event_bus.publish(
        {
            "level": "ERROR",
            "domain": "SESSION",
            "message": (
                f"Session {reason.upper()} revocation: {session.username}@{session.target_app} "
                f"from {session.source_ip} — generating LOGOUT enforcement"
            ),
            "payload": {
                "session_id": session.session_id,
                "username": session.username,
                "target_app": session.target_app,
                "source_ip": session.source_ip,
                "reason": reason,
            },
        }
    )

    settings = session_store.get_settings()

    if settings.auto_enforce:
        # Call live NSX/AVI APIs
        from infrastructure.enforcement_service import execute_live_enforcement

        results = await execute_live_enforcement(
            username=session.username,
            source_ip=session.source_ip,
            target_app=session.target_app,
            action="LOGOUT",
            source="auto-revoke",
        )
        ok_count = sum(1 for r in results if r.get("success"))
        all_ok = ok_count == len(results)
        await event_bus.publish(
            {
                "level": "SUCCESS" if all_ok else "ERROR",
                "domain": "SESSION",
                "message": (
                    f"Auto-revocation complete: {ok_count}/{len(results)} enforcement(s) succeeded "
                    f"for {session.username} ({reason})"
                ),
                "payload": None,
            }
        )
    else:
        # Generate payloads without calling live APIs (publish only)
        ts = datetime.now(timezone.utc).isoformat()
        jit_req = JITRequest(
            source="auto-revoke",
            event_type="Auto-Revocation",
            username=session.username,
            source_ip=session.source_ip,
            target_app=session.target_app,
            action="LOGOUT",
            original_timestamp=ts,
        )
        enforcements = JITService.generate_enforcements(jit_req)
        labels = ["[1/3] NSX GFW", "[2/3] NSX DFW", "[3/3] AVI LB"]
        for label, enforcement in zip(labels, enforcements):
            await event_bus.publish(
                {
                    "level": "PAYLOAD",
                    "domain": "SESSION",
                    "message": f"{label} LOGOUT payload (auto-enforce disabled — not sent live)",
                    "payload": enforcement.model_dump(),
                }
            )
        await event_bus.publish(
            {
                "level": "INFO",
                "domain": "SESSION",
                "message": (
                    f"LOGOUT payloads generated for {session.username} — "
                    "enable Auto-Enforce in Settings to push to NSX/AVI"
                ),
                "payload": None,
            }
        )
