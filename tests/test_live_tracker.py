"""Unit tests for the live tracker on synthetic data with KNOWN ground truth.

Feature-tracking strategy: an injectable "oracle" feature tracker
(``OracleFeatureTracker``) that projects the known 3D box points with the
known camera poses (+0.5 px Gaussian noise) and tracks them by identity.
Why: these tests verify the tracker's geometry and state machine (parallax
gating, essential-matrix initialisation, PnP, keyframe policy,
triangulation, LOST handling), not OpenCV's Lucas-Kanade; identity tracking
gives ground-truth correspondence per feature so cheirality / trajectory /
map assertions can be tight and deterministic. The oracle goes blind on
all-black frames so the LOST test exercises real frame content. The real
KLT path is covered once here by a rendered-white-dots smoke test
(``test_real_klt_tracker_on_rendered_dots``) and by the mp4 integration run
documented in docs/live_tracking.md.
"""
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from visionforge.live.alignment import umeyama_alignment, align_and_evaluate
from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.live.tracker import (LiveTracker, TrackerConfig, TrackState, rotation_matrix_to_quat_xyzw,
                                      triangulate_checked)
from visionforge.spatial.scene_graph import _quat_to_rotation_matrix

W, H = 640, 480
K = np.array([[640.0, 0, 320.0], [0, 640.0, 240.0], [0, 0, 1.0]])
INTR = CameraIntrinsics(640.0, 640.0, 320.0, 240.0, 0.0, "guess")


# ----------------------------------------------------------------- fixtures
def box_points(n_per_face=150, seed=1):
    """Points on the 6 faces of a 6 x 2.5 x 6 box room (same layout as
    scripts/generate_synthetic_clip.py): floor y=0, ceiling y=2.5, walls x=+-3, z=+-3."""
    rng = np.random.default_rng(seed)
    pts = []
    for _ in range(n_per_face):
        x, z = rng.uniform(-3, 3, 2)
        pts.append((x, 0.0, z))
        x, z = rng.uniform(-3, 3, 2)
        pts.append((x, 2.5, z))
        y, z = rng.uniform(0, 2.5), rng.uniform(-3, 3)
        pts.append((-3.0, y, z))
        y, z = rng.uniform(0, 2.5), rng.uniform(-3, 3)
        pts.append((3.0, y, z))
        x, y = rng.uniform(-3, 3), rng.uniform(0, 2.5)
        pts.append((x, y, -3.0))
        x, y = rng.uniform(-3, 3), rng.uniform(0, 2.5)
        pts.append((x, y, 3.0))
    return np.array(pts, dtype=np.float64)


def look_at(eye, target, up=(0, 1, 0)):
    eye, target, up = (np.asarray(v, dtype=np.float64) for v in (eye, target, up))
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z], axis=0)
    return R, -R @ eye


EYE_Y, EYE_Z, PITCH_DOWN_DEG = 0.9, 2.4, 8.0  # low camera pitched down: floor points span depth ~1.5-5.4


def translating_path(n=30, step=0.08, duration=None):
    """Dolly in x with a small, varying yaw/pitch, looking towards the far
    wall with the floor in the lower half of the frame (so the view holds a
    real spread of depths, not one dominant plane). The path is parametrised
    by "time" u in original-frame units: u = i by default; with ``duration``
    the SAME path (u from 0 to duration) is resampled with n frames, e.g.
    translating_path(360, duration=29) is translating_path(30) at 12x the
    frame rate."""
    poses = []
    for i in range(n):
        u = i if duration is None else i * duration / (n - 1)
        x = -1.2 + step * u
        yaw = math.radians(5.0 * math.sin(u / 6.0))
        pitch = math.radians(-PITCH_DOWN_DEG + 3.0 * math.cos(u / 5.0))
        eye = (x, EYE_Y, EYE_Z)
        target = (x + 4.0 * math.sin(yaw), EYE_Y + 4.0 * math.sin(pitch), EYE_Z - 4.0 * math.cos(yaw))
        poses.append(look_at(eye, target))
    return poses


