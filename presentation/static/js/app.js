"use strict";

// ─── Domain → Box/Arrow highlight map ───────────────────────────────────────
const DOMAIN_BOX_MAP = {
  IDSP:   { boxes: ["box-idsp"],  arrows: ["arrow-user-idsp", "arrow-idsp-aria"] },
  ARIA:   { boxes: ["box-aria"],  arrows: ["arrow-idsp-aria", "arrow-aria-jit"] },
  JIT:    { boxes: ["box-jit"],   arrows: ["arrow-aria-jit"] },
  SYSTEM: { boxes: [],            arrows: [] },
};

const JIT_ENFORCEMENT_MAP = [
  { keyword: "NSX GFW",     box: "box-gfw" },
  { keyword: "NSX DFW",     box: "box-dfw" },
  { keyword: "AVI LB",      box: "box-avi" },
  { keyword: "NSX Gateway", box: "box-gfw" },
  { keyword: "NSX Distrib", box: "box-dfw" },
];

// Allowlists (prevent class injection)
const VALID_LEVELS  = new Set(["INFO", "SUCCESS", "ERROR", "PAYLOAD", "DOMAIN"]);
const VALID_DOMAINS = new Set(["IDSP", "ARIA", "JIT", "SYSTEM", "CONNECTIONS"]);

// Enforcement card config (order matches JITService output)
const ENFORCEMENT_CARDS = [
  { id: "card-gfw", urlId: "url-gfw", bodyId: "body-gfw" },
  { id: "card-dfw", urlId: "url-dfw", bodyId: "body-dfw" },
  { id: "card-avi", urlId: "url-avi", bodyId: "body-avi" },
];

let sseSource        = null;
let reconnectTimer   = null;
let logCount         = 0;
let jitLogCount      = 0;
let _lastJITRequest  = null;   // last request received via SSE (external curl or form submit)
const RECONNECT_DELAY = 3000;

// ─── Sidebar navigation ──────────────────────────────────────────────────────
document.querySelectorAll(".sb-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".sb-item").forEach((b) => b.classList.remove("active"));
  const view = document.getElementById(`view-${name}`);
  const btn  = document.querySelector(`.sb-item[data-view="${name}"]`);
  if (view) view.classList.add("active");
  if (btn)  btn.classList.add("active");
}

// ─── SSE Connection ──────────────────────────────────────────────────────────
function connectSSE() {
  if (sseSource) { sseSource.close(); sseSource = null; }
  updateSSEStatus(false);
  sseSource = new EventSource("/events");

  sseSource.onopen = () => {
    updateSSEStatus(true);
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  };

  sseSource.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      appendLog(event);
      handleBoxHighlight(event);
      handleJITRequestCapture(event);
      handleJITCardUpdate(event);
    } catch (err) {
      console.error("SSE parse error:", err);
    }
  };

  sseSource.onerror = () => {
    updateSSEStatus(false);
    sseSource.close();
    sseSource = null;
    reconnectTimer = setTimeout(connectSSE, RECONNECT_DELAY);
  };
}

function updateSSEStatus(connected) {
  const el = document.getElementById("sse-status");
  el.textContent = connected ? "● Connected" : "○ Disconnected";
  el.className    = connected ? "connected"  : "disconnected";
}

// ─── Box / Arrow highlight (demo view) ───────────────────────────────────────
function handleBoxHighlight(event) {
  const domain  = VALID_DOMAINS.has(event.domain) ? event.domain : "SYSTEM";
  const mapping = DOMAIN_BOX_MAP[domain] || { boxes: [], arrows: [] };
  mapping.boxes.forEach(flashBox);
  mapping.arrows.forEach(activateArrow);

  if (domain === "JIT") {
    if (event.message) {
      for (const entry of JIT_ENFORCEMENT_MAP) {
        if (event.message.includes(entry.keyword)) { flashBox(entry.box); break; }
      }
    }
    if (event.payload && typeof event.payload.system === "string") {
      const sys = event.payload.system;
      if      (sys.includes("Gateway"))                            flashBox("box-gfw");
      else if (sys.includes("Distributed"))                        flashBox("box-dfw");
      else if (sys.includes("AVI") || sys.includes("Load Balancer")) flashBox("box-avi");
    }
  }
}

