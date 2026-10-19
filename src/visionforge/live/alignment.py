"""Similarity (sim(3)) alignment of two point sets — Umeyama's closed form,
written out by hand with numpy only (no scipy).

Used to compare a monocular trajectory (arbitrary scale, arbitrary world
frame) against a reference trajectory in a different arbitrary frame: the
best-fit scale, rotation and translation are solved for, and the RMSE of
what is left is the trajectory error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class Sim3:
    scale: float
    R: np.ndarray  # (3,3)
    t: np.ndarray  # (3,)

    def apply(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        return (self.scale * (self.R @ pts.T)).T + self.t


def umeyama_alignment(src: np.ndarray, dst: np.ndarray, with_scale: bool = True) -> Sim3:
    """Solve  dst_i ≈ s * R @ src_i + t  in the least-squares sense
    (Umeyama 1991). Requires >= 3 points; with collinear points the rotation
    about the line is undetermined but the residuals (and so the RMSE) are
    still well-defined."""
    src = np.asarray(src, dtype=np.float64).reshape(-1, 3)
    dst = np.asarray(dst, dtype=np.float64).reshape(-1, 3)
    if src.shape != dst.shape or len(src) < 3:
        raise ValueError(f"need >= 3 matched points, got {src.shape} vs {dst.shape}")
    n = len(src)
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    src_c = src - mu_s
    dst_c = dst - mu_d
    var_s = (src_c ** 2).sum() / n
    sigma = dst_c.T @ src_c / n  # cross-covariance (3,3)
    U, D, Vt = np.linalg.svd(sigma)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0
    R = U @ S @ Vt
    if with_scale:
        s = float(np.trace(np.diag(D) @ S) / var_s) if var_s > 0 else 1.0
    else:
        s = 1.0
    t = mu_d - s * (R @ mu_s)
    return Sim3(s, R, t)


@dataclass
class AlignmentResult:
    sim3: Sim3
    rmse: float
    residuals: np.ndarray       # per-point distance after alignment
    reference_extent: float     # bbox diagonal of dst, so RMSE can be read as a fraction

    @property
    def rmse_fraction_of_extent(self) -> Optional[float]:
        return float(self.rmse / self.reference_extent) if self.reference_extent > 0 else None


def align_and_evaluate(src: np.ndarray, dst: np.ndarray, with_scale: bool = True) -> AlignmentResult:
    sim3 = umeyama_alignment(src, dst, with_scale)
    aligned = sim3.apply(src)
    dst = np.asarray(dst, dtype=np.float64).reshape(-1, 3)
    residuals = np.linalg.norm(aligned - dst, axis=1)
    rmse = float(np.sqrt((residuals ** 2).mean()))
    extent = float(np.linalg.norm(dst.max(axis=0) - dst.min(axis=0)))
    return AlignmentResult(sim3, rmse, residuals, extent)
