"""WebSocket live-session endpoints, mounted on the FastAPI app.

Protocol (see docs/live_tracking.md §9):

  WS /live/{session_id}
    client -> text   {"width": W, "height": H, "intrinsics": {fx,fy,cx,cy,k1}?
                      | "intrinsics_from_cameras": [cameras.json entries]?}   (optional, first)
    server -> text   {"configured": true, ...}
    client -> bytes  one JPEG frame                       (repeat)
    server -> text   the LiveSession.feed() status dict   (one per PROCESSED frame)
    client -> text   {"cmd": "finish"}
    server -> text   {"finished": true, "session_id", "run_dir", "stage_status", ...}; then close 1000

Backpressure: frames arrive on the socket task; processing happens in a
worker task that hands each frame to a thread (the tracker is CPU-bound).
If a frame arrives while another is still being processed, the pending one
is REPLACED by the newer frame and `dropped` is incremented — the newest
frame always wins, nothing queues up.

A second socket on an active id is accepted and immediately closed with
code 4409 ("already active"). GET /live lists active sessions; DELETE
/live/{id} closes and drops one.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from visionforge.live.session import LiveSession

CLOSE_ALREADY_ACTIVE = 4409
CLOSE_INVALID_ID = 4400

router = APIRouter()


def _valid_session_id(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value and len(value) <= 128


def install_live_routes(app: FastAPI) -> None:
    """Mount WS /live/{id} (module router) and GET /live, DELETE /live/{id}
    (closures over this app's state)."""
    app.state.live_sessions = {}          # id -> {"session": LiveSession, "websocket": ws, "started": t}
    app.state.live_session_defaults = {}  # kwargs for LiveSession(...); tests inject a tracker_factory here
    _install_rest(app)
    app.include_router(router)


@router.websocket("/live/{session_id}")
async def live_socket(ws: WebSocket, session_id: str):
    app = ws.app
    sessions: Dict[str, Dict[str, Any]] = app.state.live_sessions
    await ws.accept()
    if not _valid_session_id(session_id):
        await ws.close(code=CLOSE_INVALID_ID, reason="invalid session id")
        return
    if session_id in sessions:
        await ws.close(code=CLOSE_ALREADY_ACTIVE, reason=f"live session '{session_id}' is already active")
        return

    session = LiveSession(session_id, **app.state.live_session_defaults)
    entry = {"session": session, "websocket": ws, "started": time.time()}
    sessions[session_id] = entry
    loop = asyncio.get_running_loop()

    latest: Dict[str, Any] = {}      # at most one pending frame: the newest
    wake = asyncio.Event()
    idle = asyncio.Event()
    idle.set()
    received = 0

    async def worker():
        while True:
            await wake.wait()
            wake.clear()
            while "frame" in latest:
                data, idx, ts = latest.pop("frame")
                try:
                    status = await loop.run_in_executor(None, session.feed, data, idx, ts)
                except ValueError as exc:
                    status = {"session_id": session_id, "frame_index": idx, "error": str(exc)}
                await ws.send_json(status)
            idle.set()

    worker_task = asyncio.create_task(worker())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if "frame" in latest:
                    session.record_dropped()
                latest["frame"] = (msg["bytes"], received, time.monotonic())
                received += 1
                idle.clear()
                wake.set()
                continue
            if msg.get("text") is None:
                continue
            try:
                payload = json.loads(msg["text"])
            except json.JSONDecodeError:
                await ws.send_json({"error": "text messages must be JSON"})
                continue
            if payload.get("cmd") == "finish":
                await idle.wait()  # process whatever is still pending first
                run_dir = await loop.run_in_executor(None, session.finish, app.state.store.outputs_root)
                app.state.store.register(run_dir, session_id)
                await ws.send_json({
                    "finished": True,
                    "session_id": session_id,
                    "run_dir": str(run_dir),
                    "stage_status": session.stage_status,
                    "frames": session.n_frames,
                    "received": received,
                    "dropped": session.dropped,
                    "twin_updates": session.n_twin_updates,
                })
                await ws.close(code=1000)
                break
            try:
                reply = session.configure(payload)
            except (ValueError, KeyError, TypeError) as exc:
                reply = {"error": f"bad configure message: {exc}"}
            await ws.send_json(reply)
    except WebSocketDisconnect:
        pass
    finally:
        worker_task.cancel()
        sessions.pop(session_id, None)


def _install_rest(app: FastAPI) -> None:
    @app.get("/live")
    def list_live():
        out = []
        for sid, entry in app.state.live_sessions.items():
            s = entry["session"].summary()
            s["started"] = entry["started"]
            out.append(s)
        return out

    @app.delete("/live/{session_id}")
    async def delete_live(session_id: str):
        entry = app.state.live_sessions.pop(session_id, None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No active live session '{session_id}'")
        try:
            await entry["websocket"].close(code=1001, reason="deleted")
        except RuntimeError:
            pass  # already closed
        return {"deleted": session_id, "frames": entry["session"].n_frames}
