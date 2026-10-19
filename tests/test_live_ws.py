"""Live WebSocket session: LiveSession + the /live endpoints (TestClient)."""
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from visionforge.api.app import create_app
from visionforge.api.live import CLOSE_ALREADY_ACTIVE
from visionforge.live.session import LiveSession
from visionforge.live.tracker import LiveTracker, TrackerConfig, TrackState
from test_live_tracker import INTR, OracleFeatureTracker, box_points, render_frame, translating_path

REPO = Path(__file__).resolve().parents[1]
CLIP = REPO / "data" / "input" / "synthetic_box_room_30fps.mp4"


def jpeg(img, quality=90):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return buf.tobytes()


def clip_frames(max_frames=None):
    if not CLIP.exists():
        subprocess.run([sys.executable, str(REPO / "scripts" / "generate_synthetic_clip.py"), "--output", str(CLIP),
                        "--frames", "360", "--fps", "30"], check=True)
    cap = cv2.VideoCapture(str(CLIP))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok or (max_frames and len(frames) >= max_frames):
            break
        frames.append(f)
    cap.release()
    return frames


@pytest.fixture
def client(tmp_path):
    app = create_app(outputs_root=tmp_path)
    with TestClient(app) as c:
        c.app = app
        yield c


def stream(ws, frames, each=1):
    """Send frames one at a time, waiting for each status (phone-like pacing, no drops)."""
    statuses = []
    for i, f in enumerate(frames):
        if i % each:
            continue
        ws.send_bytes(jpeg(f))
        statuses.append(ws.receive_json())
    return statuses