def rotating_path(n=30, deg_per_frame=1.0):
    eye = (0.0, EYE_Y, EYE_Z)
    pitch = math.radians(-PITCH_DOWN_DEG)
    poses = []
    for i in range(n):
        yaw = math.radians(deg_per_frame * i)
        target = (4.0 * math.sin(yaw), EYE_Y + 4.0 * math.sin(pitch), EYE_Z - 4.0 * math.cos(yaw))
        poses.append(look_at(eye, target))
    return poses


def static_path(n=30):
    return [look_at((0.0, EYE_Y, EYE_Z), (0.0, EYE_Y - 0.5, -2.0))] * n


def project_points(pts, R, t):
    cam = (R @ pts.T).T + t
    z = cam[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = (K @ cam.T).T
        uv = uv[:, :2] / uv[:, 2:3]
    visible = (z > 0.2) & (uv[:, 0] >= 2) & (uv[:, 0] < W - 2) & (uv[:, 1] >= 2) & (uv[:, 1] < H - 2)
    return uv, visible


def render_frame(pts, R, t, radius=2):
    img = np.zeros((H, W), dtype=np.uint8)
    uv, vis = project_points(pts, R, t)
    for (u, v), ok in zip(uv, vis):
        if ok:
            cv2.circle(img, (int(round(u)), int(round(v))), radius, 255, -1)
    return img


class OracleFeatureTracker:
    """Projects known 3D points with known poses; tracks by identity; blind on black frames."""

    def __init__(self, pts, poses, noise_px=0.5, seed=0):
        self.pts = pts
        self.poses = poses
        self.noise = noise_px
        self.rng = np.random.default_rng(seed)

    def _observe(self, frame_index):
        R, t = self.poses[frame_index]
        uv, vis = project_points(self.pts, R, t)
        uv = uv + self.rng.normal(0.0, self.noise, uv.shape)
        return uv, vis

    def detect(self, gray, frame_index, existing_pts, existing_ids, max_new):
        if gray.max() == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.int64)
        uv, vis = self._observe(frame_index)
        taken = set(int(i) for i in existing_ids)
        ids = [i for i in np.flatnonzero(vis) if i not in taken][:max_new]
        return uv[ids].astype(np.float32), np.array(ids, dtype=np.int64)

    def track(self, prev_gray, gray, prev_pts, prev_ids, frame_index):
        if gray.max() == 0:
            return np.zeros((len(prev_ids), 2), np.float32), np.zeros(len(prev_ids), bool)
        uv, vis = self._observe(frame_index)
        return uv[prev_ids].astype(np.float32), vis[prev_ids]


def run_sequence(poses, pts=None, black_frames=(), config=None, oracle=True):
    pts = box_points() if pts is None else pts
    frames = []
    for i, (R, t) in enumerate(poses):
        if i in black_frames:
            frames.append(np.zeros((H, W), np.uint8))
        else:
            frames.append(render_frame(pts, R, t))
    ft = OracleFeatureTracker(pts, poses) if oracle else None
    cv2.setRNGSeed(0)  # OpenCV's RANSACs are randomised; keep the runs reproducible
    tracker = LiveTracker(INTR, config or TrackerConfig(), feature_tracker=ft)
    results = [tracker.process_frame(f, i) for i, f in enumerate(frames)]
    return tracker, results


def centers_of(poses):
    return np.array([-R.T @ t for R, t in poses])


# --------------------------------------------------------------- intrinsics
def test_from_colmap_params_simple_radial_matches_cameras_json_values():
    # values copied from outputs/final_demo/p1/reconstruction/cameras.json (COLMAP SIMPLE_RADIAL)
    intr = CameraIntrinsics.from_colmap_params("SIMPLE_RADIAL", [794.9717754327129, 400.0, 300.0, 0.004549276421607342])
    assert intr.fx == pytest.approx(794.9717754327129)
    assert intr.fy == pytest.approx(794.9717754327129)
    assert intr.cx == 400.0 and intr.cy == 300.0
    assert intr.k1 == pytest.approx(0.004549276421607342)
    assert intr.source == "colmap"
    assert intr.K[0, 0] == pytest.approx(794.9717754327129) and intr.K[1, 2] == 300.0


