import random
from datetime import datetime, timezone

from domain.idsp.models import AuthRequest

# Session Management syslog message codes
_MSG_CODES = {
    "LOGIN":  "IDSP-0917",
    "LOGOUT": "IDSP-0918",
}

# Syslog priority: facility=10 (auth), severity=5 (notice) → (10*8)+5 = 85
_PRIORITY = 85


class IDSPService:
    @staticmethod
    def build_idsp_syslog(req: AuthRequest) -> str:
        """Build an IDSP Session Management syslog message.

        Format:
          <PRIORITY>gkpsyslog[PID]: created = YYYY-MM-DD HH:MM:SS
          Private IP: {ip}, Public IP: {ip}, Nat/Proxy IP: {ip},
          User: {user}, Transaction: {tx}, Address: {addr},
          Device Name: {name}, User Group: {group}, Port: {port},
          Access/Protocol: {proto}, Service/App: {svc}, Details: {msg}
        """
        pid  = random.randint(1000, 65535)
        ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        tx   = req.action.lower()   # "login" | "logout"
        code = _MSG_CODES.get(req.action, "IDSP-0917")

        if req.action == "LOGIN":
            details = f"{code}: User {req.username} logged in successfully via local authentication."
        else:
            details = f"{code}: User {req.username} logged out."

        return (
            f"<{_PRIORITY}>gkpsyslog[{pid}]: "
            f"created = {ts} "
            f"Private IP: , "
            f"Public IP: , "
            f"Nat/Proxy IP: {req.source_ip}, "
            f"User: {req.username}, "
            f"Transaction: {tx}, "
            f"Address: {req.destination_ip}, "
            f"Device Name: {req.device_name}, "
            f"User Group: --, "
            f"Port: {req.port}, "
            f"Access/Protocol: {req.access_protocol}, "
            f"Service/App: {req.target_app}, "
            f"Details: {details}"
        )
