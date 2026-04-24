from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...core.events import event_broker

router = APIRouter(tags=["events"])


@router.websocket("/events")
async def event_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = event_broker.subscribe()
    await websocket.send_json({"type": "connection.ready"})

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_broker.unsubscribe(queue)
