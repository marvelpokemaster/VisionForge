"""A live tracking session: JPEG frames in, status + twin updates out, a
normal run directory at the end.

``LiveSession`` owns one ``LiveTracker`` and, per tracker segment, one
``IncrementalRoomModel``. ``feed()`` decodes a JPEG, downscales it to
``max_width`` (scaling the intrinsics to match), tracks it, and — when the
incremental geometry decides to re-fit — builds a ``DigitalTwin`` from the
ACTIVE segment entirely in memory (``segment_points`` / ``segment_cameras``
from live/tracker.py → ``IncrementalRoomModel.update`` → ``build_scene_graph``
→ ``DigitalTwin.from_parts``). ``finish()`` exports the tracker and runs the
same P2 → scene graph → twin chain as ``visionforge live --output``.

Frames are not stored unless the configure message says ``"record": true``
(see live/recording.py): then every RECEIVED JPEG is written under the run
directory for offline replay. Otherwise the only image kept is the tracker's
previous grayscale frame, which KLT needs to track into the next one.

A re-initialisation after LOST opens a new tracker segment in a new,
unrelated frame; the session then drops its IncrementalRoomModel and starts
a fresh one, so points of different segments are never fitted together.

Timing: every processed frame's wall time inside ``feed`` (decode + resize +
track + incremental geometry), the tracker-only part, and the arrival
intervals between processed frames are kept, and ``finish`` writes their
mean / p50 / p95 and the delivered fps to ``tracking_report.timing`` — the
CLI runner fills the same field for video files.
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from visionforge.reconstruction.two_view import write_ply

from visionforge.cli import StageError, _build_and_save_twin, _run_geometry_scene_graph_twin, _write_run_status
from visionforge.geometry.api import GeometryOptions, RoomModelResult
from visionforge.geometry.incremental import IncrementalRoomModel
from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.live.recording import FrameRecorder
from visionforge.live.tracker import (LiveTracker, TrackerConfig, TrackState, rotation_matrix_to_quat_xyzw,
                                      segment_cameras, segment_points)
from visionforge.spatial.scene_graph import build_scene_graph
from visionforge.twin.digital_twin import DigitalTwin

DEFAULT_MAX_MAP_POINTS = 20000  # ~1-2 s of P2 at the measured 0.07 s / 45k points; keeps export bounded
# Live sessions get frames at ~10 fps from a hand-held phone; on the first
# real-phone run the tracked-fraction gate fired on almost every frame
# (docs/live_tracking.md §11), so live keyframes are at least this many
# frames apart. The CLI (video files) keeps TrackerConfig's default of 1.
LIVE_KEYFRAME_MIN_GAP = 3
CLIENT_INTRINSICS_SOURCES = ("client", "phone_default")
SLOW_FRAME_MS = 100.0


def _pct(values: List[float], q: float) -> Optional[float]:
    return float(np.percentile(values, q)) if values else None


class LiveSession:
    def __init__(self, session_id: str, intrinsics: Optional[CameraIntrinsics] = None,
                 config: Optional[TrackerConfig] = None, max_width: int = 640,
                 geometry_options: Optional[GeometryOptions] = None, min_interval_s: float = 1.0,
                 min_new_points: int = 50, min_points: int = 200, seed: Optional[int] = None,
                 input_type: str = "unknown",
                 tracker_factory: Optional[Callable[[CameraIntrinsics, TrackerConfig], LiveTracker]] = None,
                 outputs_root: Optional[Path] = None):
        self.session_id = session_id
        self.intrinsics = intrinsics            # for the SOURCE frame size (or intrinsics_size), if given up front
        self.config = config or TrackerConfig(max_map_points=DEFAULT_MAX_MAP_POINTS,
                                              keyframe_min_gap=LIVE_KEYFRAME_MIN_GAP)
        self.max_width = int(max_width)
        self.geometry_options = geometry_options or GeometryOptions()
        self.min_interval_s = float(min_interval_s)
        self.min_new_points = int(min_new_points)
        self.min_points = int(min_points)
        self.seed = seed
        self.input_type = input_type
        self._tracker_factory = tracker_factory or (lambda intr, cfg: LiveTracker(intr, cfg))
        self.outputs_root = Path(outputs_root) if outputs_root is not None else None

        self.tracker: Optional[LiveTracker] = None
        self.source_size: Optional[tuple] = None     # (w, h) of the frames as received
        self.processed_size: Optional[tuple] = None  # (w, h) actually tracked
        self.scale = 1.0
        self._intrinsics_size: Optional[tuple] = None  # (w, h) the given intrinsics are expressed in, if not the source
        self._inc: Optional[IncrementalRoomModel] = None
        self._segment_index: Optional[int] = None
        self.n_frames = 0
        self.dropped = 0
        self.n_twin_updates = 0
        self.last_status: Optional[Dict[str, Any]] = None
        self.created_at = time.time()
        self.finished = False
        self.run_dir: Optional[Path] = None
        self.stage_status: Dict[str, str] = {}
        self.recorder: Optional[FrameRecorder] = None
        self.configure_payload: Optional[Dict[str, Any]] = None
        # timing (see module docstring)
        self._process_ms: List[float] = []
        self._track_ms: List[float] = []
        self._keyframe_flags: List[bool] = []
        self._arrivals: List[float] = []
        # feed()/finish() run in a worker thread; cloud_ply() is called from
        # request handlers, so the tracker's map is only read under this lock
        self.lock = threading.Lock()

    # ------------------------------------------------------------ configure
    def configure(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Optional first message of the protocol: frame size and/or
        intrinsics, and ``record``. Only allowed before the first frame.

        Intrinsics: ``intrinsics`` {fx, fy, cx, cy, k1?, source?} with
        ``source`` "client" (default) or "phone_default" (the frontend's
        0.8 × longer-side stopgap), or ``intrinsics_from_cameras`` (entries of
        a cameras.json, e.g. from ``visionforge calibrate``; the first entry
        is used). Either is for ``width × height`` unless ``intrinsics_size``
        [w, h] (or ``width``/``height`` on the cameras entry) says they were
        measured at another size with the same aspect ratio — then they are
        scaled to the source size before the usual downscale."""
        if self.tracker is not None:
            raise ValueError("configure must precede the first frame")
        if "intrinsics" in payload and payload["intrinsics"]:
            p = payload["intrinsics"]
            source = str(p.get("source") or "client")
            if source not in CLIENT_INTRINSICS_SOURCES:
                raise ValueError(f"intrinsics.source must be one of {CLIENT_INTRINSICS_SOURCES}, not {source!r}")
            self.intrinsics = CameraIntrinsics(float(p["fx"]), float(p["fy"]), float(p["cx"]), float(p["cy"]),
                                               float(p.get("k1", 0.0)), source=source)
        elif payload.get("intrinsics_from_cameras"):
            first = payload["intrinsics_from_cameras"][0]
            self.intrinsics = CameraIntrinsics.from_colmap_params(first["camera_model"], first["camera_params"],
                                                                 source="colmap")
            if first.get("width") and first.get("height") and not payload.get("intrinsics_size"):
                self._intrinsics_size = (int(first["width"]), int(first["height"]))
        if payload.get("intrinsics_size"):
            w, h = payload["intrinsics_size"]
            self._intrinsics_size = (int(w), int(h))
        if payload.get("record"):
            if self.outputs_root is None:
                raise ValueError("record requested but this session has no outputs root to record into")
            if self.recorder is None:
                self.recorder = FrameRecorder(self.outputs_root / self.session_id)
        if payload.get("width") and payload.get("height"):
            self._init_tracker(int(payload["width"]), int(payload["height"]))
        self.configure_payload = dict(payload)
        reply = {"configured": True, "session_id": self.session_id,
                 "intrinsics": self.tracker.intrinsics.to_dict() if self.tracker else
                 (self.intrinsics.to_dict() if self.intrinsics else None),
                 "processed_size": list(self.processed_size) if self.processed_size else None,
                 "recording": self.recorder is not None,
                 "keyframe_min_gap": self.config.keyframe_min_gap}
        if self.recorder is not None:
            self.recorder.write_configure(payload, {k: v for k, v in reply.items() if k != "configured"})
        return reply

    # ------------------------------------------------------------ recording
    def record_received(self, frame_index: int, jpeg_bytes: bytes, received_at: float) -> None:
        """Called by the socket loop for EVERY frame that arrives, before the
        backpressure decides its fate. No-op unless recording."""
        if self.recorder is not None:
            self.recorder.received(frame_index, jpeg_bytes, received_at)

    def record_dropped(self, n: int = 1, frame_index: Optional[int] = None) -> None:
        self.dropped += n
        if self.recorder is not None and frame_index is not None:
            self.recorder.mark(frame_index, False)

    def close_recording(self) -> Optional[Dict[str, Any]]:
        return self.recorder.close() if self.recorder is not None else None

    # ----------------------------------------------------------------- feed
    def _init_tracker(self, w: int, h: int) -> None:
        self.source_size = (w, h)
        self.scale = min(1.0, self.max_width / float(w)) if w > self.max_width else 1.0
        pw, ph = (int(round(w * self.scale)), int(round(h * self.scale))) if self.scale != 1.0 else (w, h)
        self.processed_size = (pw, ph)
        base = self.intrinsics or CameraIntrinsics.guess_for_frame(w, h)
        if self.intrinsics is not None and self._intrinsics_size is not None and self._intrinsics_size != (w, h):
            iw, ih = self._intrinsics_size
            if abs((iw / ih) - (w / h)) > 0.02 * (w / h):
                raise ValueError(f"intrinsics were measured at {iw}x{ih}, whose aspect ratio differs from the "
                                 f"{w}x{h} frames; calibrate in the same orientation as the live frames")
            s = w / float(iw)
            base = CameraIntrinsics(base.fx * s, base.fy * s, base.cx * s, base.cy * s, base.k1, base.source)
        if self.scale != 1.0:
            # pixel-unit intrinsics scale with the image; k1 is in normalised coordinates and does not
            intr = CameraIntrinsics(base.fx * self.scale, base.fy * self.scale, base.cx * self.scale,
                                    base.cy * self.scale, base.k1, base.source)
        else:
            intr = base
        self.tracker = self._tracker_factory(intr, self.config)

    def feed(self, jpeg_bytes: bytes, frame_index: int, timestamp: Optional[float] = None) -> Dict[str, Any]:
        if self.finished:
            raise ValueError("session already finished")
        now = time.perf_counter() if timestamp is None else float(timestamp)
        t0 = time.perf_counter()
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            if self.recorder is not None:
                self.recorder.mark(frame_index, False)
            raise ValueError("could not decode JPEG frame")
        with self.lock:
            status = self._feed_decoded(frame, int(frame_index), now)
            self._process_ms.append(1000.0 * (time.perf_counter() - t0))
            self._keyframe_flags.append(bool(status["is_keyframe"]))
            self._arrivals.append(now)
        if self.recorder is not None:
            self.recorder.mark(frame_index, True)
        return status

    def cloud_ply(self) -> str:
        """The ACTIVE segment's current map as ASCII PLY text (the same
        points export() would write), for the live viewer. Empty PLY when
        nothing is initialised."""
        with self.lock:
            seg = self.tracker.active_segment if self.tracker is not None else None
            if seg is None:
                xyz, colors = np.zeros((0, 3)), None
            else:
                xyz, colors = segment_points(seg)
        buf = io.StringIO()
        write_ply(buf, xyz, colors if len(xyz) else None)
        return buf.getvalue()

    def _feed_decoded(self, frame: np.ndarray, frame_index: int, now: float) -> Dict[str, Any]:
        h, w = frame.shape[:2]
        if self.tracker is None:
            self._init_tracker(w, h)
        elif (w, h) != self.source_size:
            raise ValueError(f"frame size changed from {self.source_size} to {(w, h)}")
        if self.scale != 1.0:
            frame = cv2.resize(frame, self.processed_size, interpolation=cv2.INTER_AREA)

        t0 = time.perf_counter()
        result = self.tracker.process_frame(frame, int(frame_index))
        self._track_ms.append(1000.0 * (time.perf_counter() - t0))
        self.n_frames += 1

        seg = self.tracker.active_segment
        twin_update = None
        if seg is not None:
            if self._segment_index != seg.index:
                # first initialisation, or a re-initialisation after LOST: new frame, new geometry
                self._inc = IncrementalRoomModel(self.geometry_options, min_points=self.min_points,
                                                 min_new_points=self.min_new_points,
                                                 min_interval_s=self.min_interval_s, seed=self.seed)
                self._segment_index = seg.index
            if result.state == TrackState.TRACKING:
                xyz, _ = segment_points(seg)
                cams = segment_cameras(seg, self.tracker.intrinsics)
                fit = self._inc.update(xyz, cams, now=now)
                if fit is not None:
                    twin_update = self._twin_dict(fit, cams, result, seg)
                    self.n_twin_updates += 1

        pose = None
        if result.pose is not None:
            R, t = result.pose
            pose = {"rotation_quat": rotation_matrix_to_quat_xyzw(R), "translation": [float(v) for v in t]}
        status = {
            "session_id": self.session_id,
            "frame_index": int(frame_index),
            "state": result.state.value,
            "n_tracked": int(result.n_tracked),
            "n_inliers": int(result.n_inliers),
            "reprojection_rms": result.reprojection_rms,
            "is_keyframe": bool(result.is_keyframe),
            "map_size": int(result.map_size),
            "n_keyframes": len(seg.keyframes) if seg is not None else 0,
            "segment": seg.index if seg is not None else None,
            "n_segments": len(self.tracker.segments),
            "frames": self.n_frames,
            "dropped": self.dropped,
            "source_size": list(self.source_size),
            "processed_size": list(self.processed_size),
            "intrinsics_source": self.tracker.intrinsics.source,
            "pose": pose,
            "twin_update": twin_update,
        }
        self.last_status = status
        return status

    def _twin_dict(self, fit: RoomModelResult, cams, result, seg) -> Dict[str, Any]:
        room_model = fit.room_model
        fitted = fit.reason is None
        scene_graph = build_scene_graph(room_model, cameras=cams) if fitted and fit.n_planes > 0 else None
        provenance = {
            "run_dir": None,
            "source_files": {"room_model": None, "cameras": None, "scene_graph": None, "sparse_cloud": None},
            "stage_status": {
                "live_tracking": result.state.value,
                "p2_room_geometry": "success" if fitted else "skipped",
                "scene_graph": "success" if scene_graph is not None else "skipped",
                "twin": "success",
            },
            "input_type": self.input_type,
            "live": True,
            "session_id": self.session_id,
            "frames": self.n_frames,
            "keyframes": len(seg.keyframes),
            "map_size": len(seg.map_points),
            "segment": seg.index,
            "fit_index": (fit.statistics.get("incremental") or {}).get("fit_index"),
            "reason": fit.reason,
            "intrinsics_source": self.tracker.intrinsics.source,
        }
        return DigitalTwin.from_parts(room_model, cams, scene_graph, provenance).to_dict()

    # --------------------------------------------------------------- timing
    def timing_summary(self) -> Dict[str, Any]:
        """mean / p50 / p95 of the per-frame process time (whole feed) and of
        the tracker-only part, the inter-arrival interval between processed
        frames, delivered fps, and how many frames took over 100 ms. All
        from processed frames; dropped frames have no process time."""
        pm, tm = self._process_ms, self._track_ms
        gaps = [1000.0 * (b - a) for a, b in zip(self._arrivals, self._arrivals[1:])]
        span = (self._arrivals[-1] - self._arrivals[0]) if len(self._arrivals) > 1 else 0.0
        kf = np.array(self._keyframe_flags, dtype=bool)
        pma = np.array(pm) if pm else np.zeros(0)
        return {
            "frames": len(pm),
            "wall_time_s": span,
            "delivered_fps": (len(pm) - 1) / span if span > 0 else None,
            "process_frame_ms_mean": float(np.mean(pm)) if pm else None,
            "process_frame_ms_p50": _pct(pm, 50),
            "process_frame_ms_p95": _pct(pm, 95),
            "process_frame_ms_max": float(max(pm)) if pm else None,
            "track_ms_mean": float(np.mean(tm)) if tm else None,
            "track_ms_p50": _pct(tm, 50),
            "track_ms_p95": _pct(tm, 95),
            "interarrival_ms_mean": float(np.mean(gaps)) if gaps else None,
            "interarrival_ms_p50": _pct(gaps, 50),
            "interarrival_ms_p95": _pct(gaps, 95),
            "interarrival_ms_max": float(max(gaps)) if gaps else None,
            "frames_over_100ms": int((pma > SLOW_FRAME_MS).sum()) if pm else 0,
            "keyframe_ms_mean": float(pma[kf].mean()) if pm and kf.any() else None,
            "non_keyframe_ms_mean": float(pma[~kf].mean()) if pm and (~kf).any() else None,
        }

    # --------------------------------------------------------------- finish
    def finish(self, outputs_root: Optional[Path] = None) -> Path:
        """Export like `visionforge live --output <outputs_root>/<session_id>`
        and run P2 -> scene graph -> twin on it. A session that never
        initialised gets run_status live_tracking = "failed", no p2/, and a
        twin.json that says so; the directory is returned either way."""
        root = Path(outputs_root) if outputs_root is not None else self.outputs_root
        if root is None:
            raise ValueError("finish needs an outputs root")
        with self.lock:
            return self._finish_locked(root)

    def _finish_locked(self, outputs_root: Path) -> Path:
        run_dir = outputs_root / self.session_id
        run_dir.mkdir(parents=True, exist_ok=True)
        recording = self.close_recording()
        status = {
            "input_type": self.input_type,
            "video": f"live:{self.session_id}",
            "mode": "live",
            "stages": {},
            "live": {"frames": self.n_frames, "dropped": self.dropped, "twin_updates": self.n_twin_updates,
                     "source_size": list(self.source_size) if self.source_size else None,
                     "processed_size": list(self.processed_size) if self.processed_size else None,
                     "timing": self.timing_summary(),
                     "recording": recording},
        }
        n_keyframes = 0
        if self.tracker is not None:
            self.tracker.timing = status["live"]["timing"]
            report = self.tracker.export(run_dir, video=status["video"])
            n_keyframes = report["n_keyframes"]
        if n_keyframes == 0:
            status["stages"]["live_tracking"] = "failed"
            status["error"] = "the tracker never initialised (no keyframes); nothing to build geometry from"
            _write_run_status(run_dir, status)
            _build_and_save_twin(run_dir, status)
        else:
            status["stages"]["live_tracking"] = "success"
            _write_run_status(run_dir, status)
            try:
                _run_geometry_scene_graph_twin(run_dir, status, run_dir / "p1", first_step=2, total_steps=5,
                                               seed=self.seed)
            except StageError as exc:
                for stage in ("p2_room_geometry", "scene_graph"):
                    if stage not in status["stages"]:
                        status["stages"][stage] = "failed"
                        break
                status["error"] = str(exc)
                _write_run_status(run_dir, status)
                _build_and_save_twin(run_dir, status)
        self.stage_status = dict(status["stages"])
        self.finished = True
        self.run_dir = run_dir
        return run_dir

    def summary(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "frames": self.n_frames,
            "dropped": self.dropped,
            "twin_updates": self.n_twin_updates,
            "finished": self.finished,
            "created_at": self.created_at,
            "last_status": self.last_status,
            "recording": self.recorder.summary() if self.recorder is not None else None,
        }
