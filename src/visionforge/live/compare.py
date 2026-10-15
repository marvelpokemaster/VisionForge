"""Compare two camera trajectories stored in the P1 cameras.json format
(``rotation_quat`` [x,y,z,w] + ``translation`` of cam_from_world), e.g. the
live tracker's keyframes against the offline COLMAP reconstruction of the
same video. Cameras are matched by VIDEO FRAME INDEX parsed from their
names, aligned with a sim(3) (Umeyama, with scale: both trajectories are
monocular and in arbitrary frames), and the residual RMSE is reported.

Naming conventions handled:
- live export: ``frame_{video_frame_index:06d}`` (0-based video frame).
- P0/COLMAP: ``frame_{k:06d}.jpg`` with k 1-based over the frames P0
  *sampled*; video frame = (k - 1) * ref_step, where ref_step is P0's
  frame_step (readable from p0/metadata.json: round(original_fps / sampling_fps)).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

from visionforge.live.alignment import align_and_evaluate
from visionforge.spatial.scene_graph import _camera_world_position

_INT_RE = re.compile(r"(\d+)")


def frame_number(name: str) -> Optional[int]:
    """Last integer in a camera name, e.g. 'frame_000012.jpg' -> 12."""
    found = _INT_RE.findall(str(name))
    return int(found[-1]) if found else None


def camera_centres(cameras: List[dict]) -> Dict[int, np.ndarray]:
    """{frame number parsed from name: world centre}."""
    out = {}
    for cam in cameras:
        n = frame_number(cam.get("name", ""))
        if n is None:
            continue
        out[n] = _camera_world_position(cam["rotation_quat"], cam["translation"])
    return out


def load_cameras(path: Union[str, Path]) -> List[dict]:
    """Accepts a cameras.json or a run directory containing p1/reconstruction/cameras.json."""
    p = Path(path)
    if p.is_dir():
        p = p / "p1" / "reconstruction" / "cameras.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def ref_step_from_run_dir(path: Union[str, Path]) -> Optional[int]:
    """P0's sampling step, from p0/metadata.json of a `reconstruct` run; None if unavailable."""
    p = Path(path)
    meta = p / "p0" / "metadata.json" if p.is_dir() else None
    if meta is None or not meta.exists():
        return None
    with open(meta, "r", encoding="utf-8") as f:
        m = json.load(f)
    if m.get("sampling_fps") and m.get("original_fps"):
        return max(1, int(round(m["original_fps"] / m["sampling_fps"])))
    return None


def compare_trajectories(live_cams: List[dict], ref_cams: List[dict], ref_step: int = 1,
                         live_step: int = 1, live_offset: int = 0, ref_offset: int = 1) -> dict:
    """Match live and reference cameras by video frame index and report the
    sim(3)-aligned RMSE of the live centres against the reference centres.
    video_frame(live) = (n - live_offset) * live_step; video_frame(ref) = (k - ref_offset) * ref_step."""
    live = {(n - live_offset) * live_step: c for n, c in camera_centres(live_cams).items()}
    ref = {(k - ref_offset) * ref_step: c for k, c in camera_centres(ref_cams).items()}
    common = sorted(set(live) & set(ref))
    result = {
        "n_live": len(live),
        "n_ref": len(ref),
        "n_matched": len(common),
        "matched_video_frames": common,
        "ref_step": ref_step,
    }
    if len(common) < 3:
        result.update({"rmse": None, "scale": None, "rmse_fraction_of_extent": None,
                       "note": "fewer than 3 matched cameras; alignment undefined"})
        return result
    A = np.array([live[i] for i in common])
    B = np.array([ref[i] for i in common])
    res = align_and_evaluate(A, B, with_scale=True)
    result.update({
        "rmse": res.rmse,
        "rmse_fraction_of_extent": res.rmse_fraction_of_extent,
        "reference_extent": res.reference_extent,
        "scale": res.sim3.scale,
        "max_residual": float(res.residuals.max()),
        "median_residual": float(np.median(res.residuals)),
        "per_camera_residual": {int(i): float(r) for i, r in zip(common, res.residuals)},
        "units": "reference trajectory units (the live trajectory is sim(3)-mapped into the reference frame)",
    })
    return result
