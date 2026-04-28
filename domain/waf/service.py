from domain.waf.models import WAFWebhookPayload


def summarize(payload: WAFWebhookPayload) -> str:
    label = payload.attack_type or payload.rule_id or "malicious request"
    severity = f" [{payload.severity.upper()}]" if payload.severity else ""
    vs = f" on {payload.virtual_service}" if payload.virtual_service else ""
    return f"WAF alert{severity}: {label} from {payload.client_ip}{vs}"
