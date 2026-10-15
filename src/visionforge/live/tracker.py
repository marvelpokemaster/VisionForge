"""Live classical tracker: keyframe-based monocular visual odometry.

Core only — no GUI, no VideoCapture (see ``live/runner.py`` for those).

Design (see docs/live_tracking.md for the full discussion):

* INITIALIZING: a reference frame is chosen and features are tracked from
  it. Initialisation is attempted only when the tracked features show real
  parallax — median pixel displacement above a threshold AND, after the best
  rotation-only/homography model is removed, the median residual is still
  above a threshold (pure rotation and static input never pass). The two
  frames are then related by an essential matrix (RANSAC), the pose is
  recovered, points are triangulated, cheirality-checked and
  reprojection-filtered, and a minimum triangulation angle is enforced.
  Success creates a *segment*: keyframe 0 (identity) and keyframe 1
  (recovered pose, unit baseline) plus the initial map.
* TRACKING: every frame's pose is solved with ``cv2.solvePnPRansac`` against
  the map points still tracked by the feature tracker. Scale is therefore
  anchored to the initial map rather than guessed per frame. A new keyframe
  is created when the tracked-map-point count drops below a fraction of what
  the last keyframe had, or the median parallax to the last keyframe is
  sufficient; only then are NEW points triangulated (between the last
  keyframe and the new one, same checks as at init) and new features
  detected on a grid to keep coverage.
* LOST: entered when the feature tracker keeps fewer than N points or PnP
  has too few inliers. The pose is None, nothing is added to the map, and
  the tracker goes back to looking for a reference frame to re-initialise
  from. A successful re-initialisation starts a NEW segment with its own
  arbitrary frame and scale — segments are never stitched together, because
  nothing observed relates them. The last pose is never reused or
  interpolated.

What is NOT done: no bundle adjustment, no loop closure, no relocalisation
against the old map, no scale recovery (monocular). Drift accumulates.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from visionforge.live.features import FeatureTracker, KLTFeatureTracker
from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.reconstruction.two_view import save_ply


class TrackState(str, Enum):
    INITIALIZING = "INITIALIZING"
    TRACKING = "TRACKING"
    LOST = "LOST"


@dataclass
class TrackerConfig:
    # feature budget
    max_features: int = 600
    # --- initialisation gates ---
    init_min_matches: int = 60            # fewer tracked features than this -> pick a new reference
    init_max_ref_age: int = 90            # frames; a stale reference is replaced
    init_min_parallax_px: float = 10.0    # median raw pixel displacement reference -> current
    # rotation-compensated parallax: a feature "has parallax" if its residual
    # after the best RANSAC homography exceeds this many px; initialisation
    # needs at least init_min_parallax_fraction of tracked features (and at
    # least init_min_points of them) to have parallax. A fraction, not the
    # median, because one dominant plane (a far wall) can hold most features.
    init_min_parallax_residual_px: float = 3.0
    init_min_parallax_fraction: float = 0.1
    init_min_inliers: int = 40            # essential-matrix RANSAC inliers
    init_min_points: int = 30             # triangulated points surviving all checks
    init_min_accept_ratio: float = 0.5    # surviving / E inliers
    essential_ransac_px: float = 1.0
    # --- triangulation checks (init and keyframes) ---
    triangulation_reproj_px: float = 2.0
    min_triangulation_angle_deg: float = 1.0
    # --- tracking ---
    min_tracked_points: int = 20          # feature tracker keeps fewer -> LOST
    pnp_reproj_px: float = 3.0
    pnp_min_inliers: int = 15             # PnP inliers below this -> LOST
    pnp_max_outlier_strikes: int = 2      # a map track that is a PnP outlier this many frames in a row is dropped
    # --- keyframe policy ---
    keyframe_min_gap: int = 1             # frames since the last keyframe
    keyframe_tracked_fraction: float = 0.6
    keyframe_min_parallax_px: float = 20.0


@dataclass
class FrameResult:
    frame_index: int
    state: TrackState
    pose: Optional[Tuple[np.ndarray, np.ndarray]]  # (R (3,3), t (3,)) cam_from_world, or None
    n_tracked: int
    n_inliers: int
    reprojection_rms: Optional[float]
    is_keyframe: bool
    map_size: int = 0


@dataclass
class Keyframe:
    frame_index: int
    R: np.ndarray
    t: np.ndarray
    n_map_tracked: int  # map points tracked when this keyframe was created

    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.t


@dataclass
class MapPoint:
    id: int
    xyz: np.ndarray
    feature_id: int   # id of the feature track that created it
    kf_a: int         # segment-local keyframe ordinals it was triangulated from
    kf_b: int
    color: int        # gray intensity at first observation (0..255)
    angle_deg: float = 0.0  # triangulation angle of the (kf_a, kf_b) pair used


@dataclass
class Segment:
    """One continuously tracked stretch: keyframes + map in ONE arbitrary frame."""
    index: int
    keyframes: List[Keyframe] = field(default_factory=list)
    map_points: Dict[int, MapPoint] = field(default_factory=dict)
    start_frame: int = 0
    end_frame: int = 0


@dataclass
class _Track:
    id: int
    pt: np.ndarray          # current raw pixel position
    first_kf_pt: np.ndarray # raw position at the FIRST keyframe that observed it (widest baseline for triangulation)
    first_kf_index: int     # segment-local ordinal of that keyframe (0 = init reference)
    kf_pt: np.ndarray       # raw position at the LAST keyframe (parallax statistic for the keyframe decision)
    kf_index: int
    map_id: Optional[int] = None
    strikes: int = 0


# ----------------------------------------------------------------------------
# geometry helpers
# ----------------------------------------------------------------------------

def rotation_matrix_to_quat_xyzw(R: np.ndarray) -> List[float]:
    """Rotation matrix -> unit quaternion [x, y, z, w], same convention as
    pycolmap's ``Rotation3d.quat`` and ``spatial/scene_graph.py``'s reader."""
    R = np.asarray(R, dtype=np.float64)
    tr = np.trace(R)
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], dtype=np.float64)
    q /= np.linalg.norm(q)
    return q.tolist()


def _project(K: np.ndarray, R: np.ndarray, t: np.ndarray, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (uv (N,2), depth (N,)) of world points X under cam_from_world (R, t)."""
    Xc = (R @ X.T).T + t
    depth = Xc[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = (K @ Xc.T).T
        uv = uv[:, :2] / uv[:, 2:3]
    return uv, depth


def triangulate_checked(K: np.ndarray, R1: np.ndarray, t1: np.ndarray, R2: np.ndarray, t2: np.ndarray,
                        uv1: np.ndarray, uv2: np.ndarray, reproj_px: float, min_angle_deg: float
                        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Linear triangulation of pixel correspondences (already undistorted)
    between two cam_from_world poses, then: positive depth in BOTH views,
    reprojection error <= reproj_px in both, triangulation angle >= min.
    Returns (X (N,3), accept (N,) bool, rms_err (N,), angle_deg (N,)) per point."""
    uv1 = np.asarray(uv1, dtype=np.float64).reshape(-1, 2)
    uv2 = np.asarray(uv2, dtype=np.float64).reshape(-1, 2)
    n = len(uv1)
    if n == 0:
        return np.zeros((0, 3)), np.zeros((0,), bool), np.zeros((0,)), np.zeros((0,))
    P1 = K @ np.hstack([R1, t1.reshape(3, 1)])
    P2 = K @ np.hstack([R2, t2.reshape(3, 1)])
    X4 = cv2.triangulatePoints(P1, P2, uv1.T, uv2.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        X = (X4[:3] / X4[3]).T
    finite = np.isfinite(X).all(axis=1)
    X = np.where(finite[:, None], X, 0.0)

    p1, d1 = _project(K, R1, t1, X)
    p2, d2 = _project(K, R2, t2, X)
    e1 = np.linalg.norm(p1 - uv1, axis=1)
    e2 = np.linalg.norm(p2 - uv2, axis=1)
    err = np.sqrt((e1 ** 2 + e2 ** 2) / 2.0)

    C1 = -R1.T @ t1
    C2 = -R2.T @ t2
    r1 = X - C1
    r2 = X - C2
    cosang = (r1 * r2).sum(axis=1) / (np.linalg.norm(r1, axis=1) * np.linalg.norm(r2, axis=1) + 1e-12)
    angle = np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))

    accept = finite & (d1 > 0) & (d2 > 0) & (e1 <= reproj_px) & (e2 <= reproj_px) & (angle >= min_angle_deg)
    return X, accept, err, angle


# ----------------------------------------------------------------------------
# the tracker
# ----------------------------------------------------------------------------

class LiveTracker:
    def __init__(self, intrinsics: CameraIntrinsics, config: Optional[TrackerConfig] = None,
                 feature_tracker: Optional[FeatureTracker] = None):
        self.intrinsics = intrinsics
        self.config = config or TrackerConfig()
        self.features: FeatureTracker = feature_tracker or KLTFeatureTracker(max_features=self.config.max_features)
        self.K = intrinsics.K

        self.state = TrackState.INITIALIZING
        self.segments: List[Segment] = []
        self._seg: Optional[Segment] = None
        self._tracks: List[_Track] = []
        self._prev_gray: Optional[np.ndarray] = None
        self._ref_frame_index: Optional[int] = None
        self._next_map_id = 0
        self.results: List[FrameResult] = []

    # ------------------------------------------------------------------ public
    @property
    def active_segment(self) -> Optional[Segment]:
        return self._seg

    @property
    def map_size(self) -> int:
        return len(self._seg.map_points) if self._seg is not None else 0

    def tracked_points(self) -> Tuple[np.ndarray, np.ndarray]:
        """Current feature positions (N,2) and a bool mask of which ones are
        associated with a map point. For display only."""
        if not self._tracks:
            return np.zeros((0, 2), np.float32), np.zeros((0,), bool)
        pts = np.array([tr.pt for tr in self._tracks], dtype=np.float32)
        mapped = np.array([tr.map_id is not None for tr in self._tracks], dtype=bool)
        return pts, mapped

    def process_frame(self, frame: np.ndarray, frame_index: int) -> FrameResult:
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. propagate existing tracks into this frame
        if self._prev_gray is not None and self._tracks:
            prev_pts = np.array([tr.pt for tr in self._tracks], dtype=np.float32)
            prev_ids = np.array([tr.id for tr in self._tracks], dtype=np.int64)
            pts, ok = self.features.track(self._prev_gray, gray, prev_pts, prev_ids, frame_index)
            survivors = []
            for tr, p, good in zip(self._tracks, pts, ok):
                if good:
                    tr.pt = np.asarray(p, dtype=np.float32)
                    survivors.append(tr)
            self._tracks = survivors
        n_tracked = len(self._tracks)

        # 2. state machine
        if self.state == TrackState.TRACKING:
            result = self._track_frame(gray, frame_index, n_tracked)
        else:
            result = self._initialisation_step(gray, frame_index, n_tracked)

        self._prev_gray = gray
        result.map_size = self.map_size
        if self._seg is not None:
            self._seg.end_frame = frame_index
        self.results.append(result)
        return result

    # ------------------------------------------------------------ init / lost
    def _set_reference(self, gray: np.ndarray, frame_index: int) -> None:
        """Start looking for an initialisation pair from this frame."""
        self._tracks = []
        pts, ids = self.features.detect(gray, frame_index, np.zeros((0, 2), np.float32),
                                        np.zeros((0,), np.int64), self.config.max_features)
        self._tracks = [_Track(int(i), np.asarray(p, np.float32), np.asarray(p, np.float32), 0,
                               np.asarray(p, np.float32), 0) for p, i in zip(pts, ids)]
        self._ref_frame_index = frame_index

    def _enter_lost(self, gray: np.ndarray, frame_index: int) -> None:
        self.state = TrackState.LOST
        self._seg = None
        self._set_reference(gray, frame_index)

    def _initialisation_step(self, gray: np.ndarray, frame_index: int, n_tracked: int) -> FrameResult:
        cfg = self.config
        stale = (self._ref_frame_index is None
                 or n_tracked < cfg.init_min_matches
                 or frame_index - self._ref_frame_index > cfg.init_max_ref_age)
        if stale:
            self._set_reference(gray, frame_index)
            return FrameResult(frame_index, self.state, None, len(self._tracks), 0, None, False)

        init = self._try_initialise(gray, frame_index)
        if init is None:
            return FrameResult(frame_index, self.state, None, n_tracked, 0, None, False)
        R, t, n_good, rms = init
        self.state = TrackState.TRACKING
        return FrameResult(frame_index, TrackState.TRACKING, (R, t), len(self._tracks), n_good, rms, True)

    def _try_initialise(self, gray: np.ndarray, frame_index: int):
        cfg = self.config
        ref_raw = np.array([tr.kf_pt for tr in self._tracks], dtype=np.float64)
        cur_raw = np.array([tr.pt for tr in self._tracks], dtype=np.float64)

        # gate 1: raw parallax (static input never passes)
        disp = np.linalg.norm(cur_raw - ref_raw, axis=1)
        if float(np.median(disp)) < cfg.init_min_parallax_px:
            return None

        ref_u = self.intrinsics.undistort_points(ref_raw)
        cur_u = self.intrinsics.undistort_points(cur_raw)

        # gate 2: rotation-compensated parallax. A homography explains any
        # camera rotation (and a single plane); what it cannot explain is the
        # depth-dependent motion a translation induces. Pure rotation -> every
        # feature fits the homography -> no initialisation.
        H, _ = cv2.findHomography(ref_u.astype(np.float32), cur_u.astype(np.float32), cv2.RANSAC,
                                  cfg.init_min_parallax_residual_px)
        if H is not None:
            warped = cv2.perspectiveTransform(ref_u.reshape(-1, 1, 2).astype(np.float32), H.astype(np.float32)).reshape(-1, 2)
            residual = np.linalg.norm(cur_u - warped, axis=1)
            n_parallax = int((residual > cfg.init_min_parallax_residual_px).sum())
            if n_parallax < cfg.init_min_points or n_parallax < cfg.init_min_parallax_fraction * len(residual):
                return None

        # gate 3: essential matrix with enough inliers. USAC_ACCURATE (RANSAC +
        # local optimisation + final least-squares refit on the inlier set)
        # rather than plain RANSAC, which returns the best 5-point minimal
        # sample unrefined: on a scene dominated by one plane that is 5-10x
        # less accurate (measured in tests/test_live_tracker.py's fixture:
        # 0.25 deg / 3.3 deg rotation / translation-direction error vs
        # 0.05 deg / 0.2 deg at 0.5 px noise).
        E, mask = cv2.findEssentialMat(ref_u, cur_u, self.K, method=cv2.USAC_ACCURATE, prob=0.999,
                                       threshold=cfg.essential_ransac_px)
        if E is None or E.shape != (3, 3):
            return None
        inl = mask.ravel().astype(bool)
        if inl.sum() < cfg.init_min_inliers:
            return None
        _, R, t, pose_mask = cv2.recoverPose(E, ref_u, cur_u, self.K, mask=mask.copy())
        t = t.reshape(3)
        pose_inl = pose_mask.ravel().astype(bool) & inl

        # gate 4: triangulate and keep only points that pass all checks
        R0, t0 = np.eye(3), np.zeros(3)
        idx = np.flatnonzero(pose_inl)
        X, accept, err, angle = triangulate_checked(self.K, R0, t0, R, t, ref_u[idx], cur_u[idx],
                                                    cfg.triangulation_reproj_px, cfg.min_triangulation_angle_deg)
        n_good = int(accept.sum())
        if n_good < cfg.init_min_points or n_good < cfg.init_min_accept_ratio * inl.sum():
            return None

        # success: open a new segment
        seg = Segment(index=len(self.segments), start_frame=int(self._ref_frame_index), end_frame=frame_index)
        seg.keyframes.append(Keyframe(int(self._ref_frame_index), R0, t0, 0))
        seg.keyframes.append(Keyframe(frame_index, R, t, n_good))
        self.segments.append(seg)
        self._seg = seg
        for j, k in enumerate(idx):
            if accept[j]:
                tr = self._tracks[k]
                self._add_map_point(seg, X[j], tr, gray, 0, 1, float(angle[j]))
        seg.keyframes[0].n_map_tracked = n_good
        self._finish_keyframe(gray, frame_index, kf_ordinal=1)
        rms = float(np.sqrt(np.mean(err[accept] ** 2)))
        return R, t, n_good, rms

    # --------------------------------------------------------------- tracking
    def _track_frame(self, gray: np.ndarray, frame_index: int, n_tracked: int) -> FrameResult:
        cfg = self.config
        seg = self._seg
        assert seg is not None
        if n_tracked < cfg.min_tracked_points:
            self._enter_lost(gray, frame_index)
            return FrameResult(frame_index, TrackState.LOST, None, n_tracked, 0, None, False)

        mapped = [tr for tr in self._tracks if tr.map_id is not None]
        if len(mapped) < cfg.pnp_min_inliers:
            self._enter_lost(gray, frame_index)
            return FrameResult(frame_index, TrackState.LOST, None, n_tracked, 0, None, False)

        obj = np.array([seg.map_points[tr.map_id].xyz for tr in mapped], dtype=np.float64)
        img = self.intrinsics.undistort_points(np.array([tr.pt for tr in mapped], dtype=np.float64))
        ok, rvec, tvec, inliers = cv2.solvePnPRansac(obj, img, self.K, None, iterationsCount=200,
                                                     reprojectionError=cfg.pnp_reproj_px, confidence=0.999)
        if not ok or inliers is None or len(inliers) < cfg.pnp_min_inliers:
            self._enter_lost(gray, frame_index)
            return FrameResult(frame_index, TrackState.LOST, None, n_tracked, 0, None, False)
        inl = inliers.ravel()
        rvec, tvec = cv2.solvePnPRefineLM(obj[inl], img[inl], self.K, None, rvec, tvec)
        R, _ = cv2.Rodrigues(rvec)
        t = tvec.reshape(3)
        proj, _ = _project(self.K, R, t, obj[inl])
        rms = float(np.sqrt(np.mean(np.sum((proj - img[inl]) ** 2, axis=1))))
        n_inliers = int(len(inl))

        # outlier bookkeeping: drop map tracks that keep failing PnP
        inlier_set = set(inl.tolist())
        for j, tr in enumerate(mapped):
            if j in inlier_set:
                tr.strikes = 0
            else:
                tr.strikes += 1
        self._tracks = [tr for tr in self._tracks if tr.strikes < cfg.pnp_max_outlier_strikes]

        # keyframe decision
        last_kf = seg.keyframes[-1]
        last_ord = len(seg.keyframes) - 1
        tracked_fraction = n_inliers / max(1, last_kf.n_map_tracked)
        kf_disp = [float(np.linalg.norm(tr.pt - tr.kf_pt)) for tr in self._tracks if tr.kf_index == last_ord]
        parallax_kf = float(np.median(kf_disp)) if kf_disp else 0.0
        make_kf = (frame_index - last_kf.frame_index >= cfg.keyframe_min_gap and
                   (tracked_fraction < cfg.keyframe_tracked_fraction or parallax_kf >= cfg.keyframe_min_parallax_px))
        if make_kf:
            self._create_keyframe(gray, frame_index, R, t, n_inliers)
        return FrameResult(frame_index, TrackState.TRACKING, (R, t), n_tracked, n_inliers, rms, make_kf)

    def _create_keyframe(self, gray: np.ndarray, frame_index: int, R: np.ndarray, t: np.ndarray, n_inliers: int) -> None:
        cfg = self.config
        seg = self._seg
        new_ord = len(seg.keyframes)
        seg.keyframes.append(Keyframe(frame_index, R.copy(), t.copy(), n_inliers))

        # (Re)triangulate every track already observed at an earlier keyframe,
        # from its FIRST keyframe observation to this one (the widest baseline
        # available): unmapped tracks that pass the checks become NEW map
        # points; mapped tracks only get their xyz REPLACED when this pair has
        # a larger triangulation angle than the one that created them
        # (better-conditioned depth). Map size therefore changes only here.
        by_first: Dict[int, List[_Track]] = {}
        for tr in self._tracks:
            if tr.first_kf_index < new_ord:
                by_first.setdefault(tr.first_kf_index, []).append(tr)
        for first_ord, cand in by_first.items():
            kf_first = seg.keyframes[first_ord]
            uv1 = self.intrinsics.undistort_points(np.array([tr.first_kf_pt for tr in cand], dtype=np.float64))
            uv2 = self.intrinsics.undistort_points(np.array([tr.pt for tr in cand], dtype=np.float64))
            X, accept, _, angle = triangulate_checked(self.K, kf_first.R, kf_first.t, R, t, uv1, uv2,
                                                      cfg.triangulation_reproj_px, cfg.min_triangulation_angle_deg)
            for tr, x, a, ang in zip(cand, X, accept, angle):
                if not a:
                    continue
                if tr.map_id is None:
                    self._add_map_point(seg, x, tr, gray, first_ord, new_ord, float(ang))
                else:
                    mp = seg.map_points[tr.map_id]
                    if ang > mp.angle_deg:
                        mp.xyz = np.asarray(x, dtype=np.float64)
                        mp.kf_a, mp.kf_b, mp.angle_deg = first_ord, new_ord, float(ang)
        seg.keyframes[-1].n_map_tracked = sum(1 for tr in self._tracks if tr.map_id is not None)
        self._finish_keyframe(gray, frame_index, kf_ordinal=new_ord)

    def _finish_keyframe(self, gray: np.ndarray, frame_index: int, kf_ordinal: int) -> None:
        """Re-detect features to keep coverage and re-anchor every track's
        keyframe observation at this keyframe."""
        existing_pts = np.array([tr.pt for tr in self._tracks], dtype=np.float32).reshape(-1, 2)
        existing_ids = np.array([tr.id for tr in self._tracks], dtype=np.int64)
        n_new = self.config.max_features - len(self._tracks)
        if n_new > 0:
            pts, ids = self.features.detect(gray, frame_index, existing_pts, existing_ids, n_new)
            for p, i in zip(pts, ids):
                self._tracks.append(_Track(int(i), np.asarray(p, np.float32), np.asarray(p, np.float32), kf_ordinal,
                                           np.asarray(p, np.float32), kf_ordinal))
        for tr in self._tracks:
            tr.kf_pt = tr.pt.copy()
            tr.kf_index = kf_ordinal

    def _add_map_point(self, seg: Segment, xyz: np.ndarray, tr: _Track, gray: np.ndarray,
                       kf_a: int, kf_b: int, angle_deg: float) -> None:
        h, w = gray.shape[:2]
        x, y = int(round(float(tr.pt[0]))), int(round(float(tr.pt[1])))
        color = int(gray[min(max(y, 0), h - 1), min(max(x, 0), w - 1)])
        mp = MapPoint(self._next_map_id, np.asarray(xyz, dtype=np.float64), tr.id, kf_a, kf_b, color, angle_deg)
        seg.map_points[mp.id] = mp
        tr.map_id = mp.id
        self._next_map_id += 1

    # ----------------------------------------------------------------- report
    def lost_episodes(self) -> List[Dict[str, int]]:
        episodes = []
        start = None
        for i, r in enumerate(self.results):
            if r.state == TrackState.LOST and start is None:
                start = r.frame_index
            elif r.state != TrackState.LOST and start is not None:
                episodes.append({"start": start, "end": self.results[i - 1].frame_index})
                start = None
        if start is not None:
            episodes.append({"start": start, "end": self.results[-1].frame_index})
        for e in episodes:
            e["n_frames"] = e["end"] - e["start"] + 1
        return episodes

    def exported_segment(self) -> Optional[Segment]:
        """The segment that gets exported: most keyframes, then most map points
        (mirrors incremental.py exporting COLMAP's largest reconstruction)."""
        if not self.segments:
            return None
        return max(self.segments, key=lambda s: (len(s.keyframes), len(s.map_points)))

    def report(self) -> dict:
        counts = {s.value: 0 for s in TrackState}
        for r in self.results:
            counts[r.state.value] += 1
        rms_values = [r.reprojection_rms for r in self.results if r.state == TrackState.TRACKING and r.reprojection_rms is not None]
        exported = self.exported_segment()
        n_frames = len(self.results)
        return {
            "frames": n_frames,
            "keyframes": [kf.frame_index for kf in exported.keyframes] if exported else [],
            "n_keyframes": len(exported.keyframes) if exported else 0,
            "state_counts": counts,
            "tracking_fraction": (counts["TRACKING"] / n_frames) if n_frames else 0.0,
            "lost_episodes": self.lost_episodes(),
            "map_size": len(exported.map_points) if exported else 0,
            "mean_reprojection_rms": float(np.mean(rms_values)) if rms_values else None,
            "intrinsics": self.intrinsics.to_dict(),
            "intrinsics_source": self.intrinsics.source,
            "segments": [{
                "index": s.index,
                "start_frame": s.start_frame,
                "end_frame": s.end_frame,
                "n_keyframes": len(s.keyframes),
                "map_size": len(s.map_points),
                "exported": exported is s,
            } for s in self.segments],
            "config": asdict(self.config),
        }

    def export(self, run_dir: Path, video: Optional[str] = None) -> dict:
        """Write p1/reconstruction/{sparse_cloud.ply, cameras.json} in the P1
        format incremental.py writes (one camera per KEYFRAME of the exported
        segment, PINHOLE model with the intrinsics used) and tracking_report.json.
        Returns the report."""
        run_dir = Path(run_dir)
        rec_dir = run_dir / "p1" / "reconstruction"
        rec_dir.mkdir(parents=True, exist_ok=True)
        seg = self.exported_segment()
        params = self.intrinsics.pinhole_params()

        cameras = []
        points = np.zeros((0, 3))
        colors = None
        if seg is not None:
            for i, kf in enumerate(seg.keyframes):
                cameras.append({
                    "id": i + 1,
                    "name": f"frame_{kf.frame_index:06d}",
                    "rotation_quat": rotation_matrix_to_quat_xyzw(kf.R),
                    "translation": [float(v) for v in kf.t],
                    "camera_model": "PINHOLE",
                    "camera_params": params,
                })
            if seg.map_points:
                mps = list(seg.map_points.values())
                points = np.array([mp.xyz for mp in mps])
                colors = np.array([[mp.color] * 3 for mp in mps])
        save_ply(str(rec_dir / "sparse_cloud.ply"), points, colors)
        with open(rec_dir / "cameras.json", "w") as f:
            json.dump(cameras, f, indent=2)

        report = self.report()
        report["video"] = video
        report["exported_segment"] = seg.index if seg is not None else None
        with open(run_dir / "tracking_report.json", "w") as f:
            json.dump(report, f, indent=2)
        return report
