import asyncio
import socket

from fastapi import APIRouter

from core.logger import event_bus
from domain.idsp.models import AuthRequest
from domain.idsp.service import IDSPService

router = APIRouter(prefix="/idsp", tags=["IDSP"])


@router.post("/submit")
async def submit_auth_event(req: AuthRequest) -> dict:
    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "IDSP",
            "message": f"Authentication event received: {req.action} by {req.username} from {req.source_ip} → {req.target_app}",
            "payload": req.model_dump(),
        }
    )

    syslog = IDSPService.build_idsp_syslog(req)

    await event_bus.publish(
        {
            "level": "PAYLOAD",
            "domain": "IDSP",
            "message": "IDSP syslog message generated",
            "payload": {"syslog": syslog},
        }
    )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_udp, syslog.encode("utf-8"))

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "IDSP",
            "message": "IDSP syslog sent via UDP → 127.0.0.1:5140 (Aria SIEM)",
            "payload": None,
        }
    )

    return {"status": "sent", "action": req.action, "username": req.username}


def _send_udp(data: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(data, ("127.0.0.1", 5140))