# ------------------------------------------------------------- end to end
def test_replay_clip_tracks_updates_twin_and_finishes_into_a_session(client, tmp_path):
    frames = clip_frames()
    assert frames[0].shape[:2] == (600, 800)
    with client.websocket_connect("/live/replay") as ws:
        ws.send_text(json.dumps({"width": 800, "height": 600}))
        conf = ws.receive_json()
        assert conf["configured"] and conf["intrinsics"]["source"] == "guess" and conf["processed_size"] == [640, 480]
        statuses = stream(ws, frames[:200])
        # the live cloud endpoint serves the active segment's current map as PLY
        cloud = client.get("/live/replay/cloud")
        assert cloud.status_code == 200 and cloud.content.startswith(b"ply\nformat ascii 1.0\n")
        n_vertices = int([l for l in cloud.text.splitlines() if l.startswith("element vertex")][0].split()[-1])
        assert n_vertices == statuses[-1]["map_size"] > 0
        assert client.get("/live/nope/cloud").status_code == 404
        statuses += stream(ws, frames[200:])
        ws.send_text(json.dumps({"cmd": "finish"}))
        done = ws.receive_json()
    states = [s["state"] for s in statuses]
    assert "TRACKING" in states and states.count("LOST") == 0
    maps = [s["map_size"] for s in statuses]
    assert max(maps) > 300 and maps[-1] >= maps[len(maps) // 2] > 0
    assert all(s["processed_size"] == [640, 480] and s["source_size"] == [800, 600] for s in statuses)
    assert all(s["dropped"] == 0 for s in statuses)
    tracking = [s for s in statuses if s["state"] == "TRACKING"]
    assert all(s["pose"] is not None and len(s["pose"]["rotation_quat"]) == 4 for s in tracking)
    assert all(s["pose"] is None for s in statuses if s["state"] != "TRACKING")
    updates = [s["twin_update"] for s in statuses if s["twin_update"] is not None]
    assert len(updates) >= 1
    assert any(len(u["room_model"]["planes"]) >= 1 for u in updates), [u["provenance"] for u in updates]
    for u in updates:
        assert u["provenance"]["live"] is True and u["provenance"]["segment"] == 0
        assert u["cameras"] and u["cameras"][0]["camera_model"] == "PINHOLE"
        assert u["provenance"]["stage_status"]["live_tracking"] == "TRACKING"
        if u["room_model"]["planes"]:
            assert u["scene_graph"] is not None and u["provenance"]["stage_status"]["p2_room_geometry"] == "success"
    assert done["finished"] and done["session_id"] == "replay" and done["dropped"] == 0
    assert done["stage_status"]["live_tracking"] == "success" and done["stage_status"]["twin"] == "success"
    run_dir = Path(done["run_dir"])
    assert run_dir == tmp_path / "replay"
    for rel in ("p1/reconstruction/cameras.json", "p1/reconstruction/sparse_cloud.ply", "tracking_report.json",
                "p2/room_model.json", "scene_graph.json", "twin.json", "run_status.json"):
        assert (run_dir / rel).exists(), rel
    report = json.loads((run_dir / "tracking_report.json").read_text())
    assert report["intrinsics"]["fx"] == 640.0 and report["intrinsics"]["cx"] == 320.0  # guess 800 scaled by 0.8
    # the finished session is a normal session for the REST API
    assert client.get("/live").json() == []
    twin = client.get("/sessions/replay/twin")
    assert twin.status_code == 200
    assert len(twin.json()["room_model"]["planes"]) >= 1
    assert twin.json()["provenance"]["stage_status"]["live_tracking"] == "success"
    assert "replay" in [s["id"] for s in client.get("/sessions").json()]
    assert client.get("/sessions/replay/cameras").status_code == 200


def test_black_frames_never_track_and_finish_is_honest(client, tmp_path):
    black = np.zeros((480, 640, 3), np.uint8)
    with client.websocket_connect("/live/dark") as ws:
        statuses = stream(ws, [black] * 30)
        ws.send_text(json.dumps({"cmd": "finish"}))
        done = ws.receive_json()
    assert all(s["state"] == "INITIALIZING" and s["map_size"] == 0 and s["twin_update"] is None and s["pose"] is None
               for s in statuses)
    assert done["stage_status"] == {"live_tracking": "failed", "twin": "success"}
    run_dir = Path(done["run_dir"])
    status = json.loads((run_dir / "run_status.json").read_text())
    assert status["stages"]["live_tracking"] == "failed" and "never initialised" in status["error"]
    assert not (run_dir / "p2").exists()
    assert json.loads((run_dir / "p1" / "reconstruction" / "cameras.json").read_text()) == []
    twin = client.get("/sessions/dark/twin")
    assert twin.status_code == 200
    assert twin.json()["room_model"] is None and twin.json()["scene_graph"] is None
    assert twin.json()["provenance"]["stage_status"]["live_tracking"] == "failed"
    assert client.get("/sessions/dark/room_model").status_code == 404
    assert client.get("/sessions/dark/measurements").status_code == 404


def test_duplicate_id_is_rejected_with_a_clear_code(client):
    with client.websocket_connect("/live/dup") as first:
        assert [s["session_id"] for s in client.get("/live").json()] == ["dup"]
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/live/dup") as second:
                second.receive_json()
        assert exc.value.code == CLOSE_ALREADY_ACTIVE
        # the first socket is unaffected
        first.send_bytes(jpeg(np.zeros((120, 160, 3), np.uint8)))
        assert first.receive_json()["frame_index"] == 0
    assert client.get("/live").json() == []


def test_delete_closes_and_drops_the_session(client):
    with client.websocket_connect("/live/gone") as ws:
        ws.send_bytes(jpeg(np.zeros((120, 160, 3), np.uint8)))
        assert ws.receive_json()["frames"] == 1
        r = client.delete("/live/gone")
        assert r.status_code == 200 and r.json() == {"deleted": "gone", "frames": 1}
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1001
    assert client.get("/live").json() == []
    assert client.delete("/live/gone").status_code == 404


def test_wide_frames_are_processed_at_640_with_scaled_intrinsics(client, tmp_path):
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8) for _ in range(3)]
    with client.websocket_connect("/live/wide") as ws:
        statuses = stream(ws, frames)
        ws.send_text(json.dumps({"cmd": "finish"}))
        done = ws.receive_json()
    assert statuses[0]["source_size"] == [1920, 1080] and statuses[0]["processed_size"] == [640, 360]
    report = json.loads((Path(done["run_dir"]) / "tracking_report.json").read_text())
    assert report["intrinsics"] == {"fx": 640.0, "fy": 640.0, "cx": 320.0, "cy": 180.0, "k1": 0.0, "source": "guess"}


