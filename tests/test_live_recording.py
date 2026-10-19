"""Recording a live session's received frames (live/recording.py) and
replaying the recording offline (live/offline.py, scripts/replay_live.py)."""
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from visionforge.api.app import create_app
from visionforge.live.offline import replay_recording
from visionforge.live.recording import FrameRecorder, read_recording
from visionforge.live.session import LiveSession
from visionforge.live.tracker import LiveTracker, TrackerConfig
from visionforge.persistence.local_backend import LocalJsonBackend
from visionforge.persistence import persist_run
from test_live_tracker import INTR, OracleFeatureTracker, box_points, render_frame, translating_path


def jpeg(img, quality=90):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return buf.tobytes()


@pytest.fixture
def client(tmp_path):
    app = create_app(outputs_root=tmp_path)
    with TestClient(app) as c:
        c.app = app
        yield c


def index_lines(run_dir):
    return [json.loads(l) for l in (run_dir / "frames.jsonl").read_text().splitlines() if l.strip()]


# ----------------------------------------------------------- what is written
def test_recording_writes_exactly_what_the_index_lists_and_stays_out_of_listings(client, tmp_path):
    rng = np.random.default_rng(1)
    frames = [rng.integers(0, 255, (120, 160, 3), dtype=np.uint8) for _ in range(5)]
    payloads = [jpeg(f) for f in frames]
    with client.websocket_connect("/live/rec") as ws:
        ws.send_text(json.dumps({"width": 160, "height": 120, "record": True}))
        conf = ws.receive_json()
        assert conf["configured"] and conf["recording"] is True and conf["keyframe_min_gap"] == 3
        for p in payloads:
            ws.send_bytes(p)
            ws.receive_json()
        ws.send_text(json.dumps({"cmd": "finish"}))
        done = ws.receive_json()
    assert done["recording"] == {"dir": "frames", "index": "frames.jsonl", "received": 5, "processed": 5, "not_processed": 0}
    run_dir = Path(done["run_dir"])
    entries = index_lines(run_dir)
    assert [e["frame_index"] for e in entries] == [0, 1, 2, 3, 4]
    assert all(e["processed"] is True for e in entries)
    assert all(e["received_at"] <= n["received_at"] for e, n in zip(entries, entries[1:]))
    # the index is exactly the directory: every listed file exists with the listed size, nothing else is there
    files = sorted(p.name for p in (run_dir / "frames").iterdir())
    assert files == [e["file"] for e in entries] == [f"{i:06d}.jpg" for i in range(5)]
    for e, p in zip(entries, payloads):
        assert (run_dir / "frames" / e["file"]).read_bytes() == p and e["bytes"] == len(p)
    configure = json.loads((run_dir / "configure.json").read_text())
    assert configure["configure"] == {"width": 160, "height": 120, "record": True}
    assert configure["effective"]["processed_size"] == [160, 120] and configure["effective"]["intrinsics"]["source"] == "guess"
    status = json.loads((run_dir / "run_status.json").read_text())
    assert status["live"]["recording"]["received"] == 5
    # the frames are not a session, not provenance and not persisted
    ids = [s["id"] for s in client.get("/sessions").json()]
    assert ids.count("rec") == 1 and "frames" not in ids
    prov = client.get("/sessions/rec/twin").json()["provenance"]
    assert "frames" not in json.dumps(prov["source_files"])
    saved = persist_run(LocalJsonBackend(tmp_path), "rec", run_dir)["saved"]
    assert "frames" not in saved and not any("frames" in s for s in saved)
    persisted = list((run_dir / "persistence").rglob("*"))
    assert persisted and not any("frames" in p.name or p.suffix == ".jpg" for p in persisted)
    assert "rec" in [s["id"] for s in client.get("/sessions").json()]


class SlowTracker(LiveTracker):
    def process_frame(self, frame, frame_index):
        time.sleep(0.06)
        return super().process_frame(frame, frame_index)


def test_dropped_frames_are_recorded_too_and_marked_not_processed(client):
    client.app.state.live_session_defaults["tracker_factory"] = lambda intr, cfg: SlowTracker(intr, cfg)
    frame = jpeg(np.zeros((120, 160, 3), np.uint8))
    n = 10
    with client.websocket_connect("/live/drops") as ws:
        ws.send_text(json.dumps({"width": 160, "height": 120, "record": True}))
        ws.receive_json()
        for _ in range(n):
            ws.send_bytes(frame)  # faster than the tracker: some get replaced
        ws.send_text(json.dumps({"cmd": "finish"}))
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("finished"):
                break
    done = msgs[-1]
    assert done["received"] == n and done["dropped"] > 0
    run_dir = Path(done["run_dir"])
    entries = index_lines(run_dir)
    assert len(entries) == n and sorted(e["frame_index"] for e in entries) == list(range(n))
    assert sum(e["processed"] for e in entries) == done["frames"]
    assert sum(not e["processed"] for e in entries) == done["dropped"]
    assert done["recording"]["processed"] == done["frames"] and done["recording"]["not_processed"] == done["dropped"]
    assert len(list((run_dir / "frames").glob("*.jpg"))) == n
    # the dropped ones are exactly the indices the statuses never reported
    processed_idx = {m["frame_index"] for m in msgs if "state" in m}
    assert {e["frame_index"] for e in entries if e["processed"]} == processed_idx


