import json
import re

from pydantic import BaseModel, ConfigDict, model_validator


# Regex to find an IPv4 in a string
_IP_RE = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b')

# Field names that may carry the client IP inside a log entry object
_CLIENT_IP_KEYS = ("source_ip", "client_ip", "clientip", "src_ip", "ClientIP",
                   "client_addr", "srcip", "remote_addr")


def _extract_ip_from_messages(messages_raw) -> str | None:
    """
    Log Insight puts the triggering log entries in 'messages'.
    It can be a JSON-encoded string, a list of dicts, or a plain string.
    Try to extract the first plausible client IP from it.
    """
    if not messages_raw:
        return None

    # Decode if it's a JSON string
    if isinstance(messages_raw, str):
        try:
            messages_raw = json.loads(messages_raw)
        except (json.JSONDecodeError, ValueError):
            # Fall back: regex scan the raw string
            m = _IP_RE.search(messages_raw)
            return m.group(1) if m else None

    if isinstance(messages_raw, list):
        for entry in messages_raw:
            if isinstance(entry, dict):
                for key in _CLIENT_IP_KEYS:
                    val = entry.get(key) or entry.get(key.lower())
                    if val and isinstance(val, str) and _IP_RE.match(val.strip()):
                        return val.strip()
                # Last resort: scan all string values for an IP
                for val in entry.values():
                    if isinstance(val, str):
                        m = _IP_RE.search(val)
                        if m:
                            return m.group(1)
    return None


class WAFWebhookPayload(BaseModel):
    """
    Accepts Log Insight's default webhook body plus any custom template fields.

    Log Insight's built-in fields:
      alert_type, alert_name, search_period, hit_operator, messages

    To embed the client IP directly (recommended), configure a custom Log Insight
    webhook template and add:  "source_ip": "{{source_ip}}"
    If source_ip is absent, we attempt to extract it from the 'messages' entries.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Client IP — optional at parse time; resolved in the validator below
    source_ip: str | None = None

    # Standard Log Insight alert metadata
    alert_type: str | None = None
    alert_name: str | None = None
    search_period: str | None = None
    hit_operator: str | None = None       # Log Insight typos this as hit_oeprator too
    messages: object | None = None        # str (JSON-encoded) or list of log entries

    # Optional enrichment fields (custom template or other WAF sources)
    target_app: str | None = None
    rule_id: str | None = None
    attack_type: str | None = None
    severity: str | None = None
    virtual_service: str | None = None
    description: str | None = None
    event_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: dict) -> dict:
        # Accept Log Insight's typo variant hit_oeprator
        if "hit_oeprator" in data and "hit_operator" not in data:
            data["hit_operator"] = data.pop("hit_oeprator")
        # Accept common IP field aliases
        for alias in ("client_ip", "src_ip", "clientip", "ClientIP"):
            if alias in data and "source_ip" not in data:
                data["source_ip"] = data.pop(alias)
                break
        return data

    @model_validator(mode="after")
    def _resolve_ip(self) -> "WAFWebhookPayload":
        if not self.source_ip:
            self.source_ip = _extract_ip_from_messages(self.messages)
        return self

    @property
    def resolved_ip(self) -> str | None:
        return self.source_ip


class WAFRevokeResult(BaseModel):
    revoked: int
    sessions: list[str]
    details: list[dict]
    source_ip: str | None = None
    note: str | None = None