def test_from_colmap_params_pinhole_and_errors():
    intr = CameraIntrinsics.from_colmap_params("PINHOLE", [700, 710, 320, 240])
    assert (intr.fx, intr.fy, intr.cx, intr.cy, intr.k1) == (700, 710, 320, 240, 0.0)
    with pytest.raises(ValueError):
        CameraIntrinsics.from_colmap_params("OPENCV", [1, 2, 3, 4, 5, 6, 7, 8])


def test_from_cameras_json_reads_first_entry(tmp_path):
    cams = [{"camera_model": "SIMPLE_RADIAL", "camera_params": [800.0, 400.0, 300.0, 0.01]}]
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps(cams))
    intr = CameraIntrinsics.from_cameras_json(p)
    assert intr.fx == 800.0 and intr.cx == 400.0 and intr.k1 == 0.01 and intr.source == "colmap"


def test_guess_for_frame_is_max_dimension_at_centre():
    intr = CameraIntrinsics.guess_for_frame(800, 600)
    assert (intr.fx, intr.fy, intr.cx, intr.cy) == (800.0, 800.0, 400.0, 300.0)
    assert intr.source == "guess"


def test_undistort_points_identity_without_k1_and_moves_with_k1():
    pts = np.array([[100.0, 50.0], [600.0, 400.0]])
    assert np.allclose(INTR.undistort_points(pts), pts)
    distorted = CameraIntrinsics(640, 640, 320, 240, 0.05)
    out = distorted.undistort_points(pts)
    assert not np.allclose(out, pts)
    # the principal point itself is a fixed point of radial distortion
    assert np.allclose(distorted.undistort_points(np.array([[320.0, 240.0]])), [[320.0, 240.0]], atol=1e-6)


# --------------------------------------------------------- geometry helpers
def test_quaternion_matches_consumer_convention():
    rng = np.random.default_rng(3)
    for _ in range(20):
        R, _ = cv2.Rodrigues(rng.normal(size=3))
        q = rotation_matrix_to_quat_xyzw(R)
        assert np.linalg.norm(q) == pytest.approx(1.0)
        assert np.allclose(_quat_to_rotation_matrix(*q), R, atol=1e-9)


def test_umeyama_recovers_known_similarity():
    rng = np.random.default_rng(0)
    src = rng.normal(size=(40, 3))
    R_true, _ = cv2.Rodrigues(np.array([0.3, -0.5, 0.9]))
    s_true, t_true = 2.5, np.array([1.0, -2.0, 0.5])
    dst = (s_true * (R_true @ src.T)).T + t_true
    sim = umeyama_alignment(src, dst)
    assert sim.scale == pytest.approx(s_true, rel=1e-9)
    assert np.allclose(sim.R, R_true, atol=1e-9)
    assert np.allclose(sim.t, t_true, atol=1e-9)
    noisy = dst + rng.normal(0, 0.01, dst.shape)
    res = align_and_evaluate(src, noisy)
    assert res.rmse < 0.02


