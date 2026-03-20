import asyncio

from core.logger import event_bus
from domain.aria.service import AriaService
from infrastructure.http_client import post_to_jit


class AriaUDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        asyncio.ensure_future(self._handle(data, addr))

    def error_received(self, exc: Exception) -> None:
        asyncio.ensure_future(
            event_bus.publish(
                {"level": "ERROR", "domain": "ARIA", "message": f"UDP error: {exc}", "payload": None}
            )
        )

    async def _handle(self, data: bytes, addr: tuple) -> None:
        raw = data.decode("utf-8", errors="replace")

        await event_bus.publish(
            {
                "level": "INFO",
                "domain": "ARIA",
                "message": f"Datagram received from {addr[0]}:{addr[1]} ({len(data)} bytes)",
                "payload": None,
            }
        )

        parsed = AriaService.parse_idsp_syslog(raw)
        if parsed is None:
            await event_bus.publish(
                {
                    "level": "ERROR",
                    "domain": "ARIA",
                    "message": "IDSP syslog parse failed — unrecognised message format",
                    "payload": {"raw": raw[:200]},
                }
            )
            return

        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "ARIA",
                "message": "IDSP syslog parsed successfully",
                "payload": parsed.model_dump(),
            }
        )

        webhook = AriaService.build_webhook(parsed)

        await event_bus.publish(
            {
                "level": "PAYLOAD",
                "domain": "ARIA",
                "message": "Webhook payload built — POST /jit/webhook",
                "payload": webhook.model_dump(),
            }
        )

        await post_to_jit(webhook)


async def start_aria_udp(host: str = "127.0.0.1", port: int = 5140) -> None:
    loop = asyncio.get_event_loop()

    await event_bus.publish(
        {
            "level": "INFO",
            "domain": "SYSTEM",
            "message": f"Aria SIEM UDP listener starting on {host}:{port}",
            "payload": None,
        }
    )

    transport, _ = await loop.create_datagram_endpoint(
        lambda: AriaUDPProtocol(), local_addr=(host, port)
    )

    await event_bus.publish(
        {
            "level": "SUCCESS",
            "domain": "SYSTEM",
            "message": f"Aria SIEM UDP listener bound to {host}:{port}",
            "payload": None,
        }
    )

    try:
        await asyncio.sleep(float("inf"))
    except asyncio.CancelledError:
        transport.close()
        raise