function flashBox(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("flashing");
  void el.offsetWidth;
  el.classList.add("flashing");
  el.addEventListener("animationend", () => el.classList.remove("flashing"), { once: true });
}

function activateArrow(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("active", "pulsing");
  void el.offsetWidth;
  el.classList.add("active", "pulsing");
  setTimeout(() => el.classList.remove("active", "pulsing"), 2200);
}

// ─── Log rendering (shared by both consoles) ──────────────────────────────────
function appendLog(event) {
  // Main demo console — full format with payload toggle
  _renderLogEntry(event, "console-output", document.getElementById("autoscroll")?.checked ?? true, true);
  // JIT mini console — compact, no payload toggle
  _renderLogEntry(event, "jit-console", document.getElementById("jit-autoscroll")?.checked ?? true, false);
}

function _renderLogEntry(event, outputId, autoScroll, showPayload) {
  const output = document.getElementById(outputId);
  if (!output) return;

  const level   = VALID_LEVELS.has(event.level)   ? event.level   : "INFO";
  const domain  = VALID_DOMAINS.has(event.domain) ? event.domain  : "SYSTEM";
  const message = typeof event.message === "string" ? event.message : "";
  const ts      = formatTimestamp(event.timestamp);

  const idBase = outputId === "console-output" ? `pl-${logCount++}` : `jpl-${jitLogCount++}`;

  const line = document.createElement("div");
  line.className = "log-line";

  const tsEl = document.createElement("span");
  tsEl.className = "log-ts";
  tsEl.textContent = ts;
  line.appendChild(tsEl);

  const domEl = document.createElement("span");
  domEl.className = `log-domain domain-${domain}`;
  domEl.textContent = `[${domain}]`;
  line.appendChild(domEl);

  const badgeEl = document.createElement("span");
  badgeEl.className = `log-badge badge-${level}`;
  badgeEl.textContent = level;
  line.appendChild(badgeEl);

  const msgEl = document.createElement("span");
  msgEl.className = "log-msg";
  msgEl.textContent = message;
  line.appendChild(msgEl);

  output.appendChild(line);

  if (showPayload && event.payload != null) {
    const toggleEl = document.createElement("span");
    toggleEl.className = "log-payload-toggle";
    toggleEl.dataset.id = idBase;
    toggleEl.textContent = "▶ JSON";
    toggleEl.addEventListener("click", () => togglePayload(idBase, toggleEl));
    line.appendChild(toggleEl);

    const payloadDiv = document.createElement("div");
    payloadDiv.id        = idBase;
    payloadDiv.className = "log-payload-body";
    buildJSONTree(event.payload, payloadDiv);
    output.appendChild(payloadDiv);
  }

  if (autoScroll) output.scrollTop = output.scrollHeight;
}

function togglePayload(id, toggleEl) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle("expanded");
  if (toggleEl) toggleEl.textContent = el.classList.contains("expanded") ? "▼ JSON" : "▶ JSON";
}

function formatTimestamp(iso) {
  if (!iso) return "--:--:--";
  try { return new Date(iso).toTimeString().slice(0, 8); } catch { return "--:--:--"; }
}

// DOM-safe JSON tree builder
function buildJSONTree(obj, container) {
  const pre = document.createElement("pre");
  pre.style.cssText = "white-space:pre-wrap;word-break:break-all;";
  renderJSONValue(obj, pre, 0);
  container.appendChild(pre);
}

