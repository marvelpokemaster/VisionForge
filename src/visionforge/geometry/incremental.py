"""Room geometry on a GROWING point cloud (for the live session of step 2).

``IncrementalRoomModel.update(points, cameras, now)`` re-fits the room model
with ``build_room_model`` only when the cloud has grown by at least
``min_new_points`` AND at least ``min_interval_s`` have passed since the last
fit; otherwise it returns None and keeps ``.latest``. Below ``min_points`` it
produces an explicit empty result (zero planes, null measurements, a
``reason``) rather than a guess. The first call always fits.

An optional voxel pre-downsample (``prefilter_voxel_size``) bounds the cost on
large clouds; it lives here, not in ``build_room_model``, so the one-shot API
stays numerically identical to the file-based pipeline.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import open3d as o3d

from visionforge.geometry.api import GeometryOptions, RoomModelResult, build_room_model, empty_room_model_result


class IncrementalRoomModel:
    def __init__(self, options: Optional[GeometryOptions] = None, min_points: int = 200,
                 min_new_points: int = 100, min_interval_s: float = 2.0, seed: Optional[int] = None,
                 prefilter_voxel_size: Optional[float] = None):
        self.options = options or GeometryOptions()
        self.min_points = int(min_points)
        self.min_new_points = int(min_new_points)
        self.min_interval_s = float(min_interval_s)
        self.seed = seed
        self.prefilter_voxel_size = prefilter_voxel_size
        self.latest: Optional[RoomModelResult] = None
        self.n_fits = 0
        self.n_skipped = 0
        self._points_at_last_fit = 0
        self._time_of_last_fit: Optional[float] = None

    def should_refit(self, n_points: int, now: float) -> bool:
        if self.latest is None:
            return True
        grew = (n_points - self._points_at_last_fit) >= self.min_new_points
        waited = (now - self._time_of_last_fit) >= self.min_interval_s
        return grew and waited

    def update(self, points: np.ndarray, cameras: Optional[list] = None,
               now: Optional[float] = None) -> Optional[RoomModelResult]:
        now = time.monotonic() if now is None else float(now)
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        n = len(pts)
        if not self.should_refit(n, now):
            self.n_skipped += 1
            return None

        if n < self.min_points:
            result = empty_room_model_result(n, reason=f"{n} points < min_points={self.min_points}")
        else:
            fit_pts = pts
            if self.prefilter_voxel_size:
                pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
                fit_pts = np.asarray(pcd.voxel_down_sample(self.prefilter_voxel_size).points)
            t0 = time.perf_counter()
            try:
                result = build_room_model(fit_pts, cameras, self.options, self.seed)
            except ValueError as exc:  # empty / zero-extent cloud: report, don't guess
                result = empty_room_model_result(n, reason=str(exc))
            result.statistics["incremental"] = {
                "input_points": n,
                "fit_points": int(len(fit_pts)),
                "prefilter_voxel_size": self.prefilter_voxel_size,
                "fit_seconds": time.perf_counter() - t0,
                "fit_index": self.n_fits,
            }

        self.latest = result
        self.n_fits += 1
        self._points_at_last_fit = n
        self._time_of_last_fit = now
        return result
