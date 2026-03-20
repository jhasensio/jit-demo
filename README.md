# VMware Zero Trust — JIT Access PoC

An educational single-process web application that demonstrates a **Just-in-Time (JIT) access workflow** across three security domains: an Identity Service Provider (IDSP), a SIEM (Aria), and a JIT Middleware that enforces policy on NSX (Gateway & Distributed Firewall) and AVI Load Balancer.

All activity is observable in real time via an SSE-powered terminal console in the browser. No database is required — credentials and state are held in memory for the lifetime of the process.

---

## Architecture

```
External User
     │
     ▼
IDSP Simulator ──── UDP syslog ──────► Aria SIEM
  (CA PAM format)    port 5140          │
                                        │  HTTP POST /jit/webhook
                                        ▼
                                  JIT Middleware
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              NSX GFW               NSX DFW            AVI LB
         (Gateway Firewall)   (Distributed Firewall)  (IP Address Group)
         PATCH policy group   PATCH policy group      PUT ipaddrgroup
```

**LOGIN** → source IP is added to NSX policy groups and AVI IP Address Group (merged, not overwritten).
**LOGOUT** → source IP is surgically removed; other users' IPs are preserved.

---

## Views

| View | Purpose |
|---|---|
| **Architecture Demo** | Interactive diagram — click the IDSP box to fire a simulated authentication event and watch the full pipeline execute live |
| **JIT Middleware** | Build and send direct `POST /jit/direct` requests, inspect the three generated enforcement payloads, and submit them to live infrastructure with **Enforce Live** |
| **Connections** | Configure and test credentials for NSX Manager and AVI Controller |

---

## Folder Structure

```
zero-trust/
├── main.py                          # App factory, lifespan, route registration
├── requirements.txt
│
├── core/
│   └── logger.py                    # EventBus pub-sub + SSE /events endpoint
│
├── domain/                          # Pure business logic — no I/O
│   ├── idsp/
│   │   ├── models.py                # AuthRequest (Pydantic)
│   │   └── service.py               # IDSP syslog builder
│   ├── aria/
│   │   ├── models.py                # ParsedEvent, WebhookPayload
│   │   └── service.py               # Syslog parser + webhook builder
│   ├── jit_middleware/
│   │   ├── models.py                # JITRequest, DirectJITRequest, EnforcementPayload
│   │   └── service.py               # NSX GFW/DFW + AVI enforcement payload generator
│   └── connections/
│       └── models.py                # NSXCredentials, AVICredentials, ConnectionStatus
│
├── infrastructure/                  # I/O adapters
│   ├── udp_listener.py              # asyncio DatagramProtocol — Aria SIEM UDP on :5140
│   ├── http_client.py               # Async HTTP forwarder (Aria → JIT)
│   ├── nsx_client.py                # NSX 4.x Policy REST API client (httpx)
│   ├── avi_client.py                # AVI/NSX ALB client (avisdk wrapped in asyncio.to_thread)
│   └── credential_store.py          # In-memory singleton for NSX/AVI credentials
│
└── presentation/
    ├── api/
    │   ├── idsp_router.py           # POST /idsp/submit
    │   ├── aria_router.py           # GET  /aria/status
    │   ├── jit_router.py            # POST /jit/webhook  /jit/direct  /jit/enforce
    │   └── connections_router.py    # POST /connections/nsx  /connections/avi
    │                                # GET  /connections/status
    ├── templates/
    │   └── index.html               # Jinja2 SPA
    └── static/
        ├── css/style.css
        └── js/app.js
```

---

## Prerequisites

- Python 3.11+
- `avisdk` requires network access to an AVI Controller only when **Enforce Live** is used; the rest of the app works without it

---

## Installation

```bash
git clone <repo-url>
cd zero-trust

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

> **avisdk note** — `avisdk` is included in `requirements.txt`. If it fails to install in your environment the app still runs; enforcement calls to AVI will return a clear error message instead of failing silently.

---

## Running

```bash
# Development (auto-reload on file changes)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production-style (no reload)
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in a browser.

The Aria SIEM UDP listener starts automatically on **`0.0.0.0:5140`** — it accepts syslog datagrams from any interface.

---

## API Endpoints

### IDSP Simulator
| Method | Path | Description |
|---|---|---|
| `POST` | `/idsp/submit` | Submit an authentication event — triggers the full IDSP → Aria → JIT pipeline |

