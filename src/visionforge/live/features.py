"""Feature detection + frame-to-frame tracking behind a small interface.

``LiveTracker`` never calls OpenCV's detector/optical flow directly; it talks
to a ``FeatureTracker``. The production implementation (``KLTFeatureTracker``)
is Shi-Tomasi corners distributed over a grid + pyramidal Lucas-Kanade with a
forward-backward consistency check. Tests inject an oracle that projects known
3D points with known poses instead, so the tracker's geometry and state
machine are verified against ground truth independently of KLT's behaviour on
synthetic imagery (see tests/test_live_tracker.py for the rationale).

Feature ids: ``detect`` returns an id per new feature and ``track`` is handed
those ids back. KLT ignores them (they only need to be unique); the oracle uses
them to identify which 3D point each feature is.
"""
from __future__ import annotations

from typing import Protocol, Tuple

import cv2
import numpy as np


class FeatureTracker(Protocol):
    def detect(self, gray: np.ndarray, frame_index: int, existing_pts: np.ndarray,
               existing_ids: np.ndarray, max_new: int) -> Tuple[np.ndarray, np.ndarray]:
        """Return (pts (N,2) float32, ids (N,) int64) of NEW features, avoiding
        the given existing ones. May return empty arrays."""
        ...

    def track(self, prev_gray: np.ndarray, gray: np.ndarray, prev_pts: np.ndarray,
              prev_ids: np.ndarray, frame_index: int) -> Tuple[np.ndarray, np.ndarray]:
        """Return (pts (N,2) float32, ok (N,) bool): the position of each input
        feature in the new frame and whether tracking it succeeded."""
        ...


class KLTFeatureTracker:
    """Shi-Tomasi corners on a grid + pyramidal LK with forward-backward check."""

    def __init__(self, grid_rows: int = 6, grid_cols: int = 8, max_features: int = 600,
                 min_distance: int = 10, quality_level: float = 0.01,
                 win_size: int = 21, max_level: int = 3, fb_threshold_px: float = 1.0):
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols
        self.max_features = max_features
        self.min_distance = min_distance
        self.quality_level = quality_level
        self.fb_threshold_px = fb_threshold_px
        self.lk_params = dict(winSize=(win_size, win_size), maxLevel=max_level,
                              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        self._next_id = 0

    def _cell_of(self, pts: np.ndarray, w: int, h: int) -> np.ndarray:
        cols = np.clip((pts[:, 0] * self.grid_cols / w).astype(int), 0, self.grid_cols - 1)
        rows = np.clip((pts[:, 1] * self.grid_rows / h).astype(int), 0, self.grid_rows - 1)
        return rows * self.grid_cols + cols

    def detect(self, gray, frame_index, existing_pts, existing_ids, max_new):
        h, w = gray.shape[:2]
        n_cells = self.grid_rows * self.grid_cols
        quota = int(np.ceil(self.max_features / n_cells))

        mask = np.full((h, w), 255, dtype=np.uint8)
        occupancy = np.zeros(n_cells, dtype=int)
        existing_pts = np.asarray(existing_pts, dtype=np.float32).reshape(-1, 2)
        if len(existing_pts):
            for x, y in existing_pts:
                cv2.circle(mask, (int(round(x)), int(round(y))), self.min_distance, 0, -1)
            np.add.at(occupancy, self._cell_of(existing_pts, w, h), 1)

        corners = cv2.goodFeaturesToTrack(gray, maxCorners=max(1, max_new * 3),
                                          qualityLevel=self.quality_level,
                                          minDistance=self.min_distance, mask=mask, blockSize=3)
        if corners is None:
            return np.zeros((0, 2), np.float32), np.zeros((0,), np.int64)
        corners = corners.reshape(-1, 2).astype(np.float32)

        # goodFeaturesToTrack returns corners strongest-first: fill each grid cell
        # up to its quota in that order so coverage stays spread over the image.
        cells = self._cell_of(corners, w, h)
        chosen = []
        for i, c in enumerate(cells):
            if occupancy[c] < quota:
                occupancy[c] += 1
                chosen.append(i)
                if len(chosen) >= max_new:
                    break
        pts = corners[chosen] if chosen else np.zeros((0, 2), np.float32)
        ids = np.arange(self._next_id, self._next_id + len(pts), dtype=np.int64)
        self._next_id += len(pts)
        return pts, ids

    def track(self, prev_gray, gray, prev_pts, prev_ids, frame_index):
        prev_pts = np.asarray(prev_pts, dtype=np.float32).reshape(-1, 1, 2)
        if len(prev_pts) == 0:
            return np.zeros((0, 2), np.float32), np.zeros((0,), bool)
        nxt, st_f, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_pts, None, **self.lk_params)
        back, st_b, _ = cv2.calcOpticalFlowPyrLK(gray, prev_gray, nxt, None, **self.lk_params)
        fb_err = np.linalg.norm(back.reshape(-1, 2) - prev_pts.reshape(-1, 2), axis=1)
        nxt = nxt.reshape(-1, 2)
        h, w = gray.shape[:2]
        inside = (nxt[:, 0] >= 0) & (nxt[:, 0] < w - 1) & (nxt[:, 1] >= 0) & (nxt[:, 1] < h - 1)
        ok = (st_f.ravel() == 1) & (st_b.ravel() == 1) & (fb_err < self.fb_threshold_px) & inside
        return nxt.astype(np.float32), ok