function renderJSONValue(value, parent, indent) {
  if (value === null)              { appendSpan(parent, "null",          "json-null");   }
  else if (typeof value === "boolean") { appendSpan(parent, String(value), "json-bool");   }
  else if (typeof value === "number")  { appendSpan(parent, String(value), "json-number"); }
  else if (typeof value === "string")  { appendSpan(parent, JSON.stringify(value), "json-string"); }
  else if (Array.isArray(value)) {
    appendText(parent, "[\n");
    value.forEach((item, i) => {
      appendText(parent, "  ".repeat(indent + 1));
      renderJSONValue(item, parent, indent + 1);
      if (i < value.length - 1) appendText(parent, ",");
      appendText(parent, "\n");
    });
    appendText(parent, "  ".repeat(indent) + "]");
  } else if (typeof value === "object") {
    const keys = Object.keys(value);
    appendText(parent, "{\n");
    keys.forEach((k, i) => {
      appendText(parent, "  ".repeat(indent + 1));
      appendSpan(parent, JSON.stringify(k), "json-key");
      appendText(parent, ": ");
      renderJSONValue(value[k], parent, indent + 1);
      if (i < keys.length - 1) appendText(parent, ",");
      appendText(parent, "\n");
    });
    appendText(parent, "  ".repeat(indent) + "}");
  }
}

function appendSpan(parent, text, cls) {
  const s = document.createElement("span");
  s.className = cls;
  s.textContent = text;
  parent.appendChild(s);
}

function appendText(parent, text) {
  parent.appendChild(document.createTextNode(text));
}

function clearConsole() {
  document.getElementById("console-output").textContent = "";
  logCount = 0;
}

function clearJITConsole() {
  document.getElementById("jit-console").textContent = "";
  jitLogCount = 0;
}

// ─── JIT Middleware panel ─────────────────────────────────────────────────────

// Live request-body preview
function _getJITFormBody() {
  return {
    username:   document.getElementById("jf-username").value.trim()   || "jsmith",
    source_ip:  document.getElementById("jf-source-ip").value.trim()  || "10.0.1.50",
    target_app: document.getElementById("jf-target-app").value.trim() || "APP_PROD_01",
    action:     document.getElementById("jf-action").value,
  };
}

function updateJITPreview() {
  const preview = document.getElementById("jit-request-preview");
  if (!preview) return;
  preview.textContent = "";
  buildJSONTree(_getJITFormBody(), preview);
}

function copyCURL() {
  const body = _getJITFormBody();
  const json = JSON.stringify(body, null, 2);
  const curl = [
    `curl -X POST http://localhost:8000/jit/direct \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '${json.replace(/'/g, "'\\''")}'`,
  ].join("\n");

  navigator.clipboard.writeText(curl).then(() => {
    const btn = document.getElementById("btn-copy-curl");
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove("copied");
    }, 1800);
  }).catch(() => {
    // Fallback for browsers without clipboard API
    const ta = document.createElement("textarea");
    ta.value = curl;
    ta.style.cssText = "position:fixed;opacity:0;";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  });
}

// Wire live-update to all form fields
["jf-username", "jf-source-ip", "jf-target-app", "jf-action"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("input", updateJITPreview);
});

// Seed preview on load
document.addEventListener("DOMContentLoaded", updateJITPreview);

function _resetPayloadCards() {
  ENFORCEMENT_CARDS.forEach(({ id, urlId, bodyId }) => {
    const card   = document.getElementById(id);
    const urlEl  = document.getElementById(urlId);
    const bodyEl = document.getElementById(bodyId);
    if (card)   { card.classList.remove("populated", "flash"); }
    if (urlEl)  { urlEl.textContent = ""; }
    if (bodyEl) {
      bodyEl.textContent = "";
      const ph = document.createElement("span");
      ph.className   = "placeholder";
      ph.textContent = "Awaiting request…";
      bodyEl.appendChild(ph);
    }
  });
}

