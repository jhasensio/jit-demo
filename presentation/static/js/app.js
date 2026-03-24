"use strict";

// ─── Domain → Mini-diagram highlight map ─────────────────────────────────────
const DOMAIN_BOX_MAP = {
  IDSP:   { boxes: ["md-idsp"], arrows: [] },
  ARIA:   { boxes: ["md-aria"], arrows: [] },
  JIT:    { boxes: ["md-jit"],  arrows: [] },
  SYSTEM: { boxes: [],          arrows: [] },
};

const JIT_ENFORCEMENT_MAP = [
  { keyword: "vDefend GFW",     box: "md-gfw" },
  { keyword: "vDefend DFW",     box: "md-dfw" },
  { keyword: "AVI LB",          box: "md-avi" },
  { keyword: "vDefend Gateway", box: "md-gfw" },
  { keyword: "vDefend Distrib", box: "md-dfw" },
];

// ─── Mini-diagram step → node mapping ────────────────────────────────────────
const MINI_DIAGRAM_STEPS = {
  1: ["md-idsp"],
  2: ["md-aria"],
  3: ["md-jit", "md-gfw", "md-dfw", "md-avi"],
  4: ["md-jit", "md-gfw", "md-dfw", "md-avi"],
};

// Allowlists (prevent class injection)
const VALID_LEVELS  = new Set(["INFO", "SUCCESS", "ERROR", "PAYLOAD", "DOMAIN"]);
const VALID_DOMAINS = new Set(["IDSP", "ARIA", "JIT", "SYSTEM", "CONNECTIONS", "SESSION"]);

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
const VIEW_HOOKS = {
  "settings":         () => loadSettings(),
  "active-sessions":  () => { refreshSessions(); startSessionsAutoRefresh(); },
  "avi-policy":       () => loadAviPolicyView(),
};

// Parent toggle: items with data-toggle collapse/expand their sub-menu
document.querySelectorAll(".sb-item--parent[data-toggle]").forEach((btn) => {
  btn.addEventListener("click", () => {
    btn.classList.toggle("open");
    const sub = document.getElementById(btn.dataset.toggle);
    if (sub) sub.classList.toggle("open");
  });
});

// Leaf click: items with data-view switch views, auto-expand parent if needed
document.querySelectorAll("[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.view) switchView(btn.dataset.view);
  });
});

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll("[data-view]").forEach((b) => b.classList.remove("active"));
  const view = document.getElementById(`view-${name}`);
  const btn  = document.querySelector(`[data-view="${name}"]`);
  if (view) view.classList.add("active");
  if (btn) {
    btn.classList.add("active");
    // Auto-expand parent sub-menu if not already open
    const sub = btn.closest(".sb-sub");
    if (sub && !sub.classList.contains("open")) {
      sub.classList.add("open");
      const parent = document.querySelector(`[data-toggle="${sub.id}"]`);
      if (parent) parent.classList.add("open");
    }
  }
  const hook = VIEW_HOOKS[name];
  if (hook) hook();
}

// ─── Theme toggle ─────────────────────────────────────────────────────────────
function toggleTheme() {
  const isDark = document.getElementById("theme-switch").checked;
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  localStorage.setItem("zt-theme", isDark ? "dark" : "light");
  document.querySelector(".theme-toggle-label").textContent = isDark ? "Light" : "Dark";
}

(function initTheme() {
  const saved = localStorage.getItem("zt-theme") || "light";
  if (saved === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    const sw = document.getElementById("theme-switch");
    if (sw) sw.checked = true;
    const lbl = document.querySelector(".theme-toggle-label");
    if (lbl) lbl.textContent = "Light";
  }
})();

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
      if (event.domain === "SESSION") handleSessionEvent();
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
      if      (sys.includes("Gateway"))                            flashBox("md-gfw");
      else if (sys.includes("Distributed"))                        flashBox("md-dfw");
      else if (sys.includes("AVI") || sys.includes("Load Balancer")) flashBox("md-avi");
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

