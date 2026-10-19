"""LiveSession timing: per-frame process time, inter-arrival interval and
delivered fps, so tracking_report.timing is never null for a live session."""
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from visionforge.api.app import create_app
from visionforge.live.session import LiveSession
from visionforge.live.tracker import LiveTracker


def jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    assert ok
    return buf.tobytes()


class Sleeper(LiveTracker):
    sleep_s = 0.02

    def process_frame(self, frame, frame_index):
        time.sleep(self.sleep_s)
        return super().process_frame(frame, frame_index)


class SlowSleeper(Sleeper):
    sleep_s = 0.12


def test_timing_summary_from_known_timestamps_and_a_known_tracker_cost():
    s = LiveSession("t", tracker_factory=lambda intr, cfg: Sleeper(intr, cfg))
    data = jpeg(np.zeros((120, 160, 3), np.uint8))
    arrivals = [0.0, 0.1, 0.2, 0.35, 0.5, 0.6]
    for i, ts in enumerate(arrivals):
        s.feed(data, i, ts)
    tm = s.timing_summary()
    assert tm["frames"] == 6
    assert tm["wall_time_s"] == pytest.approx(0.6)
    assert tm["delivered_fps"] == pytest.approx(5 / 0.6)
    assert tm["interarrival_ms_mean"] == pytest.approx(120.0)
    assert tm["interarrival_ms_p50"] == pytest.approx(100.0)
    assert tm["interarrival_ms_max"] == pytest.approx(150.0)
    assert tm["interarrival_ms_p95"] == pytest.approx(np.percentile([100, 100, 150, 150, 100], 95))
    # the whole feed costs at least the tracker's sleep; the tracker-only part too; nothing over 100 ms
    assert tm["process_frame_ms_p50"] >= 20.0 and tm["track_ms_p50"] >= 20.0
    assert tm["process_frame_ms_mean"] >= tm["track_ms_mean"] >= 20.0
    assert tm["process_frame_ms_p95"] >= tm["process_frame_ms_p50"] and tm["process_frame_ms_max"] >= tm["process_frame_ms_p95"]
    assert tm["frames_over_100ms"] == 0
    assert tm["keyframe_ms_mean"] is None and tm["non_keyframe_ms_mean"] >= 20.0  # black frames never initialise

    slow = LiveSession("slow", tracker_factory=lambda intr, cfg: SlowSleeper(intr, cfg))
    for i in range(3):
        slow.feed(data, i, 0.1 * i)
    assert slow.timing_summary()["frames_over_100ms"] == 3

    empty = LiveSession("empty").timing_summary()
    assert empty["frames"] == 0 and empty["delivered_fps"] is None and empty["process_frame_ms_p50"] is None


def test_finished_live_session_report_has_timing_even_when_it_never_initialised(tmp_path):
    app = create_app(outputs_root=tmp_path)
    with TestClient(app) as client:
        black = jpeg(np.zeros((120, 160, 3), np.uint8))
        with client.websocket_connect("/live/timed") as ws:
            for _ in range(4):
                ws.send_bytes(black)
                ws.receive_json()
            ws.send_text(json.dumps({"cmd": "finish"}))
            done = ws.receive_json()
    report = json.loads((Path(done["run_dir"]) / "tracking_report.json").read_text())
    tm = report["timing"]
    assert tm is not None and tm["frames"] == 4
    for key in ("process_frame_ms_mean", "process_frame_ms_p50", "process_frame_ms_p95", "interarrival_ms_mean",
                "interarrival_ms_p50", "interarrival_ms_p95", "delivered_fps"):
        assert tm[key] is not None and tm[key] >= 0, key
    assert tm["frames_over_100ms"] >= 0
    status = json.loads((Path(done["run_dir"]) / "run_status.json").read_text())
    assert status["live"]["timing"] == tm and status["stages"]["live_tracking"] == "failed"