function _renderEnforcements(enforcements) {
  enforcements.forEach((e, i) => {
    const cfg    = ENFORCEMENT_CARDS[i];
    if (!cfg) return;
    const card   = document.getElementById(cfg.id);
    const urlEl  = document.getElementById(cfg.urlId);
    const bodyEl = document.getElementById(cfg.bodyId);

    if (urlEl)  { urlEl.textContent = e.url; }
    if (bodyEl) { bodyEl.textContent = ""; buildJSONTree(e.payload, bodyEl); }
    if (card)   {
      card.classList.add("populated");
      card.classList.remove("flash");
      void card.offsetWidth;
      card.classList.add("flash");
    }
  });
}

// Capture the originating request from any JIT INFO event so Enforce Live
// uses the last received request rather than the stale form values.
// Ignores "ENFORCE:" events (those are triggered by Enforce Live itself).
function handleJITRequestCapture(event) {
  if (event.domain !== "JIT" || event.level !== "INFO") return;
  if ((event.message || "").startsWith("ENFORCE:")) return;
  const p = event.payload;
  if (p && p.username && p.source_ip && p.target_app && p.action) {
    _lastJITRequest = {
      username:   p.username,
      source_ip:  p.source_ip,
      target_app: p.target_app,
      action:     p.action,
    };
  }
}

// Update JIT payload cards from any SSE event — triggered by form submit OR external curl
function handleJITCardUpdate(event) {
  if (event.domain !== "JIT" || event.level !== "PAYLOAD") return;
  const ep = event.payload;                          // enforcement payload object
  if (!ep || typeof ep.system !== "string") return;

  // "[1/3]" signals the start of a new enforcement batch — reset cards
  if ((event.message || "").includes("[1/3]")) _resetPayloadCards();

  // Map system name → card config
  const sys = ep.system;
  let cfg = null;
  if      (sys.includes("Gateway"))                              cfg = ENFORCEMENT_CARDS[0];
  else if (sys.includes("Distributed"))                          cfg = ENFORCEMENT_CARDS[1];
  else if (sys.includes("AVI") || sys.includes("Load Balancer")) cfg = ENFORCEMENT_CARDS[2];
  if (!cfg) return;

  const card   = document.getElementById(cfg.id);
  const urlEl  = document.getElementById(cfg.urlId);
  const bodyEl = document.getElementById(cfg.bodyId);

  if (urlEl)  { urlEl.textContent = ep.url || ""; }
  if (bodyEl) { bodyEl.textContent = ""; buildJSONTree(ep.payload, bodyEl); }
  if (card)   {
    card.classList.add("populated");
    card.classList.remove("flash");
    void card.offsetWidth;
    card.classList.add("flash");
  }
}

async function submitJITDirect(e) {
  e.preventDefault();
  const body      = _getJITFormBody();
  const submitBtn = document.getElementById("jit-submit");
  const statusEl  = document.getElementById("jit-status");

  submitBtn.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Sending…";
  _lastJITRequest = null;   // will be set by the incoming SSE INFO event
  _resetPayloadCards();

  try {
    const resp = await fetch("/jit/direct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (resp.ok) {
      const data = await resp.json();
      _renderEnforcements(data.enforcements);
      statusEl.style.color = "var(--text-success)";
      statusEl.textContent = `✓ ${data.enforcements.length} enforcement payloads generated`;
    } else {
      const err = await resp.json().catch(() => ({}));
      statusEl.style.color = "var(--text-error)";
      statusEl.textContent = `Error ${resp.status}: ${String(err.detail || "Unknown error")}`;
    }
  } catch (err) {
    statusEl.style.color = "var(--text-error)";
    statusEl.textContent = `Network error: ${String(err.message)}`;
  } finally {
    submitBtn.disabled = false;
  }
}

// ─── IDSP Modal ───────────────────────────────────────────────────────────────
function openIDSPModal() {
  document.getElementById("modal-overlay").classList.add("open");
  document.getElementById("f-username").focus();
}

