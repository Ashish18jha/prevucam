"""WebSockets: live notifications (/ws/live) and the browser-webcam frame link (/ws/webcam).

All CRUD/search/settings traffic stays on REST.
"""
import asyncio

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings as cfg
from app.services.camera_service import browser_inbox
from app.services.event_bus import event_bus
from app.services.pipeline import get_pipeline
from app.utils.logger import get_logger

log = get_logger("webcam")
DISCONNECT_GRACE_SECONDS = 3.0

router = APIRouter()


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    if cfg.API_KEY and ws.query_params.get("api_key") != cfg.API_KEY:
        await ws.close(code=4401)
        return
    await ws.accept()
    queue = event_bus.subscribe()
    try:
        await ws.send_json({"type": "camera_status", "data": _jsonable(get_pipeline().status())})
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:  # distinct from TimeoutError before Python 3.11
                msg = {"type": "ping", "data": None}
            await ws.send_json(_jsonable(msg))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        event_bus.unsubscribe(queue)


def _decode(data: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


@router.websocket("/ws/webcam")
async def webcam(ws: WebSocket):
    """Real webcam frames from the browser (getUserMedia) into the shared detection pipeline.

    Protocol: the client sends one JPEG (binary message) and waits for the matching
    {"type": "result"} reply before sending the next one, so the frame rate adapts to how
    fast this machine runs the pipeline and nothing queues up.
    """
    if cfg.API_KEY and ws.query_params.get("api_key") != cfg.API_KEY:
        await ws.close(code=4401)
        return
    await ws.accept()
    p = get_pipeline()
    if not (p.camera.running and p.camera.source_type == "browser"):
        await ws.send_json({"type": "error", "detail": "Monitoring is not started for the browser webcam."})
        await ws.close(code=4409)
        return
    browser_inbox.session += 1
    session = browser_inbox.session
    browser_inbox.connected = True
    browser_inbox.label = (ws.query_params.get("label") or "")[:80]
    log.info("Browser webcam connected: %s", browser_inbox.label or "unnamed device")
    last_index = p.camera.latest().index if p.camera.latest() else 0
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue
            image = await asyncio.to_thread(_decode, data)
            if image is None:
                await ws.send_json({"type": "error", "detail": "Could not decode webcam frame"})
                continue
            browser_inbox.push(image)
            frame = await asyncio.to_thread(p.camera.wait_for_frame, last_index, 3.0)
            if frame is not None:
                last_index = frame.index
            await ws.send_json({
                "type": "result", "frame": last_index, "fps": p.camera.fps, "motion": p._last_motion,
                "tracks": p.live_tracks_info, "active_event_id": p.events.active_event_id,
                "detector_available": p.detector._model is not None, "running": p.camera.running,
                "size": list(p.size),
            })
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if browser_inbox.session == session:
            browser_inbox.connected = False
        log.info("Browser webcam disconnected")
        # closing the tab / leaving the app ends monitoring (and finalises any open event),
        # unless a new browser connection took over in the meantime (restart, reconnect)
        await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
        if browser_inbox.session == session and p.camera.running and p.camera.source_type == "browser":
            log.info("No browser webcam reconnected – stopping monitoring")
            await asyncio.to_thread(p.stop)
            p.camera.error = "Browser webcam disconnected"


def _jsonable(obj):
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(obj)