```bash
curl -X POST http://localhost:8000/idsp/submit \
  -H "Content-Type: application/json" \
  -d '{"username":"jsmith","source_ip":"10.0.1.50","target_app":"APP_PROD_01","action":"LOGIN"}'
```

### JIT Middleware
| Method | Path | Description |
|---|---|---|
| `POST` | `/jit/webhook` | Aria SIEM webhook — called internally by the UDP pipeline |
| `POST` | `/jit/direct` | Bypass IDSP/Aria — generate enforcement payloads directly |
| `POST` | `/jit/enforce` | Generate payloads **and** submit to live NSX/AVI infrastructure |

```bash
# Direct payload generation (no live enforcement)
curl -X POST http://localhost:8000/jit/direct \
  -H "Content-Type: application/json" \
  -d '{"username":"jsmith","source_ip":"10.0.1.50","target_app":"APP_PROD_01","action":"LOGIN"}'

# Live enforcement (requires saved credentials)
curl -X POST http://localhost:8000/jit/enforce \
  -H "Content-Type: application/json" \
  -d '{"username":"jsmith","source_ip":"10.0.1.50","target_app":"APP_PROD_01","action":"LOGOUT"}'
```

### Connections
| Method | Path | Description |
|---|---|---|
| `POST` | `/connections/nsx` | Save NSX credentials and run a live connectivity test |
| `POST` | `/connections/avi` | Save AVI credentials and run a live connectivity test |
| `GET` | `/connections/status` | Return current connection status for NSX and AVI |

```bash
curl -X POST http://localhost:8000/connections/nsx \
  -H "Content-Type: application/json" \
  -d '{"host":"https://nsx.example.com","username":"admin","password":"secret","verify_ssl":false}'
```

### Event Stream
| Method | Path | Description |
|---|---|---|
| `GET` | `/events` | Server-Sent Events stream — all domains publish here |

```bash
curl -N http://localhost:8000/events
```

---

## Sending a Real Syslog from an External Host

The UDP listener accepts datagrams on port **5140** from any interface. The expected format is the IDSP Session Management syslog:

```
<85>gkpsyslog[PID]: created = YYYY-MM-DD HH:MM:SS Private IP: , Public IP: ,
Nat/Proxy IP: <source-ip>, User: <username>, Transaction: login,
Address: - -, Device Name: - -, User Group: --, Port: - -,
Access/Protocol: - -, Service/App: <target-app>, Details: IDSP-0917: ...
```

```bash
# Quick test from any Linux/Mac host
echo '<85>gkpsyslog[1234]: created = 2026-03-20 10:00:00 Private IP: , Public IP: , Nat/Proxy IP: 10.0.1.99, User: alice, Transaction: login, Address: - -, Device Name: - -, User Group: --, Port: - -, Access/Protocol: - -, Service/App: APP_PROD_01, Details: IDSP-0917: User alice logged in successfully via local authentication.' \
  | nc -u -w1 <server-ip> 5140
```

---

## AVI IP Address Group — Naming Convention

The JIT Middleware maps `target_app` to an AVI IP Address Group using the convention:

```
JIT_<target_app>_Allowed
```

For example, `target_app = APP_PROD_01` → group name `JIT_APP_PROD_01_Allowed`.

The group is **automatically provisioned** (POST) if it does not exist. If it already exists, IPs are **merged** (LOGIN) or **surgically removed** (LOGOUT) — existing IPs from other sessions are never overwritten.

The group must be referenced by the Virtual Service's Network Security Policy for enforcement to take effect.

---

## NSX Policy Groups

Two groups are targeted on every enforcement:

| Group | Path |
|---|---|
| Gateway Firewall | `/policy/api/v1/infra/domains/default/groups/JIT_Edge_Authorized_IPs` |
| Distributed Firewall | `/policy/api/v1/infra/domains/default/groups/JIT_Workload_Authorized_IPs` |

These groups must exist in NSX and be referenced by the appropriate GFW/DFW rules.

---

## Interactive Demo Walkthrough

1. Open `http://localhost:8000` → confirm **● Connected** in the sidebar
2. Go to **Architecture Demo** → click the `IDSP Simulator` box
3. Fill in username, source IP, target app, action → click **Send**
4. Watch the console: `[IDSP]` syslog → `[ARIA]` parse → `[JIT]` three enforcement payloads
5. Go to **Connections** → enter NSX and AVI credentials → **Save & Test**
6. Go to **JIT Middleware** → build a request → **Send Request** to preview payloads
7. Click **Enforce Live** to submit to real infrastructure — results appear as `[CONNECTIONS]` events
