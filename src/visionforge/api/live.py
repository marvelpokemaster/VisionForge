"""WebSocket live-session endpoints, mounted on the FastAPI app.

Protocol (see docs/live_tracking.md §9):

  WS /live/{session_id}
    client -> text   {"width": W, "height": H, "intrinsics": {fx,fy,cx,cy,k1,source?}?
                      | "intrinsics_from_cameras": [cameras.json entries]?,
                      "intrinsics_size": [w,h]?, "record": true?}             (optional, first)
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
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from visionforge.live.session import LiveSession

CLOSE_ALREADY_ACTIVE = 4409
CLOSE_INVALID_ID = 4400
CLOSE_UNAUTHORIZED = 4401

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

    require_auth = os.environ.get("VISIONFORGE_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
    is_prod = (
        os.environ.get("VISIONFORGE_ENV", "").lower() == "production"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
    )
    if require_auth or is_prod:
        token = ws.query_params.get("token")
        auth_header = ws.headers.get("Authorization")
        if not token and auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split()[1]

        backend = getattr(app.state, "backend", None)
        client = getattr(backend, "client", None)
        authenticated = False
        if token and client is not None and hasattr(client, "auth") and hasattr(client.auth, "get_user"):
            try:
                user_resp = client.auth.get_user(token)
                if user_resp and hasattr(user_resp, "user") and user_resp.user:
                    authenticated = True
            except Exception:
                pass
        elif token and not is_prod:
            authenticated = True

        if not authenticated:
            await ws.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
            return

    if not _valid_session_id(session_id):
        await ws.close(code=CLOSE_INVALID_ID, reason="invalid session id")
        return
    if session_id in sessions:
        await ws.close(code=CLOSE_ALREADY_ACTIVE, reason=f"live session '{session_id}' is already active")
        return

    kwargs = {"outputs_root": app.state.store.outputs_root, **app.state.live_session_defaults}
    session = LiveSession(session_id, **kwargs)
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
                now = time.perf_counter()  # perf_counter: monotonic() is ~16 ms-grained on Windows
                session.record_received(received, msg["bytes"], now)  # no-op unless {"record": true}
                if "frame" in latest:
                    session.record_dropped(frame_index=latest["frame"][1])
                latest["frame"] = (msg["bytes"], received, now)
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
                    "recording": session.recorder.summary() if session.recorder is not None else None,
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
        session.close_recording()  # a socket that died without finish still leaves a consistent index
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

    @app.get("/live/{session_id}/cloud")
    def live_cloud(session_id: str):
        """The active segment's current map as PLY, so the live viewer can
        draw points through the same PLY path as a finished session."""
        entry = app.state.live_sessions.get(session_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"No active live session '{session_id}'")
        ply = entry["session"].cloud_ply()
        return Response(content=ply, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{session_id}_live.ply"'})

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
