"""scripts/compare_trajectories.py on a synthetic case with a known sim(3)."""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from visionforge.live.compare import camera_centres, compare_trajectories, frame_number, ref_step_from_run_dir
from visionforge.live.tracker import rotation_matrix_to_quat_xyzw

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_trajectories.py"


def _cameras(centres, rotations, names):
    cams = []
    for i, (C, R, name) in enumerate(zip(centres, rotations, names)):
        t = -R @ C
        cams.append({"id": i + 1, "name": name, "rotation_quat": rotation_matrix_to_quat_xyzw(R),
                     "translation": t.tolist(), "camera_model": "PINHOLE", "camera_params": [1, 1, 1, 1]})
    return cams


@pytest.fixture
def synthetic_pair():
    rng = np.random.default_rng(7)
    n = 20
    gt = np.c_[np.linspace(-2, 2, n), 0.3 * np.sin(np.linspace(0, 3, n)), 0.1 * np.arange(n)]
    rots = [cv2.Rodrigues(rng.normal(size=3) * 0.2)[0] for _ in range(n)]
    # the "live" trajectory is the ground truth under a random sim(3) + noise, named by video frame
    R_s, _ = cv2.Rodrigues(np.array([0.4, -0.2, 1.1]))
    s, t = 0.37, np.array([3.0, -1.0, 2.0])
    noise = 0.01
    live_c = (s * (R_s @ gt.T)).T + t + rng.normal(0, noise, gt.shape)
    live = _cameras(live_c, [R_s @ R for R in rots], [f"frame_{i:06d}" for i in range(n)])
    # the reference is sampled every 3rd video frame with P0's 1-based names
    ref_idx = list(range(0, n, 3))
    ref = _cameras(gt[ref_idx], [rots[i] for i in ref_idx], [f"frame_{k + 1:06d}.jpg" for k in range(len(ref_idx))])
    return live, ref, s, noise


def test_frame_number_parsing():
    assert frame_number("frame_000012.jpg") == 12
    assert frame_number("frame_000000") == 0
    assert frame_number("no digits") is None


def test_camera_centres_recovers_centre_from_cam_from_world():
    R, _ = cv2.Rodrigues(np.array([0.1, 0.2, 0.3]))
    C = np.array([1.0, 2.0, 3.0])
    cams = _cameras([C], [R], ["frame_000005"])
    out = camera_centres(cams)
    assert list(out) == [5] and np.allclose(out[5], C, atol=1e-9)


def test_compare_matches_by_video_frame_and_recovers_scale(synthetic_pair):
    live, ref, s, noise = synthetic_pair
    res = compare_trajectories(live, ref, ref_step=3)
    assert res["n_live"] == 20 and res["n_ref"] == 7 and res["n_matched"] == 7
    assert res["matched_video_frames"] == [0, 3, 6, 9, 12, 15, 18]
    assert res["scale"] == pytest.approx(1.0 / s, rel=0.02)
    assert res["rmse"] < 3 * noise / s
    assert set(res["per_camera_residual"]) == {0, 3, 6, 9, 12, 15, 18}
    # the wrong step pairs reference cameras with the wrong live frames: clearly worse
    wrong = compare_trajectories(live, ref, ref_step=1)
    assert wrong["matched_video_frames"] == [0, 1, 2, 3, 4, 5, 6]
    assert wrong["rmse"] > 2 * res["rmse"]


def test_compare_too_few_matches_is_reported_not_faked(synthetic_pair):
    live, ref, _, _ = synthetic_pair
    res = compare_trajectories(live[:2], ref, ref_step=3)
    assert res["n_matched"] < 3 and res["rmse"] is None and "note" in res


def test_ref_step_from_metadata(tmp_path):
    (tmp_path / "p0").mkdir()
    (tmp_path / "p0" / "metadata.json").write_text(json.dumps({"original_fps": 30.0, "sampling_fps": 2.0}))
    assert ref_step_from_run_dir(tmp_path) == 15
    assert ref_step_from_run_dir(tmp_path / "nope") is None


def test_script_end_to_end(tmp_path, synthetic_pair):
    live, ref, s, _ = synthetic_pair
    live_dir = tmp_path / "live" / "p1" / "reconstruction"
    ref_dir = tmp_path / "ref" / "p1" / "reconstruction"
    live_dir.mkdir(parents=True)
    ref_dir.mkdir(parents=True)
    (live_dir / "cameras.json").write_text(json.dumps(live))
    (ref_dir / "cameras.json").write_text(json.dumps(ref))
    (tmp_path / "ref" / "p0").mkdir()
    (tmp_path / "ref" / "p0" / "metadata.json").write_text(json.dumps({"original_fps": 6.0, "sampling_fps": 2.0}))
    out = tmp_path / "cmp.json"
    proc = subprocess.run([sys.executable, str(SCRIPT), "--live", str(tmp_path / "live"), "--ref", str(tmp_path / "ref"),
                           "--output", str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "matched by video frame: 7" in proc.stdout
    data = json.loads(out.read_text())
    assert data["ref_step"] == 3 and data["n_matched"] == 7
    assert data["scale"] == pytest.approx(1.0 / s, rel=0.02)