def test_triangulate_checked_rejects_behind_camera_and_accepts_good():
    pts = box_points(20)
    (R1, t1), (R2, t2) = look_at((-0.5, 1.4, 2.4), (0, 1.4, -2)), look_at((0.5, 1.4, 2.4), (0, 1.4, -2))
    uv1, v1 = project_points(pts, R1, t1)
    uv2, v2 = project_points(pts, R2, t2)
    vis = v1 & v2
    X, acc, err, _ang = triangulate_checked(K, R1, t1, R2, t2, uv1[vis], uv2[vis], 1.0, 0.5)
    assert acc.sum() == vis.sum()
    assert np.allclose(X, pts[vis], atol=1e-6)
    # zero baseline (both views identical): triangulation angle is 0 -> the angle gate rejects everything
    _, acc_zero, _, _ = triangulate_checked(K, R1, t1, R1, t1, uv1[vis], uv1[vis], 1.0, 0.5)
    assert acc_zero.sum() == 0
    # points BEHIND both cameras: their (mathematically valid) projections triangulate to negative depth
    behind = pts.copy()
    behind[:, 2] = 2.4 + 3.0 + (3.0 - behind[:, 2])  # mirror the box to z > camera z
    cam1 = (R1 @ behind.T).T + t1
    cam2 = (R2 @ behind.T).T + t2
    assert (cam1[:, 2] < 0).all() and (cam2[:, 2] < 0).all()
    b1 = (K @ cam1.T).T; b1 = b1[:, :2] / b1[:, 2:3]
    b2 = (K @ cam2.T).T; b2 = b2[:, :2] / b2[:, 2:3]
    _, acc_behind, _, _ = triangulate_checked(K, R1, t1, R2, t2, b1, b2, 1.0, 0.5)
    assert acc_behind.sum() == 0


# ------------------------------------------------------------ state machine
def test_static_sequence_never_initialises():
    tracker, results = run_sequence(static_path())
    assert all(r.state == TrackState.INITIALIZING for r in results)
    assert all(r.pose is None for r in results)
    assert tracker.segments == []


def test_pure_rotation_never_initialises():
    tracker, results = run_sequence(rotating_path(30, 1.0))
    assert all(r.state == TrackState.INITIALIZING for r in results), [r.state for r in results]
    assert tracker.segments == []


def test_initialises_once_parallax_threshold_crossed():
    # 0.012 units/frame at ~3 units depth is ~2.5 px/frame: the 10 px gate needs ~4 frames,
    # so the first frames MUST stay INITIALIZING and a later one MUST become TRACKING.
    tracker, results = run_sequence(translating_path(30, step=0.012))
    states = [r.state for r in results]
    first_tracking = states.index(TrackState.TRACKING)
    assert first_tracking >= 3, states
    assert all(s == TrackState.INITIALIZING for s in states[:first_tracking])
    assert results[first_tracking].is_keyframe
    assert results[first_tracking].pose is not None
    assert len(tracker.segments) == 1
    assert tracker.segments[0].keyframes[0].frame_index == 0


def test_tracking_states_and_poses_are_consistent():
    tracker, results = run_sequence(translating_path())
    for r in results:
        if r.state == TrackState.TRACKING:
            assert r.pose is not None and r.n_inliers >= TrackerConfig().pnp_min_inliers
            assert r.reprojection_rms is not None and r.reprojection_rms < 2.0
        else:
            assert r.pose is None and r.reprojection_rms is None
    assert sum(r.state == TrackState.TRACKING for r in results) >= 26


def test_recovered_trajectory_matches_ground_truth_up_to_sim3():
    poses = translating_path()
    tracker, results = run_sequence(poses)
    gt = centers_of(poses)
    # keyframe centres
    seg = tracker.exported_segment()
    kf_idx = [kf.frame_index for kf in seg.keyframes]
    assert len(kf_idx) >= 3
    est = np.array([kf.center for kf in seg.keyframes])
    res = align_and_evaluate(est, gt[kf_idx])
    # tolerance: 2% of the ground-truth trajectory extent (path is 2.32 units long -> < 0.046 units)
    assert res.rmse < 0.02 * res.reference_extent, (res.rmse, res.reference_extent)
    # every TRACKING frame's pose (not only keyframes)
    tr_idx = [r.frame_index for r in results if r.state == TrackState.TRACKING]
    est_all = np.array([-r.pose[0].T @ r.pose[1] for r in results if r.state == TrackState.TRACKING])
    res_all = align_and_evaluate(est_all, gt[tr_idx])
    assert res_all.rmse < 0.02 * res_all.reference_extent, (res_all.rmse, res_all.reference_extent)
    # rotations: the estimate's world frame IS keyframe 0's camera frame, so every
    # estimated R must equal the ground-truth rotation relative to keyframe 0
    # (no alignment needed). Measured: <= 1.0 deg drift at the end of the path.
    R0_gt = poses[seg.keyframes[0].frame_index][0]
    for r in results:
        if r.state == TrackState.TRACKING:
            R_rel_gt = poses[r.frame_index][0] @ R0_gt.T
            ang = math.degrees(math.acos(np.clip((np.trace(r.pose[0] @ R_rel_gt.T) - 1) / 2, -1, 1)))
            assert ang < 2.0, (r.frame_index, ang)