def test_recorder_close_marks_pending_frames_and_reader_validates(tmp_path):
    r = FrameRecorder(tmp_path / "s")
    r.received(0, b"\xff\xd8aa", 1.0)
    r.received(1, b"\xff\xd8bb", 1.1)
    r.mark(0, True)
    assert r.close() == {"dir": "frames", "index": "frames.jsonl", "received": 2, "processed": 1, "not_processed": 1}
    r.close()  # idempotent
    rec = read_recording(tmp_path / "s" / "frames")
    assert [(e["frame_index"], e["processed"]) for e in rec.entries] == [(0, True), (1, False)]
    assert rec.configure is None and rec.frame_bytes(rec.entries[1]) == b"\xff\xd8bb"
    (tmp_path / "s" / "frames" / "000001.jpg").unlink()
    with pytest.raises(FileNotFoundError, match="indexed frame"):
        read_recording(tmp_path / "s")
    with pytest.raises(FileNotFoundError, match="neither"):
        read_recording(tmp_path / "nothing")
    with pytest.raises(ValueError, match="no outputs root"):
        LiveSession("x").configure({"record": True})


# ---------------------------------------------------------- offline replay
def oracle_factory(pts, poses):
    oracle = OracleFeatureTracker(pts, poses)
    return lambda intr, cfg: LiveTracker(intr, cfg, feature_tracker=oracle)


def test_offline_replay_of_a_recording_reproduces_the_live_state_counts(tmp_path):
    poses = translating_path(45)
    pts = box_points()
    frames = []
    for i, (R, t) in enumerate(poses):
        img = np.zeros((480, 640), np.uint8) if 15 <= i < 25 else render_frame(pts, R, t)
        frames.append(jpeg(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 100))
    kwargs = dict(intrinsics=INTR, max_width=640, min_interval_s=1.0, min_new_points=10, min_points=50,
                  config=TrackerConfig())

    # "live": record every received frame; frames 30 and 31 are "dropped" by backpressure (never fed)
    cv2.setRNGSeed(0)
    live = LiveSession("live", outputs_root=tmp_path, tracker_factory=oracle_factory(pts, poses), **kwargs)
    live.configure({"width": 640, "height": 480, "record": True})
    dropped = {30, 31}
    for i, data in enumerate(frames):
        live.record_received(i, data, float(i) / 10.0)
        if i in dropped:
            live.record_dropped(frame_index=i)
        else:
            live.feed(data, i, float(i) / 10.0)
    live.close_recording()
    live_counts = live.tracker.report()["state_counts"]
    assert live_counts["TRACKING"] > 0 and live_counts["LOST"] > 0
    rec = read_recording(tmp_path / "live")
    assert len(rec.entries) == 45 and {e["frame_index"] for e in rec.entries if not e["processed"]} == dropped
    assert rec.configure == {"width": 640, "height": 480, "record": True}

    # offline, the frames the live tracker saw -> the same state counts, same frames, no recording of the replay
    cv2.setRNGSeed(0)
    replay, _ = replay_recording(tmp_path / "live", tmp_path / "replays" / "again", processed_only=True, finish=False,
                                 tracker_factory=oracle_factory(pts, poses), **kwargs)
    assert replay.tracker.report()["state_counts"] == live_counts
    assert replay.n_frames == live.n_frames == 43
    assert replay.recorder is None and replay.source_size == (640, 480)
    assert [r.frame_index for r in replay.tracker.results] == [r.frame_index for r in live.tracker.results]

    # every received frame: the two dropped ones are fed as well
    cv2.setRNGSeed(0)
    full, _ = replay_recording(tmp_path / "live", tmp_path / "replays" / "full", finish=False,
                               tracker_factory=oracle_factory(pts, poses), **kwargs)
    assert full.n_frames == 45 and 30 in [r.frame_index for r in full.tracker.results]


# --------------------------------------------- the CLI on a real recording
def test_cli_live_frames_dir_replays_a_recorded_clip_session_offline(client, tmp_path, monkeypatch, capsys):
    import sys
    from visionforge import cli
    from test_live_ws import clip_frames

    frames = clip_frames(max_frames=120)
    with client.websocket_connect("/live/recorded") as ws:
        ws.send_text(json.dumps({"width": 800, "height": 600, "record": True}))
        ws.receive_json()
        for f in frames:
            ws.send_bytes(jpeg(f))
            ws.receive_json()
        ws.send_text(json.dumps({"cmd": "finish"}))
        done = ws.receive_json()
    assert done["recording"]["received"] == 120 and done["stage_status"]["live_tracking"] == "success"
    live_report = json.loads((Path(done["run_dir"]) / "tracking_report.json").read_text())

    out = tmp_path / "offline" / "recorded_again"
    monkeypatch.setattr(sys, "argv", ["visionforge", "live", "--frames-dir", str(tmp_path / "recorded" / "frames"),
                                      "--output", str(out), "--processed-only"])
    cli.main()
    assert "Replaying" in capsys.readouterr().out
    report = json.loads((out / "tracking_report.json").read_text())
    status = json.loads((out / "run_status.json").read_text())
    assert status["stages"]["live_tracking"] == "success" and status["stages"]["twin"] == "success"
    assert status["live"]["recording"] is None  # a replay records nothing
    assert report["frames"] == live_report["frames"] == 120
    assert report["intrinsics"] == live_report["intrinsics"]  # the recorded configure -> same (scaled) intrinsics
    assert report["config"]["keyframe_min_gap"] == live_report["config"]["keyframe_min_gap"] == 3
    assert report["state_counts"]["TRACKING"] > 0 and report["timing"]["frames"] == 120
    assert (out / "p2" / "room_model.json").exists() and (out / "twin.json").exists()
    assert not (out / "frames").exists()
    monkeypatch.setattr(sys, "argv", ["visionforge", "live", "--frames-dir", str(tmp_path / "recorded")])
    with pytest.raises(SystemExit):
        cli.main()  # --output is required
