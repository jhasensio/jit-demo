import re

from domain.aria.models import ParsedEvent, WebhookPayload

# Regex matching the IDSP Session Management syslog format:
#
#   <PRIORITY>gkpsyslog[PID]: created = YYYY-MM-DD HH:MM:SS
#   Private IP: {ip}, Public IP: {ip}, Nat/Proxy IP: {ip},
#   User: {user}, Transaction: {tx}, Address: {addr},
#   Device Name: {name}, User Group: {group}, Port: {port},
#   Access/Protocol: {proto}, Service/App: {svc}, Details: {msg}
_PAM_PATTERN = re.compile(
    r"<\d+>gkpsyslog\[\d+\]:\s+"
    r"created\s*=\s*(?P<timestamp>[\d]{4}-[\d]{2}-[\d]{2} [\d]{2}:[\d]{2}:[\d]{2})\s+"
    r"Private IP:\s*(?P<private_ip>[^,]*),\s*"
    r"Public IP:\s*(?P<public_ip>[^,]*),\s*"
    r"Nat/Proxy IP:\s*(?P<source_ip>[^,]*),\s*"
    r"User:\s*(?P<username>[^,]+),\s*"
    r"Transaction:\s*(?P<transaction>[^,]+),\s*"
    r"Address:\s*[^,]+,\s*"
    r"Device Name:\s*[^,]+,\s*"
    r"User Group:\s*[^,]+,\s*"
    r"Port:\s*[^,]+,\s*"
    r"Access/Protocol:\s*[^,]+,\s*"
    r"Service/App:\s*(?P<target_app>[^,]+),\s*"
    r"Details:\s*(?P<details>.+)$",
    re.DOTALL,
)


class AriaService:
    @staticmethod
    def parse_idsp_syslog(raw: str) -> ParsedEvent | None:
        """Parse an IDSP Session Management syslog message."""
        m = _PAM_PATTERN.search(raw)
        if not m:
            return None

        transaction = m.group("transaction").strip()
        action = transaction.upper()   # "login" → "LOGIN", "logout" → "LOGOUT"

        # Derive event_type from the Details field IDSP-XXXX prefix
        details = m.group("details").strip()
        event_type = details.split(":")[0] if ":" in details else "Session Management"

        # source_ip from Nat/Proxy IP; fall back to Private IP if blank
        source_ip = m.group("source_ip").strip()
        if not source_ip:
            source_ip = m.group("private_ip").strip()

        return ParsedEvent(
            timestamp=m.group("timestamp").strip(),
            event_type=event_type,
            username=m.group("username").strip(),
            source_ip=source_ip,
            target_app=m.group("target_app").strip(),
            action=action,
        )

    @staticmethod
    def build_webhook(parsed: ParsedEvent) -> WebhookPayload:
        return WebhookPayload(
            event_type=parsed.event_type,
            username=parsed.username,
            source_ip=parsed.source_ip,
            target_app=parsed.target_app,
            action=parsed.action,
            original_timestamp=parsed.timestamp,
        )
