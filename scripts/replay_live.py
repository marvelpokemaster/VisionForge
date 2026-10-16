"""Stream frames to a running VisionForge live session the way a phone
would: JPEG frames over a WebSocket, statuses printed as they come back,
then "finish".

Two sources:

    # a video file, paced at --fps (resized to --max-width, re-encoded at --quality)
    python scripts/replay_live.py --video data/input/synthetic_box_room_30fps.mp4 --url ws://localhost:8000/live/<id> --fps 10

    # a recorded session (live/recording.py): the ORIGINAL bytes at their original timing
    python scripts/replay_live.py --frames-dir outputs/<recorded id>/frames --url ws://localhost:8000/live/<new id>
    #   --fps 10            override the recorded pacing
    #   --processed-only    send only the frames the live tracker saw (skip the ones backpressure dropped)
    #   --record            ask the server to record this replay too

A recording replay sends the recorded configure message (frame size and
intrinsics) first, so the server tracks with the same intrinsics. The
sender paces frames regardless of how fast the server replies (so
server-side backpressure is exercised for real); a receiver task prints
every status line. Requires the `websockets` package.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import cv2

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("pip install websockets")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from visionforge.live.recording import read_recording  # noqa: E402


def fmt_status(s: dict) -> str:
    if "error" in s:
        return f"[{s.get('frame_index', '?'):>5}] ERROR {s['error']}"
    tw = s.get("twin_update")
    tw_txt = "-"
    if tw is not None:
        planes = tw["room_model"]["planes"] if tw.get("room_model") else []
        reason = tw["provenance"].get("reason")
        tw_txt = f"twin_update(planes={len(planes)}" + (f", reason={reason!r}" if reason else "") + ")"
    rms = f"{s['reprojection_rms']:.2f}" if s.get("reprojection_rms") is not None else "-"
    return (f"[{s['frame_index']:>5}] {s['state']:12s} tracked={s['n_tracked']:4d} inliers={s['n_inliers']:4d} "
            f"rms={rms:>5s} map={s['map_size']:5d} kf={s['n_keyframes']:3d} seg={s['segment']} "
            f"dropped={s['dropped']} {'KF ' if s['is_keyframe'] else ''}{tw_txt}")


def video_frames(args):
    """(configure message, iterator of (jpeg bytes, seconds to wait before the NEXT frame))."""
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"could not open {args.video}")
    ok, first = cap.read()
    if not ok:
        sys.exit("empty video")
    h, w = first.shape[:2]
    scale = min(1.0, args.max_width / w) if args.max_width else 1.0
    size = (int(round(w * scale)), int(round(h * scale)))
    fps = args.fps or 10.0
    print(f"source {w}x{h} -> sending {size[0]}x{size[1]} at {fps} fps to {args.url}")

    def frames():
        frame = first
        while True:
            if scale != 1.0:
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
            yield buf.tobytes(), 1.0 / fps
            ok, frame = cap.read()
            if not ok:
                break
        cap.release()

    return {"width": size[0], "height": size[1]}, frames()


def recording_frames(args):
    rec = read_recording(Path(args.frames_dir))
    entries = rec.processed_entries if args.processed_only else rec.entries
    configure = dict(rec.configure) if rec.configure else {}
    configure.pop("record", None)
    pacing = f"{args.fps} fps" if args.fps else "original timing"
    print(f"recording {rec.run_dir}: {len(entries)} of {len(rec.entries)} frames, {pacing}, "
          f"configure={json.dumps({k: v for k, v in configure.items() if k != 'intrinsics_from_cameras'})} -> {args.url}")

    def frames():
        for i, entry in enumerate(entries):
            if args.fps:
                delay = 1.0 / args.fps
            elif i + 1 < len(entries):
                delay = max(0.0, entries[i + 1]["received_at"] - entry["received_at"])
            else:
                delay = 0.0
            yield rec.frame_bytes(entry), delay

    return configure, frames()


async def run(args):
    configure, frames = recording_frames(args) if args.frames_dir else video_frames(args)
    if args.record:
        configure["record"] = True

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps(configure))
        print("configured:", await ws.recv())

        done = asyncio.Event()
        counts = {"statuses": 0, "updates": 0}

        async def receiver():
            async for msg in ws:
                data = json.loads(msg)
                if data.get("finished"):
                    print("finished:", json.dumps(data))
                    done.set()
                    return
                if "state" in data:
                    counts["statuses"] += 1
                    if data.get("twin_update") is not None:
                        counts["updates"] += 1
                print(fmt_status(data) if "state" in data or "error" in data else data)

        recv_task = asyncio.create_task(receiver())
        t_next = time.perf_counter()
        sent = 0
        for data, delay in frames:
            await ws.send(data)
            sent += 1
            if args.max_frames and sent >= args.max_frames:
                break
            t_next += delay
            wait = t_next - time.perf_counter()
            if wait > 0:
                await asyncio.sleep(wait)
        print(f"sent {sent} frames; sending finish")
        await ws.send(json.dumps({"cmd": "finish"}))
        await done.wait()
        await recv_task
        print(f"statuses received: {counts['statuses']}, twin updates: {counts['updates']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="video file to stream")
    src.add_argument("--frames-dir", help="a recorded session's directory or its frames/ directory")
    p.add_argument("--url", required=True, help="ws://host:port/live/<session_id>")
    p.add_argument("--fps", type=float, default=None,
                   help="pacing (default: 10 for --video; the recorded timing for --frames-dir)")
    p.add_argument("--max-width", type=int, default=640, help="--video only: resize before sending (0 = native)")
    p.add_argument("--quality", type=int, default=85, help="--video only: JPEG quality")
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--processed-only", action="store_true",
                   help="--frames-dir only: skip frames the live run dropped")
    p.add_argument("--record", action="store_true", help="ask the server to record this session too")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
