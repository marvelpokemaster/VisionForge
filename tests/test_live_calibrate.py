"""Phone intrinsics: the phone_default stopgap and its scaling through the
live downscale, calibration intrinsics rescaled from the calibration frame
size, and `visionforge calibrate` (live/calibrate.py) with a faked COLMAP."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from visionforge import cli
from visionforge.live.calibrate import calibration_from_cameras, frame_size_of, run_calibration
from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.live.session import LiveSession


def jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    assert ok
    return buf.tobytes()


# ------------------------------------------------------------ phone_default
def test_phone_default_is_0_8_times_the_longer_side_at_the_centre_in_both_orientations():
    p = CameraIntrinsics.phone_default(640, 1138)  # the first real-phone run's portrait frames
    assert (p.fx, p.fy, p.cx, p.cy, p.k1, p.source) == (0.8 * 1138, 0.8 * 1138, 320.0, 569.0, 0.0, "phone_default")
    l = CameraIntrinsics.phone_default(1280, 720)
    assert l.fx == l.fy == 0.8 * 1280 and (l.cx, l.cy) == (640.0, 360.0)
    g = CameraIntrinsics.guess_for_frame(640, 1138)
    assert g.fx == 1138.0 and p.fx < g.fx  # the stopgap is a wider field of view than the CLI's guess


def test_phone_default_sent_by_the_client_is_scaled_with_the_server_downscale():
    # the client computes it for the size it SENDS; the server downscales 1280 -> 320 here
    sent = CameraIntrinsics.phone_default(1280, 720)
    s = LiveSession("pd", max_width=320)
    reply = s.configure({"width": 1280, "height": 720, "intrinsics": {**sent.to_dict()}})
    intr = s.tracker.intrinsics
    assert reply["intrinsics"]["source"] == "phone_default" and s.processed_size == (320, 180)
    assert (intr.fx, intr.fy, intr.cx, intr.cy) == (0.8 * 320, 0.8 * 320, 160.0, 90.0)
    # i.e. identical to computing the default for the processed size directly
    assert intr.to_dict() == CameraIntrinsics.phone_default(320, 180).to_dict()
    with pytest.raises(ValueError, match="intrinsics.source"):
        LiveSession("bad").configure({"intrinsics": {"fx": 1, "fy": 1, "cx": 1, "cy": 1, "source": "made_up"}})


# ----------------------------------------------- calibration intrinsics size
def test_calibration_intrinsics_are_rescaled_from_their_frame_size_then_downscaled():
    # calibrated at 1080x1920 portrait (fx 1500), live frames arrive at 640x1138 (phone already downscaled),
    # server max_width 640 -> no further downscale: fx must become 1500 * 640/1080
    cams = [{"camera_model": "SIMPLE_RADIAL", "camera_params": [1500.0, 540.0, 960.0, -0.02], "width": 1080, "height": 1920}]
    s = LiveSession("cal", max_width=640)
    reply = s.configure({"width": 640, "height": 1138, "intrinsics_from_cameras": cams})
    intr = s.tracker.intrinsics
    k = 640 / 1080
    assert reply["intrinsics"]["source"] == "colmap"
    assert intr.fx == pytest.approx(1500 * k) and intr.cx == pytest.approx(540 * k) and intr.cy == pytest.approx(960 * k)
    assert intr.k1 == -0.02  # normalised, never scaled
    # ... and the usual processed-size downscale still applies on top (320 wide)
    s2 = LiveSession("cal2", max_width=320)
    s2.configure({"width": 640, "height": 1138, "intrinsics_size": [1080, 1920],
                  "intrinsics": {"fx": 1500, "fy": 1500, "cx": 540, "cy": 960}})
    assert s2.processed_size == (320, 569)
    assert s2.tracker.intrinsics.fx == pytest.approx(1500 * (320 / 1080))
    # the size can also arrive only with the frames
    s3 = LiveSession("cal3", max_width=640)
    s3.configure({"intrinsics_from_cameras": cams})
    s3.feed(jpeg(np.zeros((1138, 640, 3), np.uint8)), 0, 0.0)
    assert s3.tracker.intrinsics.fx == pytest.approx(1500 * k)
    # a landscape calibration for portrait frames is refused, not silently stretched
    with pytest.raises(ValueError, match="aspect ratio"):
        LiveSession("cal4").configure({"width": 640, "height": 1138, "intrinsics_size": [1920, 1080],
                                       "intrinsics": {"fx": 1500, "fy": 1500, "cx": 960, "cy": 540}})


# ------------------------------------------------------------------ calibrate
def test_calibration_from_cameras_takes_the_median_and_tags_the_size():
    cams = [{"id": 1, "name": "frame_000000", "camera_model": "SIMPLE_RADIAL", "camera_params": [1500.0, 540.0, 960.0, -0.02]},
            {"id": 2, "name": "frame_000001", "camera_model": "SIMPLE_RADIAL", "camera_params": [1520.0, 541.0, 958.0, -0.01]},
            {"id": 3, "name": "frame_000002", "camera_model": "SIMPLE_RADIAL", "camera_params": [1490.0, 539.0, 961.0, -0.03]}]
    out = calibration_from_cameras(cams, 1080, 1920, video="clip.mp4")
    assert len(out) == 4 and out[0]["name"] == "median" and out[0]["n_cameras"] == 3
    assert out[0]["camera_params"] == [1500.0, 540.0, 960.0, -0.02]
    assert all(e["width"] == 1080 and e["height"] == 1920 and e["camera_model"] == "SIMPLE_RADIAL" for e in out)
    assert [e["name"] for e in out[1:]] == ["frame_000000", "frame_000001", "frame_000002"]
    # the median entry is a valid intrinsics_from_cameras[0]
    intr = CameraIntrinsics.from_colmap_params(out[0]["camera_model"], out[0]["camera_params"])
    assert (intr.fx, intr.cx, intr.cy, intr.k1) == (1500.0, 540.0, 960.0, -0.02)
    with pytest.raises(ValueError, match="registered no cameras"):
        calibration_from_cameras([], 1, 1)
    with pytest.raises(ValueError, match="mixes camera models"):
        calibration_from_cameras(cams[:1] + [{**cams[1], "camera_model": "PINHOLE", "camera_params": [1, 1, 1, 1]}], 1, 1)


def fake_stages(tmp_path, n_cameras=3, write_cameras=True):
    """A run_stage that writes what P0 and P1 would, without COLMAP."""
    def run_stage(cmd, description):
        if "visionforge.video.extract_frames" in cmd:
            out = Path(cmd[cmd.index("--output") + 1]) / "frames"
            out.mkdir(parents=True)
            for i in range(n_cameras):
                cv2.imwrite(str(out / f"frame_{i:06d}.jpg"), np.zeros((1920, 1080, 3), np.uint8))
        elif "visionforge.reconstruction.pipeline" in cmd:
            if not write_cameras:
                return
            rec = Path(cmd[cmd.index("--output") + 1]) / "reconstruction"
            rec.mkdir(parents=True)
            cams = [{"id": i + 1, "name": f"frame_{i:06d}", "rotation_quat": [0, 0, 0, 1], "translation": [0, 0, 0],
                     "camera_model": "SIMPLE_RADIAL", "camera_params": [1500.0 + 10 * i, 540.0, 960.0, -0.02]}
                    for i in range(n_cameras)]
            (rec / "cameras.json").write_text(json.dumps(cams))
        else:
            raise AssertionError(cmd)
    return run_stage


def test_run_calibration_runs_p0_p1_and_writes_the_median_first(tmp_path):
    video = tmp_path / "phone.mp4"
    video.write_bytes(b"not really a video; the stages are faked")
    out = tmp_path / "iqoo.json"
    result = run_calibration(video, out, tmp_path / "work", fps=2.0, max_frames=50, run_stage=fake_stages(tmp_path))
    written = json.loads(out.read_text())
    assert written == result and written[0]["name"] == "median" and written[0]["camera_params"] == [1510.0, 540.0, 960.0, -0.02]
    assert written[0]["width"] == 1080 and written[0]["height"] == 1920 and written[0]["source_video"] == str(video)
    assert frame_size_of(tmp_path / "work" / "p0" / "frames") == (1080, 1920)
    # the file is directly usable by the CLI's --intrinsics-from and by the live protocol
    intr = CameraIntrinsics.from_cameras_json(out)
    assert intr.fx == 1510.0 and intr.source == "colmap"
    s = LiveSession("use", max_width=640)
    s.configure({"width": 640, "height": 1138, "intrinsics_from_cameras": written})
    assert s.tracker.intrinsics.fx == pytest.approx(1510.0 * 640 / 1080)
    with pytest.raises(ValueError, match="could not reconstruct"):
        run_calibration(video, tmp_path / "x.json", tmp_path / "work2", run_stage=fake_stages(tmp_path, write_cameras=False))


def test_cli_calibrate_command_is_wired(tmp_path, monkeypatch, capsys):
    video = tmp_path / "phone.mp4"
    video.write_bytes(b"fake")
    out = tmp_path / "cal" / "iqoo.json"
    monkeypatch.setattr(cli, "_run_stage", fake_stages(tmp_path))
    monkeypatch.setattr(sys, "argv", ["visionforge", "calibrate", "--video", str(video), "--output", str(out)])
    cli.main()
    assert out.exists() and (tmp_path / "cal" / "iqoo_work" / "p1").exists()
    assert "median SIMPLE_RADIAL" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["visionforge", "calibrate", "--video", str(tmp_path / "missing.mp4"), "--output", str(out)])
    with pytest.raises(SystemExit):
        cli.main()