function closeIDSPModal() {
  document.getElementById("modal-overlay").classList.remove("open");
  document.getElementById("idsp-form").reset();
  document.getElementById("submit-status").textContent = "";
}

async function submitIDSP(e) {
  e.preventDefault();
  const body = {
    username:   document.getElementById("f-username").value.trim(),
    source_ip:  document.getElementById("f-source-ip").value.trim(),
    target_app: document.getElementById("f-target-app").value.trim(),
    action:     document.getElementById("f-action").value,
  };
  const statusEl  = document.getElementById("submit-status");
  const submitBtn = document.getElementById("btn-submit");
  submitBtn.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Sending…";

  try {
    const resp = await fetch("/idsp/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      statusEl.style.color = "var(--text-success)";
      statusEl.textContent = "✓ IDSP event sent — watch the console";
      setTimeout(closeIDSPModal, 1400);
    } else {
      const data = await resp.json().catch(() => ({}));
      statusEl.style.color = "var(--text-error)";
      statusEl.textContent = `Error ${resp.status}: ${String(data.detail || "Unknown error")}`;
    }
  } catch (err) {
    statusEl.style.color = "var(--text-error)";
    statusEl.textContent = `Network error: ${String(err.message)}`;
  } finally {
    submitBtn.disabled = false;
  }
}

document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target === document.getElementById("modal-overlay")) closeIDSPModal();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeIDSPModal(); });

// ─── Connections view ─────────────────────────────────────────────────────────

async function saveNSXCreds(e) {
  e.preventDefault();
  const body = {
    host:       document.getElementById("nsx-host").value.trim(),
    username:   document.getElementById("nsx-user").value.trim(),
    password:   document.getElementById("nsx-pass").value,
    verify_ssl: document.getElementById("nsx-verify-ssl").checked,
  };
  const statusEl  = document.getElementById("nsx-test-status");
  const submitBtn = document.getElementById("btn-nsx-save");
  submitBtn.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Testing connection…";

  try {
    const resp = await fetch("/connections/nsx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.success) {
      statusEl.style.color = "var(--text-success)";
      statusEl.textContent = `✓ Connected${data.version ? " — " + data.version : ""}`;
      _updateConnBadge("badge-nsx", "ok");
    } else {
      statusEl.style.color = "var(--text-error)";
      statusEl.textContent = `✗ ${String(data.error || "Connection failed")}`;
      _updateConnBadge("badge-nsx", "error");
    }
  } catch (err) {
    statusEl.style.color = "var(--text-error)";
    statusEl.textContent = `Network error: ${String(err.message)}`;
  } finally {
    submitBtn.disabled = false;
    refreshEnforceFooterStatus();
  }
}

async function saveAVICreds(e) {
  e.preventDefault();
  const body = {
    host:       document.getElementById("avi-host").value.trim(),
    username:   document.getElementById("avi-user").value.trim(),
    password:   document.getElementById("avi-pass").value,
    tenant:     document.getElementById("avi-tenant").value.trim() || "admin",
    verify_ssl: document.getElementById("avi-verify-ssl").checked,
  };
  const statusEl  = document.getElementById("avi-test-status");
  const submitBtn = document.getElementById("btn-avi-save");
  submitBtn.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Testing connection…";

  try {
    const resp = await fetch("/connections/avi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.success) {
      statusEl.style.color = "var(--text-success)";
      statusEl.textContent = `✓ Connected${data.version ? " — " + data.version : ""}`;
      _updateConnBadge("badge-avi", "ok");
    } else {
      statusEl.style.color = "var(--text-error)";
      statusEl.textContent = `✗ ${String(data.error || "Connection failed")}`;
      _updateConnBadge("badge-avi", "error");
    }
  } catch (err) {
    statusEl.style.color = "var(--text-error)";
    statusEl.textContent = `Network error: ${String(err.message)}`;
  } finally {
    submitBtn.disabled = false;
    refreshEnforceFooterStatus();
  }
}