// ─── Log rendering (separate streams) ────────────────────────────────────────
// demo context  → Architecture Demo console only (full format + payload toggle)
// live context  → JIT Middleware console only (compact, no payload toggle)
function appendLog(event) {
  const isDemoCtx = event.context === "demo";
  if (isDemoCtx) {
    _renderLogEntry(event, "console-output", document.getElementById("autoscroll")?.checked ?? true, true);
  } else {
    _renderLogEntry(event, "jit-console", document.getElementById("jit-autoscroll")?.checked ?? true, false);
  }
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
  line.dataset.domain = domain;

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
    username:        document.getElementById("jf-username").value.trim()    || "jsmith",
    source_ip:       document.getElementById("jf-source-ip").value.trim()   || "127.0.0.1",
    target_app:      document.getElementById("jf-target-app").value,
    action:          document.getElementById("jf-action").value,
    port:            document.getElementById("jf-port").value.trim()        || "22",
    access_protocol: document.getElementById("jf-protocol").value.trim()    || "SSH",
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
  const host = `${window.location.hostname}:${window.location.port || 8000}`;
  const curl = [
    `curl -X POST http://${host}/jit/direct \\`,
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

let _lastSessionsList = [];   // updated by refreshSessions()

function copyIDSPCurl() {
  const host = `${window.location.hostname}:${window.location.port || 8000}`;
  const active = _lastSessionsList.find((s) => s.status === "active");
  const sessionId = active ? active.session_id : "{SESSION_ID}";
  const curl = `curl -s http://${host}/idsp/sessions/${sessionId}`;

  const btn = document.getElementById("btn-copy-idsp-curl");
  navigator.clipboard.writeText(curl).then(() => {
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 1800);
  }).catch(() => {
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
["jf-username", "jf-source-ip", "jf-target-app", "jf-action", "jf-port", "jf-protocol"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("input", updateJITPreview);
});

// Seed preview on load + auto-fill source IP fields from server-detected client IP
document.addEventListener("DOMContentLoaded", () => {
  updateJITPreview();
  fetch("/client-ip")
    .then((r) => r.json())
    .then(({ ip }) => {
      ["da-source-ip", "jf-source-ip"].forEach((id) => {
        const el = document.getElementById(id);
        if (el && !el.value) el.value = ip;
      });
      updateJITPreview();
    })
    .catch(() => {});

  // AVI policy forms use onsubmit inline handlers; no additional wiring needed
});

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
      username:        p.username,
      source_ip:       p.source_ip,
      target_app:      p.target_app,
      action:          p.action,
      destination_ip:  p.destination_ip  || "192.168.10.100",
      device_name:     p.device_name     || "linux-db-prod-01",
      port:            p.port            || "22",
      access_protocol: p.access_protocol || "SSH",
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

// ─── Architecture Demo — Step Wizard ─────────────────────────────────────────

const DEMO_STEP_DOMAINS = { 1: "IDSP", 2: "ARIA", 3: "JIT", 4: "JIT" };

const DEMO_EXPLANATIONS = {
  1: "The Identity Service Provider (IDSP) authenticates the user against the target application. " +
     "Upon successful authentication it generates a Session Management syslog message. " +
     "The 13-field syslog carries identity metadata, network origin, destination target, and event details — " +
     "and is forwarded to VCF Operations via UDP port 5140.",
  2: "VCF Operations for Logs receives the UDP syslog datagram and applies a structured regex parser " +
     "to extract 13 named fields. The parsed event is enriched into a webhook payload and forwarded " +
     "to the L7 APIM via HTTP POST /jit/webhook.",
  3: "The L7 APIM receives the webhook and generates enforcement payloads for each security engine. " +
     "vDefend Gateway Firewall and Distributed Firewall groups are scoped per application. " +
     "Source IPs are merged on LOGIN — the user's IP is added to the authorized group.",
  4: "When a session ends — either by explicit logout or by automatic revocation (TTL expiry or IDSP polling) — " +
     "the L7 APIM generates LOGOUT enforcement payloads to withdraw the previously granted access. " +
     "vDefend and AVI both surgically remove only the revoked user's IP, preserving all other active sessions' IPs.",
};

let demoState = {
  step: 0,            // 0 = landing, 1-4 = wizard steps
  syslog: null,
  request: null,
  parsed: null,
  webhook: null,
  enforcements: null,
  revoke_enforcements: null,
  revoke_type: "logout",   // "logout" | "policy"
};

function _getDemoAuthBody() {
  return {
    username:        document.getElementById("da-username").value.trim()    || "jsmith",
    source_ip:       document.getElementById("da-source-ip").value.trim()   || "127.0.0.1",
    target_app:      document.getElementById("da-target-app").value,
    action:          document.getElementById("da-action").value,
    port:            document.getElementById("da-port").value.trim()        || "22",
    access_protocol: document.getElementById("da-protocol").value.trim()    || "SSH",
  };
}

function _setDemoStepIndicators() {
  document.querySelectorAll(".demo-step-item").forEach((el) => {
    const s = parseInt(el.dataset.step, 10);
    el.classList.remove("active", "done");
    if (s === demoState.step) el.classList.add("active");
    if (s <  demoState.step)  el.classList.add("done");
  });
}

function _setDemoConsoleFilter() {
  const output = document.getElementById("console-output");
  if (!output) return;
  output.classList.remove("filter-IDSP", "filter-ARIA", "filter-JIT");
  const domain = DEMO_STEP_DOMAINS[demoState.step];
  if (domain) output.classList.add(`filter-${domain}`);
  const titleEl = document.getElementById("demo-console-title");
  const label = demoState.step === 4 ? "JIT — Revocation" : domain;
  if (titleEl) titleEl.textContent = label ? `Event Stream — [${label}]` : "Event Stream";
}

function _setDemoNavButtons() {
  const backBtn = document.getElementById("btn-demo-back");
  const nextBtn = document.getElementById("btn-demo-next");
  const hintEl  = document.getElementById("demo-nav-hint");
  const isLanding = demoState.step === 0;

  if (backBtn) backBtn.disabled = isLanding || demoState.step <= 0;

  if (nextBtn) {
    if (isLanding) {
      nextBtn.textContent = "Start \u25B6";
      nextBtn.disabled    = false;
    } else if (demoState.step === 4) {
      nextBtn.textContent = "\u21BA Restart";
      nextBtn.disabled    = false;
    } else {
      nextBtn.textContent = "Next \u25B6";
      nextBtn.disabled    = !_demoStepComplete();
    }
  }

  if (hintEl) hintEl.textContent = (!isLanding && !_demoStepComplete()) ? _demoStepHint() : "";
}

function _demoStepComplete() {
  if (demoState.step === 0) return true;
  if (demoState.step === 1) return demoState.syslog !== null;
  if (demoState.step === 2) return demoState.webhook !== null;
  return true;
}

function _demoStepHint() {
  if (demoState.step === 1) return "Fill in the form and click Authenticate";
  if (demoState.step === 2) return "Parsing\u2026";
  return "";
}

function _renderDemoStep() {
  const isLanding = demoState.step === 0;

  // Toggle landing vs wizard panels
  const landingEl = document.getElementById("demo-landing");
  const leftEl    = document.getElementById("demo-left");
  const rightEl   = document.getElementById("demo-right");
  if (landingEl) landingEl.style.display = isLanding ? "flex" : "none";
  if (leftEl)    leftEl.style.display    = isLanding ? "none" : "";
  if (rightEl)   rightEl.style.display   = isLanding ? "none" : "";

  _setDemoStepIndicators();
  _setDemoConsoleFilter();
  updateMiniDiagram(demoState.step);

  if (!isLanding) {
    // Show/hide step panels
    ["step1-panel", "step2-panel", "step3-panel", "step4-panel"].forEach((id, i) => {
      const el = document.getElementById(id);
      if (el) el.style.display = (demoState.step === i + 1) ? "" : "none";
    });

    // Update explanation text
    const explainEl = document.getElementById("demo-explain-text");
    if (explainEl) explainEl.textContent = DEMO_EXPLANATIONS[demoState.step] || "";

    _renderDemoDataReveal();
  }

  _setDemoNavButtons();
}

function startDemo() {
  demoState.step = 1;
  _renderDemoStep();
}

function _renderDemoDataReveal() {
  const container = document.getElementById("demo-data-reveal");
  if (!container) return;
  container.textContent = "";

  if (demoState.step === 1 && demoState.syslog) {
    const label = document.createElement("div");
    label.className   = "demo-reveal-label";
    label.textContent = "Generated Syslog Message";
    container.appendChild(label);

    const pre = document.createElement("div");
    pre.className   = "code-block";
    pre.style.cssText = "margin-top:0; white-space:pre-wrap; word-break:break-all; background:#000; color:#c8d6e5;";
    pre.textContent = demoState.syslog;
    container.appendChild(pre);
  }

  if (demoState.step === 2 && demoState.webhook) {
    const label = document.createElement("div");
    label.className   = "demo-reveal-label";
    label.textContent = "Webhook Payload → POST /jit/webhook";
    container.appendChild(label);

    const box = document.createElement("div");
    box.className = "code-block";
    box.style.cssText = "margin-top:0; background:#000; color:#c8d6e5;";
    buildJSONTree(demoState.webhook, box);
    container.appendChild(box);
  }

  // Step 4 right-panel: summary text after revocation is triggered
  if (demoState.step === 4 && demoState.revoke_enforcements) {
    const info = document.createElement("div");
    info.className = "demo-reveal-label";
    const r = demoState.request || {};
    info.textContent = `Access revoked — ${r.username || "user"} (${r.source_ip || "IP"}) removed from ${r.target_app || "app"} groups`;
    container.appendChild(info);
  }
}

function _renderDemoFieldMap() {
  const container = document.getElementById("demo-field-map");
  if (!container || !demoState.parsed) return;
  container.textContent = "";

  const hdr = document.createElement("div");
  hdr.className   = "demo-reveal-label";
  hdr.textContent = "Parsed Event Fields";
  hdr.style.marginBottom = "8px";
  container.appendChild(hdr);

  const FIELD_LABELS = [
    ["timestamp",       "Timestamp"],
    ["event_type",      "Event Type"],
    ["username",        "Username"],
    ["source_ip",       "Source IP"],
    ["target_app",      "Target App"],
    ["action",          "Action"],
    ["destination_ip",  "Destination IP"],
    ["device_name",     "Device Name"],
    ["port",            "Port"],
    ["access_protocol", "Access Protocol"],
  ];

  const table = document.createElement("table");
  table.className = "demo-field-table";

  const thead = document.createElement("thead");
  const hrow  = document.createElement("tr");
  ["Field", "Value"].forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h;
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  const DEST_FIELDS = new Set(["destination_ip", "device_name", "port", "access_protocol"]);
  FIELD_LABELS.forEach(([key, label]) => {
    const tr = document.createElement("tr");
    if (DEST_FIELDS.has(key)) tr.classList.add("highlight");
    const td1 = document.createElement("td");
    td1.textContent = label;
    const td2 = document.createElement("td");
    td2.textContent = String(demoState.parsed[key] || "—");
    tr.appendChild(td1);
    tr.appendChild(td2);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}

function _renderDemoEnfCards() {
  const container = document.getElementById("demo-enf-cards");
  if (!container || !demoState.enforcements) return;
  container.textContent = "";

  const METHOD_CLASS = { "PATCH": "", "PUT": "method-put" };

  demoState.enforcements.forEach((e) => {
    const card = document.createElement("div");
    card.className = "payload-card populated";

    const hd = document.createElement("div");
    hd.className = "card-hd";

    const sys = document.createElement("span");
    sys.className   = "card-sys";
    sys.textContent = typeof e.system === "string"
      ? e.system.replace(/[<>]/g, "")
      : "System";

    const badge = document.createElement("span");
    const meth = typeof e.method === "string" ? e.method.replace(/[^A-Z]/g, "") : "?";
    badge.className   = `method-badge ${METHOD_CLASS[meth] || ""}`;
    badge.textContent = meth;

    hd.appendChild(sys);
    hd.appendChild(badge);

    const urlEl = document.createElement("div");
    urlEl.className   = "card-url";
    urlEl.textContent = typeof e.url === "string" ? e.url : "";

    const body = document.createElement("div");
    body.className = "card-body";
    if (e.payload && typeof e.payload === "object") {
      buildJSONTree(e.payload, body);
    }

    card.appendChild(hd);
    card.appendChild(urlEl);
    card.appendChild(body);
    container.appendChild(card);
  });
}

async function demoAuthenticate(e) {
  e.preventDefault();
  const body      = _getDemoAuthBody();
  const submitBtn = document.getElementById("btn-demo-auth");
  const statusEl  = document.getElementById("demo-auth-status");

  submitBtn.disabled = true;
  statusEl.style.color = "var(--text-muted)";
  statusEl.textContent = "Authenticating…";

  try {
    const resp = await fetch("/demo/authenticate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      const data = await resp.json();
      demoState.syslog  = data.syslog  || null;
      demoState.request = data.request || null;
      statusEl.style.color = "var(--text-success)";
      statusEl.textContent = "✓ Syslog generated";
      _renderDemoStep();         // reveal syslog in right panel + enable Next
    } else {
      const err = await resp.json().catch(() => ({}));
      statusEl.style.color = "var(--text-error)";
      statusEl.textContent = `Error ${resp.status}: ${String(err.detail || "Unknown")}`;
    }
  } catch (err) {
    statusEl.style.color = "var(--text-error)";
    statusEl.textContent = `Network error: ${String(err.message)}`;
  } finally {
    submitBtn.disabled = false;
  }
}

async function _demoParse() {
  if (!demoState.syslog) return;
  const hintEl = document.getElementById("demo-nav-hint");
  if (hintEl) hintEl.textContent = "Parsing syslog…";

  try {
    const resp = await fetch("/demo/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ syslog: demoState.syslog }),
    });
    if (resp.ok) {
      const data = await resp.json();
      demoState.parsed  = data.parsed  || null;
      demoState.webhook = data.webhook || null;
      _renderDemoFieldMap();
      _renderDemoDataReveal();
      _setDemoNavButtons();
    }
  } catch (_) {
    // non-fatal; user can see error in console
  }
}

async function _demoEnforce() {
  if (!demoState.webhook) return;
  try {
    const resp = await fetch("/demo/enforce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(demoState.webhook),
    });
    if (resp.ok) {
      const data = await resp.json();
      demoState.enforcements = data.enforcements || [];
      _renderDemoEnfCards();
    }
  } catch (_) {
    // non-fatal
  }
}

async function advanceStep() {
  if (demoState.step === 0) { startDemo(); return; }
  if (demoState.step === 4) { resetDemo(); return; }
  if (!_demoStepComplete()) return;
  demoState.step++;
  _renderDemoStep();

  if (demoState.step === 2) await _demoParse();
  if (demoState.step === 3) await _demoEnforce();
  // Step 4: user must manually click "Trigger Revocation" — no auto-fire
}

function goBackStep() {
  if (demoState.step <= 0) return;
  demoState.step--;
  _renderDemoStep();
  // Re-render cached step data (no re-fetch)
  if (demoState.step === 2) { _renderDemoFieldMap(); _renderDemoDataReveal(); }
  if (demoState.step === 3) { _renderDemoEnfCards(); }
  if (demoState.step === 4) { _renderDemoRevokeCards(); _renderDemoDataReveal(); }
}

function resetDemo() {
  demoState = {
    step: 0, syslog: null, request: null, parsed: null,
    webhook: null, enforcements: null,
    revoke_enforcements: null, revoke_type: "logout",
  };
  clearConsole();
  const statusEl = document.getElementById("demo-auth-status");
  if (statusEl) statusEl.textContent = "";
  _renderDemoStep();
}

// ─── Step 4: Revocation ───────────────────────────────────────────────────────

function selectRevokeType(type) {
  demoState.revoke_type = type;
  document.querySelectorAll(".revoke-trigger-card").forEach((c) => {
    c.classList.toggle("active", c.dataset.rtype === type);
  });
}

function _renderRevokeSessionInfo() {
  const el = document.getElementById("demo-revoke-session-info");
  if (!el || !demoState.request) { if (el) el.style.display = "none"; return; }
  const r = demoState.request;
  el.style.display = "";
  el.innerHTML = `
    <div class="revoke-session-pill">
      <span class="rsp-label">Session to revoke</span>
      <span class="rsp-field">${_esc(r.username)}</span>
      <span class="rsp-sep">@</span>
      <span class="rsp-field">${_esc(r.target_app)}</span>
      <span class="rsp-sep">from</span>
      <span class="rsp-field rsp-ip">${_esc(r.source_ip)}</span>
    </div>`;
}

async function _demoRevoke() {
  if (!demoState.webhook) return;

  const btn      = document.getElementById("btn-demo-revoke");
  const statusEl = document.getElementById("demo-revoke-status");
  if (btn) btn.disabled = true;
  if (statusEl) { statusEl.style.color = "var(--text-muted)"; statusEl.textContent = "Generating revocation payloads…"; }

  // Build LOGOUT webhook from the step-2 webhook, overriding action
  const logoutWebhook = { ...demoState.webhook, action: "LOGOUT" };

  try {
    const resp = await fetch("/demo/enforce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(logoutWebhook),
    });
    if (resp.ok) {
      const data = await resp.json();
      demoState.revoke_enforcements = data.enforcements || [];
      if (statusEl) { statusEl.style.color = "var(--text-success)"; statusEl.textContent = "✓ Revocation payloads generated — access withdrawn"; }
      _renderDemoRevokeCards();
      _renderDemoDataReveal();
      _setDemoNavButtons();
    } else {
      if (statusEl) { statusEl.style.color = "var(--text-error)"; statusEl.textContent = "Error generating revocation payloads"; }
    }
  } catch (err) {
    if (statusEl) { statusEl.style.color = "var(--text-error)"; statusEl.textContent = `Network error: ${String(err.message)}`; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _renderDemoRevokeCards() {
  const container = document.getElementById("demo-revoke-cards");
  if (!container || !demoState.revoke_enforcements) return;
  container.textContent = "";

  const hdr = document.createElement("div");
  hdr.className   = "demo-reveal-label";
  hdr.textContent = "LOGOUT Enforcement Payloads";
  hdr.style.cssText = "margin-top:14px; margin-bottom:8px;";
  container.appendChild(hdr);

  const METHOD_CLASS = { "PATCH": "", "PUT": "method-put" };

  demoState.revoke_enforcements.forEach((e) => {
    const card = document.createElement("div");
    card.className = "payload-card populated revoke-card";

    const hd = document.createElement("div");
    hd.className = "card-hd";

    const sys = document.createElement("span");
    sys.className   = "card-sys";
    sys.textContent = typeof e.system === "string" ? e.system.replace(/[<>]/g, "") : "System";

    const badge = document.createElement("span");
    const meth = typeof e.method === "string" ? e.method.replace(/[^A-Z]/g, "") : "?";
    badge.className   = `method-badge ${METHOD_CLASS[meth] || ""}`;
    badge.textContent = meth;

    hd.appendChild(sys);
    hd.appendChild(badge);

    const urlEl = document.createElement("div");
    urlEl.className   = "card-url";
    urlEl.textContent = typeof e.url === "string" ? e.url : "";

    const body = document.createElement("div");
    body.className = "card-body";
    if (e.payload && typeof e.payload === "object") {
      buildJSONTree(e.payload, body);
    }

    card.appendChild(hd);
    card.appendChild(urlEl);
    card.appendChild(body);
    container.appendChild(card);
  });
}

function _renderRevokeDelta(container) {
  // Show a side-by-side comparison of LOGIN vs LOGOUT payloads
  if (!demoState.enforcements || !demoState.revoke_enforcements) return;

  const SYSTEMS = [
    { name: "NSX GFW / DFW", login: null, logout: null },
    { name: "AVI Load Balancer", login: null, logout: null },
  ];

  // NSX (take first enforcement as representative)
  const nsxLogin  = demoState.enforcements.find(e => e.system.includes("Gateway"));
  const nsxLogout = demoState.revoke_enforcements.find(e => e.system.includes("Gateway"));
  // AVI
  const aviLogin  = demoState.enforcements.find(e => e.system.includes("AVI"));
  const aviLogout = demoState.revoke_enforcements.find(e => e.system.includes("AVI"));

  [[nsxLogin, nsxLogout, "NSX ip_addresses"], [aviLogin, aviLogout, "AVI addrs"]].forEach(([login, logout, label]) => {
    if (!login || !logout) return;

    const row = document.createElement("div");
    row.className = "revoke-delta-row";

    const rowLabel = document.createElement("div");
    rowLabel.className   = "revoke-delta-label";
    rowLabel.textContent = label;
    row.appendChild(rowLabel);

    const cols = document.createElement("div");
    cols.className = "revoke-delta-cols";

    const mkCol = (title, payload, isLogout) => {
      const col = document.createElement("div");
      col.className = `revoke-delta-col ${isLogout ? "revoke-delta-col-out" : "revoke-delta-col-in"}`;
      const colHd = document.createElement("div");
      colHd.className   = "revoke-delta-col-hd";
      colHd.textContent = title;
      const colBd = document.createElement("div");
      colBd.className = "code-block";
      colBd.style.cssText = "margin-top:4px; background:#000; color:#c8d6e5; font-size:0.62rem; max-height:120px;";
      buildJSONTree(payload, colBd);
      col.appendChild(colHd);
      col.appendChild(colBd);
      return col;
    };

    cols.appendChild(mkCol("LOGIN (grant)", login.payload, false));
    cols.appendChild(mkCol("LOGOUT (revoke)", logout.payload, true));
    row.appendChild(cols);
    container.appendChild(row);
  });
}

// Initialise demo view on load
document.addEventListener("DOMContentLoaded", () => { _renderDemoStep(); });

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

// ─── Settings & Sessions ──────────────────────────────────────────────────────
let _sessionsRefreshTimer = null;

function handleSessionEvent() {
  // Auto-refresh sessions table if Active Sessions view is active
  if (document.getElementById("view-active-sessions")?.classList.contains("active")) {
    refreshSessions();
  }
}

function switchSettingsTab(name) {
  document.querySelectorAll(".stab").forEach((t) => t.classList.toggle("active", t.dataset.stab === name));
  document.querySelectorAll(".stab-panel").forEach((p) => p.classList.toggle("active", p.id === `stab-${name}`));
}

async function loadSettings() {
  try {
    const res = await fetch("/sessions/settings");
    if (!res.ok) return;
    const s = await res.json();
    const ttl  = document.getElementById("cfg-ttl");
    const poll = document.getElementById("cfg-poll");
    const mode = document.getElementById("cfg-mode");
    const auto = document.getElementById("cfg-auto-enforce");
    if (ttl)  ttl.value   = s.ttl_seconds;
    if (poll) poll.value  = s.poll_interval_seconds;
    if (mode) mode.value  = s.mode;
    if (auto) auto.checked = s.auto_enforce;
  } catch (_) {}
}

async function saveSettings(e) {
  e.preventDefault();
  const statusEl = document.getElementById("settings-status");
  const body = {
    ttl_seconds:          parseInt(document.getElementById("cfg-ttl").value, 10),
    poll_interval_seconds: parseInt(document.getElementById("cfg-poll").value, 10),
    mode:                 document.getElementById("cfg-mode").value,
    auto_enforce:         document.getElementById("cfg-auto-enforce").checked,
  };
  try {
    const res = await fetch("/sessions/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      if (statusEl) { statusEl.style.color = "var(--text-success)"; statusEl.textContent = "Saved."; }
      setTimeout(() => { if (statusEl) statusEl.textContent = ""; }, 2000);
    } else {
      if (statusEl) { statusEl.style.color = "var(--text-error)"; statusEl.textContent = "Save failed."; }
    }
  } catch (err) {
    if (statusEl) { statusEl.style.color = "var(--text-error)"; statusEl.textContent = "Network error."; }
  }
}

async function refreshSessions() {
  try {
    const res = await fetch("/sessions/?exclude_demo=true");
    if (!res.ok) return;
    const sessions = await res.json();
    _lastSessionsList = sessions;
    _renderSessionsTable(sessions);
  } catch (_) {}
}

function _renderSessionsTable(sessions) {
  const tbody = document.getElementById("sessions-tbody");
  const countEl = document.getElementById("sessions-count");
  if (!tbody) return;

  const active = sessions.filter(s => s.status === "active").length;
  if (countEl) countEl.textContent = `${active} active`;

  if (sessions.length === 0) {
    tbody.innerHTML = `<tr class="sessions-empty"><td colspan="7">No sessions yet — submit a LOGIN event to register one.</td></tr>`;
    return;
  }

  tbody.innerHTML = sessions.map(s => {
    const elapsed = _formatElapsed(s.elapsed_seconds);
    const badgeClass = `session-badge session-badge-${s.status}`;
    const isKillable = s.status === "active";
    const killBtn = isKillable
      ? `<button class="btn-kill" onclick="killSession('${s.session_id}')">Kill</button>`
      : `<button class="btn-kill" disabled>Kill</button>`;
    return `<tr>
      <td>${_esc(s.username)}</td>
      <td>${_esc(s.target_app)}</td>
      <td>${_esc(s.source_ip)}</td>
      <td><span class="${badgeClass}">${s.status}</span></td>
      <td>${elapsed}</td>
      <td style="color:var(--text-muted); font-size:0.62rem;">${_esc(s.source)}</td>
      <td>${killBtn}</td>
    </tr>`;
  }).join("");
}

function _formatElapsed(secs) {
  if (secs < 60) return `${Math.floor(secs)}s`;
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}m ${s}s`;
}

function _esc(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

async function killSession(sessionId) {
  try {
    const res = await fetch(`/sessions/${sessionId}/kill`, { method: "POST" });
    if (res.ok) refreshSessions();
  } catch (_) {}
}

// ─── Sessions auto-refresh ────────────────────────────────────────────────────
function startSessionsAutoRefresh() {
  clearInterval(_sessionsRefreshTimer);
  _sessionsRefreshTimer = setInterval(() => {
    if (document.getElementById("view-active-sessions")?.classList.contains("active")) {
      refreshSessions();
    } else {
      clearInterval(_sessionsRefreshTimer);
    }
  }, 5000);
}

// ─── AVI Policy view ──────────────────────────────────────────────────────────
let _cachedIpGroups  = [];
let _expandedNspData = null;
let _nspAllResults   = [];
let _nspPage         = 0;
let _nspRowsPerPage  = 10;
let _nspSearchTerm   = "";

// ── Modal helpers ──────────────────────────────────────────────────────────────
function openModal(html) {
  const content = document.getElementById("modal-content");
  if (!content) return;
  content.innerHTML = html;
  document.getElementById("modal-overlay")?.classList.add("open");
}

function closeModal() {
  document.getElementById("modal-overlay")?.classList.remove("open");
  document.getElementById("modal-content").innerHTML = "";
  _expandedNspData = null;
}

// ── Toast notifications ────────────────────────────────────────────────────────
function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-visible"));
  setTimeout(() => {
    toast.classList.add("toast-exit");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
  }, 3500);
}

// ── Confirm dialog (modal-based, returns Promise<boolean>) ─────────────────────
function showConfirm(message) {
  return new Promise((resolve) => {
    const content = document.getElementById("modal-content");
    if (!content) { resolve(false); return; }
    content.innerHTML = `
      <div style="font-size:0.85rem; line-height:1.55; margin-bottom:20px;">${_esc(message)}</div>
      <div style="display:flex; justify-content:flex-end; gap:8px;">
        <button class="btn-small btn-secondary" id="confirm-cancel">Cancel</button>
        <button class="btn-small btn-danger" id="confirm-ok">Confirm</button>
      </div>`;
    document.getElementById("modal-overlay")?.classList.add("open");
    document.getElementById("confirm-ok").onclick = () => { closeModal(); resolve(true); };
    document.getElementById("confirm-cancel").onclick = () => { closeModal(); resolve(false); };
  });
}

// ── Mini-diagram step highlighting ────────────────────────────────────────────
function updateMiniDiagram(step) {
  const mini = document.getElementById("mini-diagram");
  if (!mini) return;
  mini.style.display = step >= 1 ? "" : "none";
  document.querySelectorAll(".md-node").forEach(n => n.classList.remove("md-active"));
  const nodes = MINI_DIAGRAM_STEPS[step] || [];
  nodes.forEach(id => document.getElementById(id)?.classList.add("md-active"));
}

// ── Init ───────────────────────────────────────────────────────────────────────
async function loadAviPolicyView() {
  await Promise.all([
    refreshAviIpAddrGroups(),
    refreshAviPolicies(),
    refreshAviVirtualServices(),
    refreshMappings(),
  ]);
}

// ── IP Address Groups ──────────────────────────────────────────────────────────
async function refreshAviIpAddrGroups() {
  try {
    const res = await fetch("/avi-policy/ipaddrgroups");
    if (!res.ok) { _cachedIpGroups = []; return; }
    const data = await res.json();
    _cachedIpGroups = data.results || [];
  } catch (_) {
    _cachedIpGroups = [];
  }
}

// ── Policies table ─────────────────────────────────────────────────────────────
async function refreshAviPolicies() {
  const wrap = document.getElementById("avi-nsp-table-wrap");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted-hint">Loading…</p>';
  try {
    const res = await fetch("/avi-policy/networksecuritypolicies");
    if (!res.ok) { wrap.innerHTML = '<p class="muted-hint">AVI not connected.</p>'; return; }
    const data = await res.json();
    _nspAllResults = data.results || [];
    _nspPage = 0;
    renderNspTable();
  } catch (_) {
    wrap.innerHTML = '<p class="muted-hint">Error loading policies.</p>';
  }
}

function renderNspTable() {
  const wrap = document.getElementById("avi-nsp-table-wrap");
  if (!wrap) return;

  const filtered = _nspAllResults.filter(p =>
    !_nspSearchTerm || p.name.toLowerCase().includes(_nspSearchTerm.toLowerCase())
  );
  const total   = filtered.length;
  const pages   = Math.max(1, Math.ceil(total / _nspRowsPerPage));
  if (_nspPage >= pages) _nspPage = pages - 1;
  const start   = _nspPage * _nspRowsPerPage;
  const slice   = filtered.slice(start, start + _nspRowsPerPage);

  if (!total) {
    wrap.innerHTML = '<p class="muted-hint">No policies found.</p>';
    return;
  }

  const rows = slice.map(p => {
    const uuid = p.uuid || (p.url || "").split("/").filter(Boolean).pop() || "";
    const ruleCount = (p.rules || []).length;
    return `<tr style="cursor:pointer;" onclick="openEditNspModal('${_esc(uuid)}')">
      <td>${_esc(p.name)}</td>
      <td>${ruleCount} rule${ruleCount !== 1 ? "s" : ""}</td>
      <td>
        <button class="btn-small" onclick="event.stopPropagation();openEditNspModal('${_esc(uuid)}')">Edit</button>
        <button class="btn-small btn-danger" onclick="event.stopPropagation();deleteNsp('${_esc(uuid)}')">Delete</button>
      </td>
    </tr>`;
  }).join("");

  const showStart = total ? start + 1 : 0;
  const showEnd   = Math.min(start + _nspRowsPerPage, total);

  wrap.innerHTML = `
    <table class="nsp-table">
      <thead><tr><th>Name</th><th>Rules</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="nsp-pagination">
      <span>Showing ${showStart}–${showEnd} of ${total}</span>
      <div class="nsp-pagination-controls">
        <label>Rows:
          <select onchange="onNspRowsPerPage(this.value)">
            ${[10,20,30].map(n => `<option value="${n}" ${n===_nspRowsPerPage?"selected":""}>${n}</option>`).join("")}
          </select>
        </label>
        <button onclick="onNspPrevPage()" ${_nspPage === 0 ? "disabled" : ""}>&#9664; Prev</button>
        <button onclick="onNspNextPage()" ${_nspPage >= pages-1 ? "disabled" : ""}>Next &#9654;</button>
      </div>
    </div>`;
}

function onNspSearch(value) {
  _nspSearchTerm = value;
  _nspPage = 0;
  renderNspTable();
}

function onNspRowsPerPage(value) {
  _nspRowsPerPage = parseInt(value, 10) || 10;
  _nspPage = 0;
  renderNspTable();
}

function onNspPrevPage() { if (_nspPage > 0) { _nspPage--; renderNspTable(); } }
function onNspNextPage() {
  const pages = Math.ceil(_nspAllResults.filter(p =>
    !_nspSearchTerm || p.name.toLowerCase().includes(_nspSearchTerm.toLowerCase())
  ).length / _nspRowsPerPage);
  if (_nspPage < pages - 1) { _nspPage++; renderNspTable(); }
}

// ── Create NSP modal ───────────────────────────────────────────────────────────
function openCreateNspModal() {
  const groupOptions = _cachedIpGroups.map(g =>
    `<option value="${_esc(g.url)}">${_esc(g.name)}</option>`
  ).join("");

  openModal(`
    <h3 style="margin:0 0 14px;">Create Network Security Policy</h3>
    <div class="modal-form-row">
      <label>Policy Name</label>
      <input id="modal-nsp-name" type="text" placeholder="e.g. allow-hr-users" style="width:100%;">
    </div>
    <div class="modal-form-row" style="margin-top:10px;">
      <label>IP Address Group</label>
      <div class="modal-ipgroup-row">
        <select id="modal-nsp-ipgroup" style="flex:1;">
          <option value="">— select group (optional) —</option>
          ${groupOptions}
        </select>
        <button class="btn-small" onclick="toggleModalIpGroupForm()">+ New Group</button>
      </div>
    </div>
    <div id="modal-ipgroup-inline" class="modal-ipgroup-inline" style="display:none; margin-top:8px;">
      <input id="modal-ipg-name" type="text" placeholder="Group name" style="width:48%;">
      <input id="modal-ipg-addrs" type="text" placeholder="IPs, comma-separated (optional)" style="width:48%;">
      <button class="btn-small" onclick="createIpAddrGroupFromModal()" style="margin-top:6px;">Create Group</button>
      <span id="modal-ipg-status" style="font-size:0.65rem; color:var(--text-muted); margin-left:6px;"></span>
    </div>
    <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:18px;">
      <button class="btn-small" onclick="closeModal()">Cancel</button>
      <button class="btn-small btn-primary" onclick="submitCreateNsp()">Create Policy</button>
    </div>`);
}

function toggleModalIpGroupForm() {
  const el = document.getElementById("modal-ipgroup-inline");
  if (el) el.style.display = el.style.display === "none" ? "" : "none";
}

async function createIpAddrGroupFromModal() {
  const name   = document.getElementById("modal-ipg-name")?.value.trim();
  const raw    = document.getElementById("modal-ipg-addrs")?.value || "";
  const addrs  = raw.split(",").map(s => s.trim()).filter(Boolean);
  const status = document.getElementById("modal-ipg-status");
  if (!name) { if (status) status.textContent = "Name required."; return; }
  if (status) status.textContent = "Creating…";
  try {
    const res = await fetch("/avi-policy/ipaddrgroups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, addrs }),
    });
    if (!res.ok) {
      const err = await res.json();
      if (status) status.textContent = "Error: " + (err.detail || res.status);
      return;
    }
    const data = await res.json();
    await refreshAviIpAddrGroups();
    const newUrl = data.body?.url || "";
    const sel = document.getElementById("modal-nsp-ipgroup");
    if (sel) {
      sel.innerHTML = '<option value="">— select group (optional) —</option>' +
        _cachedIpGroups.map(g => `<option value="${_esc(g.url)}" ${g.url===newUrl?"selected":""}>${_esc(g.name)}</option>`).join("");
    }
    document.getElementById("modal-ipgroup-inline").style.display = "none";
    document.getElementById("modal-ipg-name").value = "";
    document.getElementById("modal-ipg-addrs").value = "";
    if (status) status.textContent = "";
  } catch (ex) {
    if (status) status.textContent = "Request failed: " + ex.message;
  }
}

async function submitCreateNsp() {
  const name    = document.getElementById("modal-nsp-name")?.value.trim();
  const ipgroup = document.getElementById("modal-nsp-ipgroup")?.value.trim();
  if (!name) { showToast("Policy name is required.", "error"); return; }
  try {
    const res = await fetch("/avi-policy/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, ipaddrgroup_ref: ipgroup || "" }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Error: " + (err.detail || res.status), "error");
      return;
    }
    closeModal();
    showToast(`Policy '${name}' created`, "success");
    await Promise.all([refreshAviPolicies(), refreshAviVirtualServices()]);
  } catch (ex) {
    showToast("Request failed: " + ex.message, "error");
  }
}

// ── Edit NSP modal ─────────────────────────────────────────────────────────────
async function openEditNspModal(uuid) {
  openModal('<p class="muted-hint" style="padding:20px;">Loading…</p>');
  try {
    const res = await fetch(`/avi-policy/networksecuritypolicies/${uuid}/references`);
    if (!res.ok) { openModal('<p class="muted-hint">Failed to load policy.</p>'); return; }
    const data = await res.json();
    _expandedNspData = data.result;
    const referredVs = data.referred_by_vs || [];
    _renderEditNspModal(uuid, _expandedNspData, referredVs);
  } catch (ex) {
    openModal(`<p class="muted-hint">Error: ${_esc(ex.message)}</p>`);
  }
}

function _renderEditNspModal(uuid, nspData, referredVs) {
  const rules = nspData.rules || [];

  const rulesHtml = rules.length ? rules.map((rule, idx) => {
    const isAllow  = (rule.action || "").includes("ALLOW");
    const disabled = rule.enable === false;
    const groupRefs = rule.match?.client_ip?.group_refs || [];
    let matchHtml = "";
    if (groupRefs.length) {
      const currentRef = groupRefs[0] || "";
      matchHtml = `<select class="nsp-rule-ipgroup" onchange="changeRuleGroupRef('${_esc(uuid)}',${idx},this.value)">
        ${_cachedIpGroups.map(g => `<option value="${_esc(g.url)}" ${g.url===currentRef?"selected":""}>${_esc(g.name)}</option>`).join("")}
        ${!_cachedIpGroups.some(g => g.url===currentRef) && currentRef
          ? `<option value="${_esc(currentRef)}" selected>${_esc(currentRef.split("/").pop())}</option>` : ""}
      </select>`;
    } else {
      const prefixes = rule.match?.client_ip?.prefixes || [];
      matchHtml = `<span style="font-size:0.62rem;color:var(--text-muted);">${prefixes.map(p=>`${p.ip_addr?.addr||""}/${p.mask??""}`).join(", ")||"—"}</span>`;
    }
    return `<div class="modal-rule-row${disabled?" disabled":""}">
      <span class="nsp-rule-badge ${isAllow?"allow":"deny"}">${isAllow?"ALLOW":"DENY"}</span>
      <span class="nsp-rule-name" style="flex:1;">${_esc(rule.name||`rule-${idx}`)}</span>
      ${matchHtml}
      <button class="nsp-rule-toggle" onclick="toggleRuleEnable('${_esc(uuid)}',${idx})">${disabled?"Enable":"Disable"}</button>
    </div>`;
  }).join("") : '<p class="muted-hint" style="margin:4px 0;">No rules.</p>';

  const vsHtml = referredVs.length
    ? referredVs.map(vs => `
        <div class="modal-vs-item">
          <span>${_esc(vs.name || vs.uuid || vs.url)}</span>
          <button class="btn-small btn-danger" onclick="detachPolicyFromVs('${_esc(vs.uuid||"")}','${_esc(uuid)}')">Detach</button>
        </div>`).join("")
    : '<p class="muted-hint" style="margin:4px 0;">Not attached to any Virtual Service.</p>';

  openModal(`
    <h3 style="margin:0 0 4px;">Edit Policy</h3>
    <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:14px;">${_esc(nspData.name||uuid)}</div>
    <div class="modal-section-label">Rules</div>
    <div style="margin-bottom:14px;">${rulesHtml}</div>
    <div class="modal-section-label">Virtual Services</div>
    <div class="modal-vs-list">${vsHtml}</div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
      <button class="btn-small" onclick="closeModal()">Close</button>
      <button class="btn-small btn-danger" onclick="deleteNsp('${_esc(uuid)}')">Delete Policy</button>
    </div>`);
}

async function detachPolicyFromVs(vsUuid, nspUuid) {
  try {
    const res = await fetch("/avi-policy/detach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vs_uuid: vsUuid }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast("Detach error: " + (err.detail || res.status), "error");
      return;
    }
    showToast("Policy detached from Virtual Service", "success");
    // Re-fetch and re-render the edit modal with updated VS list
    await openEditNspModal(nspUuid);
  } catch (ex) {
    showToast("Request failed: " + ex.message, "error");
  }
}

async function toggleRuleEnable(uuid, ruleIdx) {
  if (!_expandedNspData) return;
  const rule = _expandedNspData.rules?.[ruleIdx];
  if (!rule) return;
  rule.enable = !rule.enable;
  try {
    const res = await fetch(`/avi-policy/networksecuritypolicies/${uuid}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_expandedNspData),
    });
    if (!res.ok) {
      rule.enable = !rule.enable;
      const err = await res.json();
      showToast("Error: " + (err.detail || res.status), "error");
      return;
    }
    const data = await res.json();
    _expandedNspData = data.body || _expandedNspData;
    await openEditNspModal(uuid);
  } catch (ex) {
    rule.enable = !rule.enable;
    showToast("Request failed: " + ex.message, "error");
  }
}

