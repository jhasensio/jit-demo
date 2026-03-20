import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import Request
from fastapi.responses import StreamingResponse


class EventBus:
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, event: dict) -> None:
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(timezone.utc).isoformat()

        dead: list[asyncio.Queue] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)

        for q in dead:
            self.unsubscribe(q)


event_bus = EventBus()


async def _sse_generator(request: Request, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                import json
                data = json.dumps(event)
                yield f"data: {data}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        event_bus.unsubscribe(queue)


async def sse_endpoint(request: Request) -> StreamingResponse:
    queue = await event_bus.subscribe()
    return StreamingResponse(
        _sse_generator(request, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
