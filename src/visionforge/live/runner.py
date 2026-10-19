"""Drives ``LiveTracker`` from a cv2.VideoCapture source (video file or
webcam), optionally with an OpenCV overlay window. All the I/O lives here so
the tracker core stays testable without a camera or a file."""
from __future__ import annotations

import json
import sys
import time
from typing import Optional, Union

import cv2
import numpy as np

from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.live.tracker import FrameResult, LiveTracker, TrackerConfig, TrackState

STATE_COLORS = {
    TrackState.INITIALIZING: (0, 200, 255),
    TrackState.TRACKING: (0, 220, 0),
    TrackState.LOST: (0, 0, 255),
}


def draw_overlay(frame_bgr: np.ndarray, tracker: LiveTracker, result: FrameResult, fps: float) -> np.ndarray:
    out = frame_bgr.copy()
    pts, mapped = tracker.tracked_points()
    for (x, y), m in zip(pts, mapped):
        cv2.circle(out, (int(x), int(y)), 3, (0, 255, 0) if m else (0, 255, 255), -1)
    color = STATE_COLORS[result.state]
    rms = f"{result.reprojection_rms:.2f}px" if result.reprojection_rms is not None else "-"
    lines = [
        f"{result.state.value}  frame {result.frame_index}  {fps:.1f} fps",
        f"tracked {result.n_tracked}  inliers {result.n_inliers}  rms {rms}",
        f"map {result.map_size}  keyframes {len(tracker.active_segment.keyframes) if tracker.active_segment else 0}"
        f"  segments {len(tracker.segments)}" + ("  [KF]" if result.is_keyframe else ""),
    ]
    for i, text in enumerate(lines):
        cv2.putText(out, text, (12, 26 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    return out


def run_source(source: Union[int, str], intrinsics: Optional[CameraIntrinsics] = None,
               config: Optional[TrackerConfig] = None, max_frames: Optional[int] = None,
               gui: bool = True, log_every: int = 1) -> LiveTracker:
    """Process every frame of ``source`` (a path, or 0 for the default webcam).
    If no intrinsics are given they are GUESSED from the first frame's size
    (``CameraIntrinsics.guess_for_frame``). Returns the tracker, whose
    ``export()`` writes the P1-format output."""
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source {source!r}")

    tracker: Optional[LiveTracker] = None
    frame_index = 0
    t_start = time.time()
    last_t = t_start
    fps = 0.0
    process_times = []  # seconds spent inside process_frame only (excludes decoding / GUI)
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if tracker is None:
                h, w = frame.shape[:2]
                if intrinsics is None:
                    intrinsics = CameraIntrinsics.guess_for_frame(w, h)
                print(f"Frame size {w}x{h}; intrinsics ({intrinsics.source}): "
                      f"fx={intrinsics.fx:.1f} fy={intrinsics.fy:.1f} cx={intrinsics.cx:.1f} cy={intrinsics.cy:.1f} k1={intrinsics.k1:.5f}")
                tracker = LiveTracker(intrinsics, config)

            t0 = time.perf_counter()
            result = tracker.process_frame(frame, frame_index)
            process_times.append(time.perf_counter() - t0)

            now = time.time()
            fps = 1.0 / max(now - last_t, 1e-6)
            last_t = now
            if log_every and frame_index % log_every == 0:
                rms = f"{result.reprojection_rms:.2f}" if result.reprojection_rms is not None else "-"
                print(f"[{frame_index:5d}] {result.state.value:12s} tracked={result.n_tracked:4d} "
                      f"inliers={result.n_inliers:4d} rms={rms:>5s} map={result.map_size:5d}"
                      f"{'  KF' if result.is_keyframe else ''}")

            if gui:
                cv2.imshow("VisionForge Live Tracking", draw_overlay(frame, tracker, result, fps))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("Stopped by user.")
                    break

            frame_index += 1
            if max_frames is not None and frame_index >= max_frames:
                break
    finally:
        cap.release()
        if gui:
            cv2.destroyAllWindows()

    if tracker is None:
        raise RuntimeError(f"No frames could be read from {source!r}")
    elapsed = time.time() - t_start
    pt = np.array(process_times) * 1000.0
    is_kf = np.array([r.is_keyframe for r in tracker.results], dtype=bool)
    tracker.timing = {
        "wall_time_s": elapsed,
        "wall_ms_per_frame": 1000.0 * elapsed / max(frame_index, 1),
        "process_frame_ms_mean": float(pt.mean()) if len(pt) else None,
        "process_frame_ms_median": float(np.median(pt)) if len(pt) else None,
        "process_frame_ms_p95": float(np.percentile(pt, 95)) if len(pt) else None,
        "process_frame_ms_max": float(pt.max()) if len(pt) else None,
        "keyframe_ms_mean": float(pt[is_kf].mean()) if is_kf.any() else None,
        "non_keyframe_ms_mean": float(pt[~is_kf].mean()) if (~is_kf).any() else None,
        "frames_over_33ms": int((pt > 33.0).sum()),
        "keyframes_over_33ms": int(((pt > 33.0) & is_kf).sum()),
    }
    tm = tracker.timing
    print(f"Processed {frame_index} frames in {elapsed:.1f}s ({frame_index / max(elapsed, 1e-6):.1f} fps); "
          f"process_frame: mean {tm['process_frame_ms_mean']:.1f} ms, median {tm['process_frame_ms_median']:.1f} ms, "
          f"p95 {tm['process_frame_ms_p95']:.1f} ms, max {tm['process_frame_ms_max']:.1f} ms; "
          f"keyframes {tm['keyframe_ms_mean'] or 0:.1f} ms vs other frames {tm['non_keyframe_ms_mean'] or 0:.1f} ms; "
          f"{tm['frames_over_33ms']} frames > 33 ms ({tm['keyframes_over_33ms']} of them keyframes)")
    return tracker


def run_live_tracker() -> None:
    """Webcam demo entry point (``visionforge live`` with no arguments)."""
    print("==================================================")
    print(" VisionForge: Live Classical Tracking (webcam)    ")
    print("==================================================")
    print("Press 'q' in the window to stop.")
    try:
        tracker = run_source(0, gui=True, log_every=30)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(json.dumps(tracker.report(), indent=2))
