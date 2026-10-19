"""Run a recorded live session (live/recording.py) through ``LiveSession``
again, offline: same bytes, same frame indices, same configure message
(hence the recorded intrinsics), with the original arrival times as the
feed timestamps so the incremental geometry re-fits at the same moments.

``visionforge live --frames-dir <dir> --output <dir2>`` is this plus the
usual finish (export, P2, scene graph, twin). By default every RECEIVED
frame is fed — offline there is no backpressure, so the tracker sees what
the live run dropped; ``processed_only=True`` feeds exactly the frames the
live tracker saw, which reproduces the live run's state counts under a
deterministic tracker.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from visionforge.live.recording import Recording, read_recording
from visionforge.live.session import LiveSession


def replay_recording(frames_dir: Path, output_dir: Path, processed_only: bool = False,
                     max_frames: Optional[int] = None, finish: bool = True,
                     log: Optional[Callable[[Dict[str, Any]], None]] = None,
                     **session_kwargs: Any) -> Tuple[LiveSession, Recording]:
    """Feed the recording under ``frames_dir`` to a fresh ``LiveSession``
    whose run directory will be ``output_dir`` (= ``<parent>/<session id>``).
    ``session_kwargs`` go to ``LiveSession`` (intrinsics, tracker_factory,
    input_type, seed, ...). Returns the session (finished if ``finish``) and
    the recording."""
    rec = read_recording(Path(frames_dir))
    output_dir = Path(output_dir)
    session = LiveSession(output_dir.name, outputs_root=output_dir.parent, **session_kwargs)
    configure = dict(rec.configure) if rec.configure else {}
    configure.pop("record", None)  # a replay records nothing
    if configure:
        session.configure(configure)
    entries = rec.processed_entries if processed_only else rec.entries
    if max_frames is not None:
        entries = entries[:max_frames]
    for entry in entries:
        status = session.feed(rec.frame_bytes(entry), entry["frame_index"], entry["received_at"])
        if log is not None:
            log(status)
    if finish:
        session.finish()
    return session, rec