// Update the badge next to the system name in the Connections panel header
function _updateConnBadge(id, status) {
  const el = document.getElementById(id);
  if (!el) return;
  // status is constrained to known values — safe to use as a class suffix
  const safe = ["ok", "error", "unconfigured"].includes(status) ? status : "unconfigured";
  el.textContent = safe;
  el.className = `conn-badge conn-badge-${safe}`;
}

// Poll /connections/status and refresh enforce footer indicators
async function refreshEnforceFooterStatus() {
  try {
    const resp   = await fetch("/connections/status");
    const status = await resp.json();

    _updateConnDot("dot-nsx", status.nsx);
    _updateConnDot("dot-avi", status.avi);
    _updateConnBadge("badge-nsx", status.nsx);
    _updateConnBadge("badge-avi", status.avi);

    const hostNsx = document.getElementById("host-nsx");
    const hostAvi = document.getElementById("host-avi");
    if (hostNsx) hostNsx.textContent = status.nsx_host || "—";
    if (hostAvi) hostAvi.textContent = status.avi_host || "—";

    // Enable Enforce Live only when at least one system is connected
    const enforceBtn = document.getElementById("btn-enforce");
    if (enforceBtn) {
      enforceBtn.disabled = !(status.nsx === "ok" || status.avi === "ok");
    }
  } catch (_) {
    // Non-fatal; leave dots unchanged
  }
}

function _updateConnDot(id, status) {
  const el = document.getElementById(id);
  if (!el) return;
  const safe = ["ok", "error", "unconfigured"].includes(status) ? status : "unconfigured";
  el.className = `conn-dot conn-dot-${safe}`;
}

// ─── Live enforcement ─────────────────────────────────────────────────────────

async function runLiveEnforce() {
  // Prefer the last request received via SSE (external curl or form submit)
  // over the current form values, which may be stale or unrelated.
  const body       = _lastJITRequest || _getJITFormBody();
  const enforceBtn = document.getElementById("btn-enforce");
  const resultsEl  = document.getElementById("enforce-results");

  if (enforceBtn) enforceBtn.disabled = true;
  if (resultsEl)  { resultsEl.textContent = ""; }

  // Show pending indicator
  if (resultsEl) {
    const span = document.createElement("span");
    span.className   = "enforce-pending";
    span.textContent = "Enforcing…";
    resultsEl.appendChild(span);
  }

  try {
    const resp = await fetch("/jit/enforce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();

    if (resultsEl) {
      resultsEl.textContent = "";
      const results = Array.isArray(data.results) ? data.results : [];
      if (results.length === 0) {
        const span = document.createElement("span");
        span.className   = "enforce-pending";
        span.textContent = resp.ok ? "No results returned" : `Error ${resp.status}`;
        resultsEl.appendChild(span);
      } else {
        results.forEach((r) => {
          const badge = document.createElement("span");
          const ok    = Boolean(r.success);
          badge.className   = `enforce-result-badge enforce-result-${ok ? "ok" : "err"}`;
          // Build safe label — never use unsanitised user input as class name
          const sysLabel = typeof r.system === "string"
            ? r.system.replace(/[^A-Za-z0-9 ]/g, "").slice(0, 30)
            : "System";
          badge.textContent = `${sysLabel}: ${ok ? "OK" : "FAIL"}`;
          resultsEl.appendChild(badge);
        });
      }
    }
  } catch (err) {
    if (resultsEl) {
      resultsEl.textContent = "";
      const badge = document.createElement("span");
      badge.className   = "enforce-result-badge enforce-result-err";
      badge.textContent = `Error: ${String(err.message).slice(0, 50)}`;
      resultsEl.appendChild(badge);
    }
  } finally {
    if (enforceBtn) enforceBtn.disabled = false;
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
connectSSE();
updateJITPreview();
refreshEnforceFooterStatus();