async function changeRuleGroupRef(uuid, ruleIdx, newRef) {
  if (!_expandedNspData) return;
  const rule = _expandedNspData.rules?.[ruleIdx];
  if (!rule || !rule.match?.client_ip) return;
  const prev = [...(rule.match.client_ip.group_refs || [])];
  rule.match.client_ip.group_refs = [newRef];
  try {
    const res = await fetch(`/avi-policy/networksecuritypolicies/${uuid}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_expandedNspData),
    });
    if (!res.ok) {
      rule.match.client_ip.group_refs = prev;
      const err = await res.json();
      showToast("Error: " + (err.detail || res.status), "error");
      return;
    }
    const data = await res.json();
    _expandedNspData = data.body || _expandedNspData;
    await openEditNspModal(uuid);
  } catch (ex) {
    rule.match.client_ip.group_refs = prev;
    showToast("Request failed: " + ex.message, "error");
  }
}

async function deleteNsp(uuid) {
  // Check VS references — AVI will return 403 if still attached
  let referredVs = [];
  try {
    const refRes = await fetch(`/avi-policy/networksecuritypolicies/${uuid}/references`);
    if (refRes.ok) {
      const refData = await refRes.json();
      referredVs = refData.referred_by_vs || [];
    }
  } catch (_) {}

  if (referredVs.length) {
    const names = referredVs.map(v => v.name || v.uuid || v.url).join(", ");
    showToast(`Cannot delete — still attached to: ${names}. Detach first.`, "error");
    return;
  }

  const ok = await showConfirm("Delete this policy from AVI? This cannot be undone.");
  if (!ok) return;

  try {
    const res = await fetch(`/avi-policy/networksecuritypolicies/${uuid}`, { method: "DELETE" });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const err = await res.json();
        msg = err.detail || err.error || msg;
      } catch (_) {}
      showToast("Delete failed: " + msg, "error");
      return;
    }
    closeModal();
    showToast("Policy deleted", "success");
    await Promise.all([refreshAviPolicies(), refreshAviVirtualServices()]);
  } catch (ex) {
    showToast("Request failed: " + ex.message, "error");
  }
}

async function refreshAviVirtualServices() {
  const policyDropdown = document.getElementById("attach-policy");
  const vsDropdown     = document.getElementById("attach-vs");
  const promises = [];

  if (policyDropdown) {
    promises.push(
      fetch("/avi-policy/networksecuritypolicies").then(r => r.ok ? r.json() : null).then(data => {
        if (!data) { policyDropdown.innerHTML = '<option value="">— AVI not connected —</option>'; return; }
        policyDropdown.innerHTML = '<option value="">— select policy —</option>' +
          (data.results || []).map(p =>
            `<option value="${_esc(p.url)}">${_esc(p.name)}</option>`
          ).join("");
      }).catch(() => { policyDropdown.innerHTML = '<option value="">— error —</option>'; })
    );
  }

  if (vsDropdown) {
    promises.push(
      fetch("/avi-policy/virtualservices").then(r => r.ok ? r.json() : null).then(data => {
        if (!data) { vsDropdown.innerHTML = '<option value="">— AVI not connected —</option>'; return; }
        vsDropdown.innerHTML = '<option value="">— select VS —</option>' +
          (data.results || []).map(vs =>
            `<option value="${_esc(vs.uuid)}" data-name="${_esc(vs.name)}">${_esc(vs.name)}</option>`
          ).join("");
      }).catch(() => { vsDropdown.innerHTML = '<option value="">— error —</option>'; })
    );
  }

  await Promise.all(promises);
}

async function attachPolicyToVS(e) {
  e.preventDefault();
  const policyRef = document.getElementById("attach-policy")?.value.trim();
  const vsUuid    = document.getElementById("attach-vs")?.value.trim();
  const targetApp = document.getElementById("attach-target-app")?.value.trim();

  const vsEl = document.getElementById("attach-vs");
  const vsName = vsEl?.options[vsEl.selectedIndex]?.dataset.name || vsUuid;

  const policyEl = document.getElementById("attach-policy");
  const policyName = policyEl?.options[policyEl.selectedIndex]?.text || policyRef;

  if (!policyRef || !vsUuid || !targetApp) return;

  try {
    const attachRes = await fetch("/avi-policy/attach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vs_uuid: vsUuid, policy_ref: policyRef }),
    });
    if (!attachRes.ok) {
      const err = await attachRes.json();
      showToast("Attach error: " + (err.detail || attachRes.status), "error");
      return;
    }

    await fetch("/avi-policy/mappings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_app:       targetApp,
        vs_name:          vsName,
        vs_uuid:          vsUuid,
        policy_name:      policyName,
        policy_uuid:      policyRef.split("/").pop() || policyRef,
        ipaddrgroup_name: "",
        ipaddrgroup_ref:  "",
      }),
    });

    showToast("Policy attached to Virtual Service", "success");
    await refreshMappings();
  } catch (ex) {
    showToast("Request failed: " + ex.message, "error");
  }
}

async function refreshMappings() {
  const tbody = document.getElementById("mappings-tbody");
  if (!tbody) return;
  try {
    const res = await fetch("/avi-policy/mappings");
    if (!res.ok) { tbody.innerHTML = '<tr><td colspan="5">Error loading.</td></tr>'; return; }
    const rows = await res.json();
    if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="muted-hint">No mappings saved.</td></tr>'; return; }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${_esc(r.target_app)}</td>
        <td>${_esc(r.vs_name)}</td>
        <td>${_esc(r.policy_name)}</td>
        <td>${new Date(r.created_at).toLocaleString()}</td>
        <td><button class="btn-small btn-danger" onclick="deleteMapping(${r.id})">Delete</button></td>
      </tr>`).join("");
  } catch (_) {
    tbody.innerHTML = '<tr><td colspan="5">Error loading.</td></tr>';
  }
}

async function deleteMapping(id) {
  try {
    await fetch(`/avi-policy/mappings/${id}`, { method: "DELETE" });
    await refreshMappings();
  } catch (_) {}
}

// ─── Init ─────────────────────────────────────────────────────────────────────
connectSSE();
updateJITPreview();
refreshEnforceFooterStatus();
