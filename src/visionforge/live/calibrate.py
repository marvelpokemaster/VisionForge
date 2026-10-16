"""Phone intrinsics from a short clip, with the existing COLMAP pipeline.

The live tracker needs fx, fy, cx, cy (and k1) for the frames it is fed. A
phone does not tell the WebView its focal length, so without this the Live
screen sends ``CameraIntrinsics.phone_default`` (0.8 × the longer side — a
~64° horizontal field of view assumption, a STOPGAP). The real fix: film a
20–30 s clip with the SAME phone in the SAME orientation as the live run
(slow sideways walk in a textured room), run

    visionforge calibrate --video <clip.mp4> --output <phone>.json

which runs P0 (frame extraction) and P1 (COLMAP incremental SfM, the same
stages ``visionforge reconstruct`` uses) and writes a cameras.json-style
LIST: the element-wise MEDIAN of the per-frame intrinsics first (``name``
"median"), then one entry per registered frame — every entry carrying the
``width``/``height`` it was measured at so the live session can rescale it
to the frames the phone actually sends (``LiveSession.configure``,
``intrinsics_size``). COLMAP's incremental mapper shares one camera across
a video's frames, so the median is normally just that camera; the list is
kept so the spread is visible.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2

from visionforge.live.intrinsics import CameraIntrinsics


def frame_size_of(frames_dir: Path) -> Tuple[int, int]:
    """(width, height) of the first extracted frame."""
    for p in sorted(frames_dir.iterdir()):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            img = cv2.imread(str(p))
            if img is not None:
                h, w = img.shape[:2]
                return int(w), int(h)
    raise ValueError(f"no readable frame image under {frames_dir}")


def calibration_from_cameras(cameras: Sequence[Dict[str, Any]], width: int, height: int,
                             video: Optional[str] = None) -> List[Dict[str, Any]]:
    """The output list from a P1 cameras.json: median first, then every
    camera, each tagged with the frame size. All entries must share one
    COLMAP model (they do for a video); the median is element-wise over
    ``camera_params`` of that model, so it is itself a valid entry."""
    if not cameras:
        raise ValueError("P1 registered no cameras: the clip has too little parallax or texture for COLMAP "
                         "(walk sideways, slowly, in a textured room; do not just rotate)")
    models = {str(c["camera_model"]).upper() for c in cameras}
    if len(models) != 1:
        raise ValueError(f"cameras.json mixes camera models {sorted(models)}; cannot take a median")
    model = models.pop()
    n_params = {len(c["camera_params"]) for c in cameras}
    if len(n_params) != 1:
        raise ValueError("cameras.json entries have different parameter counts")
    params = [[float(v) for v in c["camera_params"]] for c in cameras]
    median = [statistics.median(col) for col in zip(*params)]
    CameraIntrinsics.from_colmap_params(model, median)  # raises on an unsupported model
    per_camera = [{"id": c.get("id"), "name": c.get("name"), "camera_model": model,
                   "camera_params": p, "width": int(width), "height": int(height)} for c, p in zip(cameras, params)]
    first = {"id": 0, "name": "median", "camera_model": model, "camera_params": median,
             "width": int(width), "height": int(height), "n_cameras": len(cameras), "source_video": video,
             "note": "element-wise median of the per-frame COLMAP intrinsics that follow; "
                     "use as intrinsics_from_cameras[0] / --intrinsics-from"}
    return [first] + per_camera


def run_calibration(video_path: Path, out_path: Path, work_dir: Path, fps: float = 2.0,
                    max_frames: Optional[int] = None,
                    run_stage: Optional[Callable[[List[str], str], None]] = None) -> List[Dict[str, Any]]:
    """P0 + P1 under ``work_dir`` (the same stage commands ``visionforge
    reconstruct`` runs), then ``calibration_from_cameras`` written to
    ``out_path``. ``run_stage(cmd, description)`` is the CLI's subprocess
    runner (injected so tests can fake COLMAP)."""
    if run_stage is None:
        from visionforge.cli import _run_stage as run_stage  # noqa: WPS433 (lazy: cli imports are heavy)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    p0_dir, p1_dir = work_dir / "p0", work_dir / "p1"
    cmd = [sys.executable, "-m", "visionforge.video.extract_frames", "--input", str(video_path),
           "--output", str(p0_dir), "--fps", str(fps)]
    if max_frames is not None:
        cmd += ["--max-frames", str(max_frames)]
    print(f"[1/3] Extracting frames from {video_path} at {fps} fps...")
    run_stage(cmd, "P0 (Video Extraction)")
    print("[2/3] Running COLMAP reconstruction (P1)...")
    run_stage([sys.executable, "-m", "visionforge.reconstruction.pipeline",
               "--frames-dir", str(p0_dir / "frames"), "--output", str(p1_dir)], "P1 (Reconstruction)")
    cameras_path = p1_dir / "reconstruction" / "cameras.json"
    if not cameras_path.exists():
        raise ValueError(f"P1 wrote no {cameras_path}: COLMAP could not reconstruct the clip (too little parallax "
                         "or texture). Re-record: slow sideways walk, 20-30 s, textured room.")
    with open(cameras_path, "r", encoding="utf-8") as f:
        cameras = json.load(f)
    width, height = frame_size_of(p0_dir / "frames")
    print(f"[3/3] {len(cameras)} cameras registered at {width}x{height}; taking the median...")
    result = calibration_from_cameras(cameras, width, height, video=str(video_path))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result