def test_triangulated_points_have_positive_depth_in_both_keyframes_and_match_gt():
    poses = translating_path()
    pts = box_points()
    tracker, results = run_sequence(poses, pts)
    seg = tracker.exported_segment()
    assert len(seg.map_points) > 100
    for mp in seg.map_points.values():
        for kf_ord in (mp.kf_a, mp.kf_b):
            kf = seg.keyframes[kf_ord]
            depth = (kf.R @ mp.xyz + kf.t)[2]
            assert depth > 0, (mp.id, kf_ord, depth)
    # the map matches the ground-truth 3D points (the oracle's feature id IS the point index).
    # Compared in the estimate's own frame -- keyframe 0's camera frame with a unit baseline to
    # keyframe 1 -- by mapping ground truth into it; no fitted alignment (the camera centres are
    # nearly collinear, which would leave a camera-only sim3's roll undetermined).
    gt = centers_of(poses)
    R0, t0 = poses[seg.keyframes[0].frame_index]
    scale = 1.0 / np.linalg.norm(gt[seg.keyframes[1].frame_index] - gt[seg.keyframes[0].frame_index])
    mps = list(seg.map_points.values())
    est_pts = np.array([mp.xyz for mp in mps]) / scale                      # -> ground-truth units
    gt_pts_in_est_frame = (R0 @ pts[[mp.feature_id for mp in mps]].T).T + t0
    err = np.linalg.norm(est_pts - gt_pts_in_est_frame, axis=1)
    # measured: median 0.06, p90 0.19 in a 6 x 2.5 x 6 room (two-view triangulation, no BA)
    assert np.median(err) < 0.15, np.median(err)
    assert np.percentile(err, 90) < 0.40, np.percentile(err, 90)
    # map points that were re-triangulated from a wider baseline record that pair
    assert all(mp.kf_a < mp.kf_b for mp in mps)
    assert any(mp.kf_b - mp.kf_a > 1 for mp in mps)


def test_map_does_not_grow_on_non_keyframes():
    tracker, results = run_sequence(translating_path())
    prev = 0
    saw_non_kf_while_tracking = False
    for r in results:
        if r.state == TrackState.TRACKING and not r.is_keyframe:
            assert r.map_size == prev, (r.frame_index, r.map_size, prev)
            saw_non_kf_while_tracking = True
        prev = r.map_size
    assert saw_non_kf_while_tracking
    assert sum(r.is_keyframe for r in results) < sum(r.state == TrackState.TRACKING for r in results)


def test_black_cut_produces_lost_episode_with_none_poses_then_reinitialises():
    poses = translating_path(45)
    black = set(range(15, 25))
    tracker, results = run_sequence(poses, black_frames=black)
    states = [r.state for r in results]
    assert states[14] == TrackState.TRACKING
    for i in black:
        assert states[i] == TrackState.LOST and results[i].pose is None, (i, states[i])
    episodes = tracker.lost_episodes()
    assert len(episodes) == 1 and episodes[0]["start"] == 15
    assert episodes[0]["end"] >= 24
    # re-initialised afterwards, in a NEW segment (never stitched to the old one)
    assert TrackState.TRACKING in states[25:], states[25:]
    assert len(tracker.segments) == 2
    assert tracker.segments[1].start_frame >= 25
    # map size during LOST is 0 (no active segment) and nothing was added to the old segment
    old_map = len(tracker.segments[0].map_points)
    for i in black:
        assert results[i].map_size == 0
    assert len(tracker.segments[0].map_points) == old_map
    rep = tracker.report()
    assert rep["lost_episodes"] == episodes
    assert rep["state_counts"]["LOST"] == sum(s == TrackState.LOST for s in states)