def test_client_intrinsics_are_scaled_with_the_frame(tmp_path):
    s = LiveSession("intr", max_width=320)
    s.configure({"width": 640, "height": 480, "intrinsics": {"fx": 600, "fy": 610, "cx": 330, "cy": 250, "k1": 0.01}})
    intr = s.tracker.intrinsics
    assert (intr.fx, intr.fy, intr.cx, intr.cy, intr.k1, intr.source) == (300, 305, 165, 125, 0.01, "client")
    assert s.processed_size == (320, 240)
    with pytest.raises(ValueError, match="configure must precede"):
        s.configure({"width": 1, "height": 1})
    with pytest.raises(ValueError, match="frame size changed"):
        s.feed(jpeg(np.zeros((100, 100, 3), np.uint8)), 0, 0.0)
    with pytest.raises(ValueError, match="could not decode"):
        LiveSession("bad").feed(b"not a jpeg", 0, 0.0)


# ------------------------------------------------------------ backpressure
class SlowTracker(LiveTracker):
    def process_frame(self, frame, frame_index):
        time.sleep(0.08)
        return super().process_frame(frame, frame_index)


def test_frames_are_dropped_under_a_slow_tracker(client):
    client.app.state.live_session_defaults["tracker_factory"] = lambda intr, cfg: SlowTracker(intr, cfg)
    frame = jpeg(np.zeros((120, 160, 3), np.uint8))
    n = 12
    with client.websocket_connect("/live/slow") as ws:
        for _ in range(n):
            ws.send_bytes(frame)   # no waiting: faster than 80 ms per frame
        ws.send_text(json.dumps({"cmd": "finish"}))
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("finished"):
                break
    statuses = [m for m in msgs if "state" in m]
    done = msgs[-1]
    assert done["received"] == n
    assert done["dropped"] > 0 and done["frames"] + done["dropped"] == n
    assert len(statuses) == done["frames"] < n
    assert statuses[-1]["dropped"] == done["dropped"]
    # the newest frame always wins: the last processed index is the last one sent
    assert statuses[-1]["frame_index"] == n - 1


# --------------------------------------------------------- segment change
def test_reinitialisation_after_lost_starts_a_new_incremental_room_model():
    poses = translating_path(45)
    pts = box_points()
    oracle = OracleFeatureTracker(pts, poses)
    cv2.setRNGSeed(0)
    s = LiveSession("seg", intrinsics=INTR, max_width=640, min_interval_s=1.0, min_new_points=10, min_points=50,
                    tracker_factory=lambda intr, cfg: LiveTracker(intr, TrackerConfig(), feature_tracker=oracle))
    incs, statuses = [], []
    for i, (R, t) in enumerate(poses):
        img = np.zeros((480, 640), np.uint8) if 15 <= i < 25 else render_frame(pts, R, t)
        # JPEG round-trip: a black frame stays exactly black (the oracle's "blind" signal); dots survive
        st = s.feed(jpeg(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 100), i, float(i))
        statuses.append(st)
        incs.append(s._inc)
    states = [st["state"] for st in statuses]
    assert states[14] == "TRACKING" and all(states[i] == "LOST" for i in range(15, 25)) and "TRACKING" in states[25:]
    segs = [st["segment"] for st in statuses]
    assert segs[14] == 0 and 1 in segs[25:]
    first_tracking_after = next(i for i in range(25, 45) if states[i] == "TRACKING")
    assert incs[14] is not None and incs[first_tracking_after] is not incs[14]
    assert statuses[-1]["n_segments"] == 2
    updates = [(st["frame_index"], st["twin_update"]) for st in statuses if st["twin_update"] is not None]
    assert updates
    assert all(u["provenance"]["segment"] == 0 for i, u in updates if i <= 14)
    assert all(u["provenance"]["segment"] == 1 for i, u in updates if i >= 25)
    assert all(st["twin_update"] is None for st in statuses[15:25])


def test_live_ws_production_requires_auth_and_rejects_missing_token(client, monkeypatch):
    monkeypatch.setenv("VISIONFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("VISIONFORGE_ENV", "production")

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/live/sess-unauth") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_live_ws_production_accepts_valid_token_in_query_param(client, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setenv("VISIONFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("VISIONFORGE_ENV", "production")

    mock_client = MagicMock()
    mock_user_resp = MagicMock()
    mock_user = MagicMock()
    mock_user.id = "valid-ws-user"
    mock_user_resp.user = mock_user
    mock_client.auth.get_user.return_value = mock_user_resp

    mock_backend = MagicMock()
    mock_backend.client = mock_client
    client.app.state.backend = mock_backend

    with client.websocket_connect("/live/sess-auth?token=valid-token") as ws:
        # Connection established successfully
        ws.send_json({"cmd": "finish"})
        reply = ws.receive_json()
        assert reply.get("finished") is True

