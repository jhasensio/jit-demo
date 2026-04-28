import json
import re

from pydantic import BaseModel, ConfigDict, model_validator


_IP_RE = re.compile(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b')


def _extract_client_ip(messages_raw) -> str | None:
    """
    Extract client_ip from Log Insight's messages array.

    Log Insight sends each triggering log entry as:
      {"text": "...", "timestamp": ..., "fields": [{"name": "client_ip", "content": "1.2.3.4"}, ...]}

    Falls back to a flat key lookup then a regex scan if the structure differs.
    """
    if not messages_raw:
        return None

    # Decode JSON string if needed
    if isinstance(messages_raw, str):
        try:
            messages_raw = json.loads(messages_raw)
        except (json.JSONDecodeError, ValueError):
            m = _IP_RE.search(messages_raw)
            return m.group(1) if m else None

    if not isinstance(messages_raw, list):
        return None

    for entry in messages_raw:
        if not isinstance(entry, dict):
            continue

        # Primary: Log Insight nested fields array — {"name": "client_ip", "content": "..."}
        fields = entry.get("fields")
        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, dict) and f.get("name") == "client_ip":
                    val = f.get("content", "")
                    if val and _IP_RE.match(val.strip()):
                        return val.strip()

        # Fallback: flat key on the entry dict itself
        for key in ("client_ip", "clientip", "ClientIP", "client_addr", "src_ip"):
            val = entry.get(key, "")
            if val and isinstance(val, str) and _IP_RE.match(val.strip()):
                return val.strip()

        # Last resort: regex scan all string values in the entry
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
        return data

    @model_validator(mode="after")
    def _resolve_ip(self) -> "WAFWebhookPayload":
        if not self.source_ip:
            self.source_ip = _extract_client_ip(self.messages)
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