def test_pnp_inlier_collapse_is_reported_lost_not_faked():
    # a tracker whose config demands more PnP inliers than the scene can give must go LOST
    cfg = TrackerConfig(pnp_min_inliers=100000)
    tracker, results = run_sequence(translating_path(12), config=cfg)
    assert any(r.state == TrackState.LOST for r in results)
    assert all(r.pose is None for r in results if r.state == TrackState.LOST)


# ------------------------------------------------------------------ export
def test_export_writes_exact_cameras_json_schema_and_report(tmp_path):
    poses = translating_path()
    tracker, results = run_sequence(poses)
    report = tracker.export(tmp_path, video="synthetic")
    cams = json.loads((tmp_path / "p1" / "reconstruction" / "cameras.json").read_text())
    seg = tracker.exported_segment()
    assert len(cams) == len(seg.keyframes)
    for cam, kf in zip(cams, seg.keyframes):
        assert set(cam.keys()) == {"id", "name", "rotation_quat", "translation", "camera_model", "camera_params"}
        assert isinstance(cam["id"], int)
        assert cam["name"] == f"frame_{kf.frame_index:06d}"
        q = np.array(cam["rotation_quat"])
        assert q.shape == (4,) and np.linalg.norm(q) == pytest.approx(1.0, abs=1e-9)
        assert np.allclose(_quat_to_rotation_matrix(*q), kf.R, atol=1e-9)
        assert np.allclose(cam["translation"], kf.t)
        assert cam["camera_model"] == "PINHOLE"
        assert cam["camera_params"] == [640.0, 640.0, 320.0, 240.0]
    ply = (tmp_path / "p1" / "reconstruction" / "sparse_cloud.ply").read_text().splitlines()
    assert ply[0] == "ply" and f"element vertex {len(seg.map_points)}" in ply
    assert len(ply) == ply.index("end_header") + 1 + len(seg.map_points)

    rep = json.loads((tmp_path / "tracking_report.json").read_text())
    assert rep == json.loads(json.dumps(report))
    for key in ("frames", "keyframes", "n_keyframes", "state_counts", "tracking_fraction", "lost_episodes",
                "map_size", "mean_reprojection_rms", "intrinsics", "intrinsics_source", "segments", "config", "video"):
        assert key in rep, key
    assert rep["frames"] == 30 and rep["intrinsics_source"] == "guess" and rep["video"] == "synthetic"
    assert rep["keyframes"] == [kf.frame_index for kf in seg.keyframes]
    assert rep["map_size"] == len(seg.map_points)
    assert set(rep["state_counts"]) == {"INITIALIZING", "TRACKING", "LOST"}
    assert rep["mean_reprojection_rms"] is not None and rep["mean_reprojection_rms"] < 2.0


def test_export_without_initialisation_writes_empty_but_valid_files(tmp_path):
    tracker, _ = run_sequence(static_path(5))
    rep = tracker.export(tmp_path)
    assert json.loads((tmp_path / "p1" / "reconstruction" / "cameras.json").read_text()) == []
    assert rep["n_keyframes"] == 0 and rep["map_size"] == 0 and rep["exported_segment"] is None


