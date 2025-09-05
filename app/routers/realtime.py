from __future__ import annotations
import asyncio, json, time
from typing import Set
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse
from ..loaders import get_inventory_version, bump_inventory_version

router = APIRouter(prefix="/api", tags=["realtime"])

_CLIENTS: Set[asyncio.Queue] = set()

def _sse(event: str, data: dict) -> bytes:
    return (f"event: {event}\n" f"data: {json.dumps(data, ensure_ascii=False)}\n\n").encode("utf-8")

def broadcast_inventory_event():
    msg = _sse("inventory", {"version": get_inventory_version(), "ts": time.time()})
    for q in list(_CLIENTS):
        try:
            q.put_nowait(msg)
        except Exception:
            pass

def notify_inventory_changed():
    bump_inventory_version()
    broadcast_inventory_event()

@router.get("/stream")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    _CLIENTS.add(q)

    async def gen():
        # сразу отдаем текущую версию
        yield _sse("inventory", {"version": get_inventory_version(), "ts": time.time()})
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = await q.get()
                yield msg
        finally:
            _CLIENTS.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")

@router.get("/inventory/version")
def inventory_version():
    return {"version": get_inventory_version()}
