# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VMware Zero Trust — JIT Access PoC. A single-process FastAPI application demonstrating Just-in-Time (JIT) access workflows across three simulated security domains: IDSP (identity), Aria SIEM, and JIT Middleware (enforces policy on NSX Gateway/Distributed Firewall and AVI Load Balancer). All activity streams in real-time to the browser via SSE.

## Running the Application

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (starts FastAPI on :8000 + UDP listener on :5140)
python main.py

# Or via uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Access the UI at `http://localhost:8000`. Test syslog input: `echo "..." | nc -u localhost 5140`.

No test suite exists — testing is manual via the browser "Architecture Demo" view or curl.

## Architecture

**Domain-Driven Design**: `domain/` holds pure business logic (Pydantic models + services, no I/O). `infrastructure/` holds singletons and I/O adapters. `presentation/` holds FastAPI routers and Jinja2 templates.

**Full pipeline**:
```
POST /idsp/submit
  → UDP syslog → :5140 UDP listener
  → AriaService parses syslog, builds webhook payload
  → POST /jit/webhook
  → JITService generates EnforcementPayload (NSX PATCH + AVI PUT)
  → Optional live enforcement via NSXClient / AVIClient
  → SessionStore registers session
  → EventBus publishes all events → GET /events (SSE) → browser
```

**Bypass paths**:
- `POST /jit/direct` — skip IDSP/Aria, generate payloads without enforcement
- `POST /jit/enforce` — generate payloads + submit live to NSX/AVI (requires saved credentials)

**Background lifecycle** (`infrastructure/session_poller.py`): asyncio task that polls IDSP state and checks TTL every N seconds. On expiry/revocation, triggers LOGOUT enforcement payloads and optionally submits them live.

## Key Design Decisions

**In-memory state**: Sessions (`SessionStore`), credentials (`CredentialStore`), and session settings are held in memory — lost on restart. Only SQLite (`zero_trust.db`) persists policy mappings and target apps.

**EventBus** (`core/logger.py`): All domains publish to a central pub-sub queue; subscribers read via asyncio `Queue`. The SSE `/events` endpoint streams these to the browser. Up to 100 queued events per subscriber; dead queues are cleaned up on overflow.

**Surgical IP removal**: When LOGOUT fires, NSXClient and AVIClient receive a `remove_ip`/`remove_addr` flag in the payload, which causes them to surgically remove only that IP rather than overwrite the whole group — preserving concurrent users' access.

**AVI SDK compatibility**: `avisdk` is synchronous; all AVI calls are wrapped in `asyncio.to_thread`.

**Session key**: `{username}:{target_app}:{source_ip}` — unique per user+app+IP combination.

**NSX group naming convention**: `{prefix}-JIT-active-users-ipaddr` (e.g., `HR_APP_01` → `HR-JIT-active-users-ipaddr`). AVI groups follow the same pattern or can be overridden via policy mapping.

## Critical Files

| File | Role |
|------|------|
| `main.py` | App factory, lifespan startup/shutdown (UDP listener + session poller) |
| `core/logger.py` | EventBus pub-sub + SSE `/events` endpoint |
| `domain/jit_middleware/service.py` | Enforcement payload generation (NSX + AVI) |
| `domain/aria/service.py` | Syslog regex parser + webhook builder |
| `infrastructure/session_poller.py` | Background TTL/polling lifecycle + auto-revocation |
| `infrastructure/enforcement_service.py` | `execute_live_enforcement()` shared by `/jit/enforce` + poller |
| `presentation/static/js/app.js` | SSE client, view routing, form handling |

## Database

SQLite via SQLAlchemy ORM. `init_db()` runs on startup and seeds 3 target apps (`HR_APP_01`, `FIN_APP_01`, `ENG_APP_01`) with mock IPs if they don't already exist. Schema is auto-created on first run.

## Session Settings (configurable per-session via API)

- `ttl_seconds` (default 300): max session lifetime
- `poll_interval_seconds` (default 30): IDSP check cadence
- `mode`: `"ttl_only"` | `"polling_only"` | `"both"`
- `auto_enforce` (default `False`): whether revocation auto-submits LOGOUT to NSX/AVI
