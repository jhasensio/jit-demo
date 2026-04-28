from domain.waf.models import WAFWebhookPayload


def summarize(payload: WAFWebhookPayload) -> str:
    ip       = payload.source_ip or "unknown IP"
    label    = payload.attack_type or payload.rule_id or payload.alert_name or "malicious request"
    severity = f" [{payload.severity.upper()}]" if payload.severity else ""
    vs       = f" → {payload.virtual_service}" if payload.virtual_service else ""
    pool     = f" ({payload.pool_name})" if payload.pool_name else ""
    rid      = f" rule:{payload.rule_id}" if payload.rule_id and payload.attack_type else ""
    return f"WAF{severity}: {label}{rid} from {ip}{vs}{pool}"