def test_30fps_resampled_path_keyframes_are_a_small_fraction_of_frames():
    """The 30-frame fixture path resampled to 360 frames (the same motion at
    12x the frame rate, like a 30 fps phone instead of the 2 fps synthetic
    clip): the keyframe policy must be driven by parallax, not by frame
    count, so keyframes must stay a small fraction of frames while tracking
    stays continuous and accurate. Measured: 13 keyframes (3.6 %), 344/360
    TRACKING, sim(3) RMSE 0.24 % of extent."""
    poses = translating_path(360, duration=29)
    assert np.allclose(centers_of(poses)[[0, 359]], centers_of(translating_path(30))[[0, 29]])
    tracker, results = run_sequence(poses)
    states = [r.state for r in results]
    seg = tracker.exported_segment()
    n_kf = len(seg.keyframes)
    assert 5 <= n_kf <= 36, n_kf                       # 36 = 10 % of frames; at 2 fps it was 22 of 24
    assert sum(r.is_keyframe for r in results) == n_kf - 1   # keyframe 0 is the init reference frame
    assert states.count(TrackState.LOST) == 0
    assert states.count(TrackState.TRACKING) >= 0.9 * 360
    gt = centers_of(poses)
    kf_idx = [kf.frame_index for kf in seg.keyframes]
    res = align_and_evaluate(np.array([kf.center for kf in seg.keyframes]), gt[kf_idx])
    assert res.rmse < 0.02 * res.reference_extent, (res.rmse, res.reference_extent)


# ------------------------------------------------------- real KLT smoke test
def test_real_klt_tracker_on_rendered_dots():
    """Same box + path, but frames are rendered white dots and the production
    Shi-Tomasi + LK tracker is used (no oracle). Looser tolerance: KLT on
    dots is less accurate than identity tracking."""
    poses = translating_path(30, step=0.05)
    tracker, results = run_sequence(poses, oracle=False)
    states = [r.state for r in results]
    assert TrackState.TRACKING in states, states
    assert sum(s == TrackState.TRACKING for s in states) >= 20, states
    seg = tracker.exported_segment()
    gt = centers_of(poses)
    kf_idx = [kf.frame_index for kf in seg.keyframes]
    res = align_and_evaluate(np.array([kf.center for kf in seg.keyframes]), gt[kf_idx])
    assert res.rmse < 0.10 * res.reference_extent, (res.rmse, res.reference_extent)


# ------------------------------------------------- segment helpers / map cap
def test_segment_cameras_and_points_match_export_files(tmp_path):
    from visionforge.live.tracker import segment_cameras, segment_points
    tracker, _ = run_sequence(translating_path())
    seg = tracker.exported_segment()
    tracker.export(tmp_path)
    cams_file = json.loads((tmp_path / "p1" / "reconstruction" / "cameras.json").read_text())
    assert segment_cameras(seg, INTR) == cams_file
    xyz, colors = segment_points(seg)
    lines = (tmp_path / "p1" / "reconstruction" / "sparse_cloud.ply").read_text().splitlines()
    body = lines[lines.index("end_header") + 1:]
    assert len(body) == len(xyz) == len(seg.map_points)
    file_xyz = np.array([[float(v) for v in l.split()[:3]] for l in body])
    file_rgb = np.array([[int(v) for v in l.split()[3:6]] for l in body])
    assert np.allclose(file_xyz, xyz) and np.array_equal(file_rgb, colors)
    assert colors.dtype == np.uint8 and (colors[:, 0] == colors[:, 1]).all()


def test_max_map_points_caps_the_map_without_dropping_tracked_points():
    cfg = TrackerConfig(max_map_points=150)
    tracker, results = run_sequence(translating_path(), config=cfg)
    seg = tracker.exported_segment()
    # the cap is enforced when a keyframe is created and can only be exceeded by points still
    # being tracked (never dropped): at every keyframe map_size <= max(cap, live tracks)
    assert all(r.map_size <= max(150, r.n_tracked) for r in results if r.is_keyframe)
    assert len(seg.map_points) <= max(150, len(tracker._tracks))
    # the cap bites: the map sits exactly at the cap for a stretch, where uncapped it kept growing
    assert sum(r.map_size == 150 for r in results) >= 3
    assert max(r.map_size for r in results) < 276
    # the points still tracked by live features are all present in the map
    tracked_ids = {tr.map_id for tr in tracker._tracks if tr.map_id is not None}
    assert tracked_ids <= set(seg.map_points)
    # and the uncapped run really would have exceeded the cap
    uncapped, _ = run_sequence(translating_path())
    assert len(uncapped.exported_segment().map_points) > 150
