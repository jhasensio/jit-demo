from domain.sessions.models import Session, SessionSettings, SessionSummary


class SessionStore:
    """In-memory singleton tracking active JIT sessions and mock IDSP session state."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}       # keyed by session_key
        self._mock_idsp_active: dict[str, bool] = {}  # keyed by session_id
        self._settings = SessionSettings()

    # ── Session CRUD ─────────────────────────────────────────────────────────

    def register(self, session: Session) -> None:
        """Upsert session by session_key. Overwrites if key already exists."""
        self._sessions[session.session_key] = session
        self._mock_idsp_active[session.session_id] = True

    def deregister(self, session_key: str) -> "Session | None":
        """Mark session as logged_out. Returns the session or None if not found."""
        session = self._sessions.get(session_key)
        if session is None:
            return None
        session.status = "logged_out"
        self._mock_idsp_active[session.session_id] = False
        return session

    def get(self, session_key: str) -> "Session | None":
        return self._sessions.get(session_key)

    def get_by_id(self, session_id: str) -> "Session | None":
        for s in self._sessions.values():
            if s.session_id == session_id:
                return s
        return None

    def get_active(self) -> list[Session]:
        return [s for s in self._sessions.values() if s.status == "active"]

    def get_all(self) -> list[Session]:
        return list(self._sessions.values())

    def mark_expired(self, session_key: str) -> "Session | None":
        """Mark session as expired. Returns None if session is already non-active (guard)."""
        session = self._sessions.get(session_key)
        if session is None or session.status != "active":
            return None
        session.status = "expired"
        self._mock_idsp_active[session.session_id] = False
        return session

    def mark_revoked(self, session_key: str) -> "Session | None":
        """Mark session as revoked. Returns None if session is already non-active (guard)."""
        session = self._sessions.get(session_key)
        if session is None or session.status != "active":
            return None
        session.status = "revoked"
        self._mock_idsp_active[session.session_id] = False
        return session

    # ── Mock IDSP state ───────────────────────────────────────────────────────

    def mock_idsp_is_active(self, session_id: str) -> bool:
        return self._mock_idsp_active.get(session_id, False)

    def mock_idsp_set_active(self, session_id: str, active: bool) -> None:
        self._mock_idsp_active[session_id] = active

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> SessionSettings:
        return self._settings

    def update_settings(self, settings: SessionSettings) -> None:
        self._settings = settings

    # ── Summary projection ────────────────────────────────────────────────────

    def to_summary(self, session: Session) -> SessionSummary:
        return SessionSummary(
            session_id=session.session_id,
            username=session.username,
            source_ip=session.source_ip,
            target_app=session.target_app,
            status=session.status,
            elapsed_seconds=round(session.elapsed_seconds(), 1),
            login_timestamp=session.login_timestamp.isoformat(),
            source=session.source,
        )


# Module-level singleton — imported everywhere
session_store = SessionStore()
