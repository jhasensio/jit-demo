import httpx

from core.logger import event_bus
from domain.aria.models import WebhookPayload


async def post_to_jit(webhook: WebhookPayload) -> None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://127.0.0.1:8000/jit/webhook",
                json=webhook.model_dump(),
                timeout=10.0,
            )
        await event_bus.publish(
            {
                "level": "SUCCESS",
                "domain": "ARIA",
                "message": f"HTTP POST → /jit/webhook  response: HTTP {resp.status_code}",
                "payload": None,
            }
        )
    except Exception as exc:
        await event_bus.publish(
            {
                "level": "ERROR",
                "domain": "ARIA",
                "message": f"HTTP POST to JIT failed: {exc}",
                "payload": None,
            }
        )
