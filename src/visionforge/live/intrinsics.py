"""Camera intrinsics for the live tracker.

The tracker needs fx, fy, cx, cy (and optionally a first radial term k1)
expressed in pixels of the frames it is fed. They come from one of two
places, and the export records which:

- ``"colmap"``: parsed from an existing P1 ``cameras.json`` produced by
  ``visionforge reconstruct`` (``from_colmap_params`` / ``from_cameras_json``).
- ``"guess"``: ``guess_for_frame`` — focal = max(width, height) at the image
  centre. This is a GUESS, not a calibration: it is the same heuristic
  ``reconstruction/two_view.py`` uses (``focal = max(h, w)``), chosen because
  it is roughly right for typical phone/webcam fields of view. Poses
  estimated with a guessed focal are internally consistent but can be
  systematically distorted (wrong depth-to-baseline ratio); use real
  intrinsics whenever a COLMAP run of the same camera exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Sequence, Union

import cv2
import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    k1: float = 0.0
    source: str = "guess"  # "colmap" | "guess"

    @classmethod
    def from_colmap_params(cls, model: str, params: Sequence[float], source: str = "colmap") -> "CameraIntrinsics":
        """Build from a COLMAP camera model name + its parameter list, as stored in
        cameras.json (``camera_model`` / ``camera_params``). Supported:
        SIMPLE_PINHOLE [f, cx, cy], PINHOLE [fx, fy, cx, cy],
        SIMPLE_RADIAL [f, cx, cy, k], RADIAL [f, cx, cy, k1, k2] (k2 is dropped,
        with the loss recorded nowhere else — so prefer SIMPLE_RADIAL/PINHOLE)."""
        p = [float(v) for v in params]
        model = model.upper()
        if model == "SIMPLE_PINHOLE" and len(p) == 3:
            return cls(p[0], p[0], p[1], p[2], 0.0, source)
        if model == "PINHOLE" and len(p) == 4:
            return cls(p[0], p[1], p[2], p[3], 0.0, source)
        if model == "SIMPLE_RADIAL" and len(p) == 4:
            return cls(p[0], p[0], p[1], p[2], p[3], source)
        if model == "RADIAL" and len(p) == 5:
            return cls(p[0], p[0], p[1], p[2], p[3], source)
        raise ValueError(f"Unsupported COLMAP camera model/params: {model} {params}")

    @classmethod
    def from_cameras_json(cls, path: Union[str, Path]) -> "CameraIntrinsics":
        """Read the first camera entry of a P1 cameras.json. COLMAP's
        incremental mapper shares one camera across all frames of a video, so
        every entry carries the same model/params; the first one is used."""
        with open(path, "r", encoding="utf-8") as f:
            cameras = json.load(f)
        if not cameras:
            raise ValueError(f"{path} contains no cameras")
        first = cameras[0]
        return cls.from_colmap_params(first["camera_model"], first["camera_params"], source="colmap")

    @classmethod
    def guess_for_frame(cls, width: int, height: int) -> "CameraIntrinsics":
        """Focal = max(w, h), principal point at the image centre. A guess — see
        the module docstring."""
        f = float(max(width, height))
        return cls(f, f, width / 2.0, height / 2.0, 0.0, "guess")

    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx],
                         [0.0, self.fy, self.cy],
                         [0.0, 0.0, 1.0]], dtype=np.float64)

    @property
    def dist_coeffs(self) -> np.ndarray:
        return np.array([self.k1, 0.0, 0.0, 0.0], dtype=np.float64)

    def undistort_points(self, pts: np.ndarray) -> np.ndarray:
        """Map raw pixel coordinates to pixel coordinates of the ideal pinhole
        camera with the same K. Identity when k1 == 0."""
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if len(pts) == 0 or self.k1 == 0.0:
            return pts
        out = cv2.undistortPoints(pts.reshape(-1, 1, 2), self.K, self.dist_coeffs, P=self.K)
        return out.reshape(-1, 2)

    def pinhole_params(self) -> List[float]:
        """camera_params for the exported PINHOLE camera model: [fx, fy, cx, cy]."""
        return [float(self.fx), float(self.fy), float(self.cx), float(self.cy)]

    def to_dict(self) -> dict:
        return asdict(self)
