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

Frames are never stored: the only image kept is the tracker's previous
grayscale frame, which KLT needs to track into the next one.

A re-initialisation after LOST opens a new tracker segment in a new,
unrelated frame; the session then drops its IncrementalRoomModel and starts
a fresh one, so points of different segments are never fitted together.
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

from visionforge.reconstruction.two_view import write_ply

from visionforge.cli import StageError, _build_and_save_twin, _run_geometry_scene_graph_twin, _write_run_status
from visionforge.geometry.api import GeometryOptions, RoomModelResult
from visionforge.geometry.incremental import IncrementalRoomModel
from visionforge.live.intrinsics import CameraIntrinsics
from visionforge.live.tracker import (LiveTracker, TrackerConfig, TrackState, rotation_matrix_to_quat_xyzw,
                                      segment_cameras, segment_points)
from visionforge.spatial.scene_graph import build_scene_graph
from visionforge.twin.digital_twin import DigitalTwin

DEFAULT_MAX_MAP_POINTS = 20000  # ~1-2 s of P2 at the measured 0.07 s / 45k points; keeps export bounded


class LiveSession:
    def __init__(self, session_id: str, intrinsics: Optional[CameraIntrinsics] = None,
                 config: Optional[TrackerConfig] = None, max_width: int = 640,
                 geometry_options: Optional[GeometryOptions] = None, min_interval_s: float = 1.0,
                 min_new_points: int = 50, min_points: int = 200, seed: Optional[int] = None,
                 input_type: str = "unknown",
                 tracker_factory: Optional[Callable[[CameraIntrinsics, TrackerConfig], LiveTracker]] = None):
        self.session_id = session_id
        self.intrinsics = intrinsics            # for the SOURCE frame size, if given up front
        self.config = config or TrackerConfig(max_map_points=DEFAULT_MAX_MAP_POINTS)
        self.max_width = int(max_width)
        self.geometry_options = geometry_options or GeometryOptions()
        self.min_interval_s = float(min_interval_s)
        self.min_new_points = int(min_new_points)
        self.min_points = int(min_points)
        self.seed = seed
        self.input_type = input_type
        self._tracker_factory = tracker_factory or (lambda intr, cfg: LiveTracker(intr, cfg))

        self.tracker: Optional[LiveTracker] = None
        self.source_size: Optional[tuple] = None     # (w, h) of the frames as received
        self.processed_size: Optional[tuple] = None  # (w, h) actually tracked
        self.scale = 1.0
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
        # feed()/finish() run in a worker thread; cloud_ply() is called from
        # request handlers, so the tracker's map is only read under this lock
        self.lock = threading.Lock()

    # ------------------------------------------------------------ configure
    def configure(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Optional first message of the protocol: frame size and/or
        intrinsics for that size. Only allowed before the first frame."""
        if self.tracker is not None:
            raise ValueError("configure must precede the first frame")
        if "intrinsics" in payload and payload["intrinsics"]:
            p = payload["intrinsics"]
            self.intrinsics = CameraIntrinsics(float(p["fx"]), float(p["fy"]), float(p["cx"]), float(p["cy"]),
                                               float(p.get("k1", 0.0)), source="client")
        elif payload.get("intrinsics_from_cameras"):
            first = payload["intrinsics_from_cameras"][0]
            self.intrinsics = CameraIntrinsics.from_colmap_params(first["camera_model"], first["camera_params"],
                                                                 source="colmap")
        if payload.get("width") and payload.get("height"):
            self._init_tracker(int(payload["width"]), int(payload["height"]))
        return {"configured": True, "session_id": self.session_id,
                "intrinsics": self.tracker.intrinsics.to_dict() if self.tracker else
                (self.intrinsics.to_dict() if self.intrinsics else None),
                "processed_size": list(self.processed_size) if self.processed_size else None}

    def record_dropped(self, n: int = 1) -> None:
        self.dropped += n

    # ----------------------------------------------------------------- feed
    def _init_tracker(self, w: int, h: int) -> None:
        self.source_size = (w, h)
        self.scale = min(1.0, self.max_width / float(w)) if w > self.max_width else 1.0
        pw, ph = (int(round(w * self.scale)), int(round(h * self.scale))) if self.scale != 1.0 else (w, h)
        self.processed_size = (pw, ph)
        base = self.intrinsics or CameraIntrinsics.guess_for_frame(w, h)
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
        now = time.monotonic() if timestamp is None else float(timestamp)
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("could not decode JPEG frame")
        with self.lock:
            return self._feed_decoded(frame, int(frame_index), now)

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

        result = self.tracker.process_frame(frame, int(frame_index))
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

    # --------------------------------------------------------------- finish
    def finish(self, outputs_root: Path) -> Path:
        """Export like `visionforge live --output <outputs_root>/<session_id>`
        and run P2 -> scene graph -> twin on it. A session that never
        initialised gets run_status live_tracking = "failed", no p2/, and a
        twin.json that says so; the directory is returned either way."""
        with self.lock:
            return self._finish_locked(Path(outputs_root))

    def _finish_locked(self, outputs_root: Path) -> Path:
        run_dir = outputs_root / self.session_id
        run_dir.mkdir(parents=True, exist_ok=True)
        status = {
            "input_type": self.input_type,
            "video": f"live:{self.session_id}",
            "mode": "live",
            "stages": {},
            "live": {"frames": self.n_frames, "dropped": self.dropped, "twin_updates": self.n_twin_updates,
                     "source_size": list(self.source_size) if self.source_size else None,
                     "processed_size": list(self.processed_size) if self.processed_size else None},
        }
        n_keyframes = 0
        if self.tracker is not None:
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
                _run_geometry_scene_graph_twin(run_dir, status, run_dir / "p1", first_step=2, total_steps=5)
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
        }
