import json
import re

from pydantic import BaseModel, ConfigDict, model_validator


_IP_RE = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b')

# AVI WAF field names that carry the client IP, in priority order
_CLIENT_IP_FIELD_NAMES = (
    "client_ip",          # primary AVI WAF field
    "client_src_ip",      # AVI variant
    "clientip",
    "ClientIP",
    "client_addr",
    "src_ip",
)

# X-Forwarded-For header field name as recorded by AVI
_XFF_FIELD = "srv_req_hdr_x-forwarded-for"

# waf_tags token → human attack_type label
_WAF_TAG_MAP = {
    "attack-xss":    "XSS",
    "attack-sqli":   "SQLi",
    "attack-rce":    "RCE",
    "attack-lfi":    "LFI",
    "attack-rfi":    "RFI",
    "attack-ssrf":   "SSRF",
    "attack-dos":    "DoS",
    "attack-fixation": "Session Fixation",
    "attack-injection": "Injection",
    "attack-disclosure": "Info Disclosure",
}


def _named_fields_to_dict(fields: list) -> dict:
    """Convert [{"name": "k", "content": "v"}, ...] → {"k": "v"}."""
    result = {}
    for f in fields:
        if isinstance(f, dict) and "name" in f:
            result[f["name"]] = f.get("content", "")
    return result


def _parse_attack_type(waf_tags: str) -> str | None:
    if not waf_tags:
        return None
    for tag, label in _WAF_TAG_MAP.items():
        if tag in waf_tags:
            return label
    return None


def _first_ip(value: str) -> str | None:
    """Return first IPv4 from a possibly comma-separated string."""
    if not value:
        return None
    m = _IP_RE.search(value)
    return m.group(1) if m else None


class _WAFFields:
    """Parsed enrichment extracted from a single AVI WAF log entry's fields array."""
    __slots__ = ("client_ip", "attack_type", "rule_id", "virtual_service", "pool_name", "request_id")

    def __init__(self):
        self.client_ip: str | None = None
        self.attack_type: str | None = None
        self.rule_id: str | None = None
        self.virtual_service: str | None = None
        self.pool_name: str | None = None
        self.request_id: str | None = None


def _extract_from_entry(entry: dict) -> _WAFFields:
    """Extract enrichment from one Log Insight message entry."""
    result = _WAFFields()

    # Build a flat dict from the nested fields array if present
    flat: dict = {}
    raw_fields = entry.get("fields")
    if isinstance(raw_fields, list):
        flat = _named_fields_to_dict(raw_fields)
    # Also accept entries that are already flat dicts
    flat_entry = {k: v for k, v in entry.items() if k != "fields"}
    merged = {**flat_entry, **flat}   # fields array takes priority

    # ── Client IP ────────────────────────────────────────────────────────────
    for key in _CLIENT_IP_FIELD_NAMES:
        val = merged.get(key, "")
        ip = _first_ip(str(val)) if val else None
        if ip:
            result.client_ip = ip
            break
    # Fallback: X-Forwarded-For header captured by AVI
    if not result.client_ip:
        result.client_ip = _first_ip(merged.get(_XFF_FIELD, ""))

    # ── Attack type from waf_tags ─────────────────────────────────────────────
    result.attack_type = _parse_attack_type(merged.get("waf_tags", ""))

    # ── First WAF rule ID ────────────────────────────────────────────────────
    for key in ("waf_rule_1_id", "waf_rule_2_id", "waf_rule_3_id", "rule_id"):
        val = merged.get(key, "")
        if val:
            result.rule_id = str(val)
            break

    # ── Virtual service / pool ───────────────────────────────────────────────
    result.virtual_service = merged.get("vs_name") or merged.get("virtual_service") or None
    result.pool_name = merged.get("pool_name") or None
    result.request_id = merged.get("request_id") or None

    return result


def _extract_from_messages(messages_raw) -> _WAFFields:
    """Walk all messages entries and return enrichment from the first useful one."""
    empty = _WAFFields()
    if not messages_raw:
        return empty

    if isinstance(messages_raw, str):
        try:
            messages_raw = json.loads(messages_raw)
        except (json.JSONDecodeError, ValueError):
            ip = _first_ip(messages_raw)
            if ip:
                empty.client_ip = ip
            return empty

    if not isinstance(messages_raw, list):
        return empty

    for entry in messages_raw:
        if not isinstance(entry, dict):
            continue
        result = _extract_from_entry(entry)
        if result.client_ip:
            return result   # first entry with a resolved IP wins

    return empty


class WAFWebhookPayload(BaseModel):
    """
    Accepts Log Insight's default webhook body plus any custom template fields.

    Log Insight delivers each triggering AVI WAF log entry as:
      {"text": "...", "fields": [{"name": "client_ip", "content": "x.x.x.x"}, ...]}

    client_ip is extracted from those fields. attack_type, rule_id, and
    virtual_service are also auto-populated from the WAF log fields so the
    SSE console shows useful context without any template configuration.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_ip: str | None = None          # resolved client IP
    alert_type: str | None = None
    alert_name: str | None = None
    search_period: str | None = None
    hit_operator: str | None = None
    messages: object | None = None

    # Enrichment — auto-populated from WAF log fields or set by custom template
    target_app: str | None = None
    rule_id: str | None = None
    attack_type: str | None = None
    severity: str | None = None
    virtual_service: str | None = None
    pool_name: str | None = None
    request_id: str | None = None
    description: str | None = None
    event_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: dict) -> dict:
        if "hit_oeprator" in data and "hit_operator" not in data:
            data["hit_operator"] = data.pop("hit_oeprator")
        return data

    @model_validator(mode="after")
    def _enrich_from_messages(self) -> "WAFWebhookPayload":
        extracted = _extract_from_messages(self.messages)
        if not self.source_ip:
            self.source_ip = extracted.client_ip
        if not self.attack_type:
            self.attack_type = extracted.attack_type
        if not self.rule_id:
            self.rule_id = extracted.rule_id
        if not self.virtual_service:
            self.virtual_service = extracted.virtual_service
        if not self.pool_name:
            self.pool_name = extracted.pool_name
        if not self.request_id:
            self.request_id = extracted.request_id
        return self


class WAFRevokeResult(BaseModel):
    revoked: int
    sessions: list[str]
    details: list[dict]
    source_ip: str | None = None
    note: str | None = None
