"""Opt-in recording of a live session's RECEIVED frames, for offline replay.

A phone walk-through cannot be repeated exactly, so a session started with
``{"record": true}`` in its configure message keeps every JPEG the socket
received -- including frames the backpressure later dropped -- under the
session's run directory:

    <outputs>/<id>/frames/<frame_index:06d>.jpg   one file per received frame
    <outputs>/<id>/frames.jsonl                    one line per received frame:
        {"frame_index", "received_at", "bytes", "file", "processed"}
    <outputs>/<id>/configure.json                  the configure message as
        sent, plus what the session made of it (effective intrinsics,
        processed size)

``received_at`` is the server's monotonic clock at arrival, so a replay can
reproduce the original pacing (``scripts/replay_live.py --frames-dir``) and
``visionforge live --frames-dir`` can run the tracker on the same bytes
offline (``live/offline.py``). ``processed`` says whether the tracker saw the
frame live (``false`` = dropped by backpressure, or undecodable).

The index line is written when the frame's fate is known (processed in
``LiveSession.feed`` or dropped in the socket loop), so a session that dies
without ``finish`` still has a consistent index for everything decided so
far; ``close()`` marks whatever is still pending as not processed.

Nothing under ``frames/`` is a session: ``SessionStore`` only looks at
top-level ``outputs/<id>/`` directories, provenance lists no frames and
``persist_run`` saves none.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

FRAMES_DIRNAME = "frames"
INDEX_FILENAME = "frames.jsonl"
CONFIGURE_FILENAME = "configure.json"


class FrameRecorder:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.frames_dir = self.run_dir / FRAMES_DIRNAME
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.run_dir / INDEX_FILENAME
        self._index = open(self.index_path, "a", encoding="utf-8")
        self._pending: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()  # received() runs on the socket task, mark() in the tracker thread
        self.n_received = 0
        self.n_processed = 0
        self.n_dropped = 0
        self.closed = False

    def write_configure(self, payload: Dict[str, Any], effective: Dict[str, Any]) -> None:
        with open(self.run_dir / CONFIGURE_FILENAME, "w", encoding="utf-8") as f:
            json.dump({"configure": payload, "effective": effective, "recorded_at": time.time()}, f, indent=2)

    def received(self, frame_index: int, jpeg_bytes: bytes, received_at: float) -> None:
        name = f"{int(frame_index):06d}.jpg"
        (self.frames_dir / name).write_bytes(jpeg_bytes)
        with self._lock:
            self._pending[int(frame_index)] = {"frame_index": int(frame_index), "received_at": float(received_at),
                                               "bytes": len(jpeg_bytes), "file": name}
            self.n_received += 1

    def mark(self, frame_index: int, processed: bool) -> None:
        with self._lock:
            entry = self._pending.pop(int(frame_index), None)
            if entry is None or self.closed:
                return
            self._write(entry, processed)

    def _write(self, entry: Dict[str, Any], processed: bool) -> None:
        entry["processed"] = bool(processed)
        self._index.write(json.dumps(entry) + "\n")
        self._index.flush()
        if processed:
            self.n_processed += 1
        else:
            self.n_dropped += 1

    def close(self) -> Dict[str, Any]:
        """Flush: anything still pending was never processed. Idempotent."""
        with self._lock:
            if not self.closed:
                for idx in sorted(self._pending):
                    self._write(self._pending[idx], False)
                self._pending.clear()
                self._index.close()
                self.closed = True
        return self.summary()

    def summary(self) -> Dict[str, Any]:
        return {"dir": FRAMES_DIRNAME, "index": INDEX_FILENAME, "received": self.n_received,
                "processed": self.n_processed, "not_processed": self.n_dropped}


@dataclass
class Recording:
    run_dir: Path
    frames_dir: Path
    configure: Optional[Dict[str, Any]]      # the client's configure message, or None
    effective: Optional[Dict[str, Any]]      # what the session made of it (intrinsics, processed_size)
    entries: List[Dict[str, Any]] = field(default_factory=list)  # frames.jsonl lines, by frame_index

    def frame_bytes(self, entry: Dict[str, Any]) -> bytes:
        return (self.frames_dir / entry["file"]).read_bytes()

    @property
    def processed_entries(self) -> List[Dict[str, Any]]:
        return [e for e in self.entries if e.get("processed")]


def read_recording(path: Path) -> Recording:
    """Load a recording from its run directory or its ``frames/`` directory.
    Every indexed file must exist; the index is the truth about what was
    received."""
    p = Path(path)
    if p.name == FRAMES_DIRNAME and p.is_dir():
        run_dir = p.parent
    elif (p / FRAMES_DIRNAME).is_dir():
        run_dir = p
    else:
        raise FileNotFoundError(f"{p} is neither a recorded session directory nor its {FRAMES_DIRNAME}/ directory")
    index_path = run_dir / INDEX_FILENAME
    if not index_path.exists():
        raise FileNotFoundError(f"{index_path} missing: this recording has no index")
    entries = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.sort(key=lambda e: e["frame_index"])
    frames_dir = run_dir / FRAMES_DIRNAME
    missing = [e["file"] for e in entries if not (frames_dir / e["file"]).exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} indexed frame(s) missing under {frames_dir}, e.g. {missing[0]}")
    configure = effective = None
    conf_path = run_dir / CONFIGURE_FILENAME
    if conf_path.exists():
        with open(conf_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        configure, effective = data.get("configure"), data.get("effective")
    return Recording(run_dir=run_dir, frames_dir=frames_dir, configure=configure, effective=effective, entries=entries)
