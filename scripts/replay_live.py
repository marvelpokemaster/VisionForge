"""Stream a video file to a running VisionForge live session the way a phone
would: JPEG frames over a WebSocket at a fixed rate, statuses printed as
they come back, then "finish".

    python scripts/replay_live.py --video data/input/synthetic_box_room_30fps.mp4 --url ws://localhost:8000/live/<id> --fps 10 [--max-width 640] [--quality 85] [--max-frames N]

The sender paces frames by --fps regardless of how fast the server replies
(so server-side backpressure is exercised for real); a receiver task prints
every status line. Requires the `websockets` package.
"""
import argparse
import asyncio
import json
import sys
import time

import cv2

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("pip install websockets")


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


async def run(args):
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f"could not open {args.video}")
    ok, first = cap.read()
    if not ok:
        sys.exit("empty video")
    h, w = first.shape[:2]
    scale = min(1.0, args.max_width / w) if args.max_width else 1.0
    size = (int(round(w * scale)), int(round(h * scale)))
    print(f"source {w}x{h} -> sending {size[0]}x{size[1]} at {args.fps} fps to {args.url}")

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"width": size[0], "height": size[1]}))
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
        period = 1.0 / args.fps
        t_next = time.perf_counter()
        sent = 0
        frame = first
        while True:
            if scale != 1.0:
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
            await ws.send(buf.tobytes())
            sent += 1
            if args.max_frames and sent >= args.max_frames:
                break
            t_next += period
            delay = t_next - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            ok, frame = cap.read()
            if not ok:
                break
        cap.release()
        print(f"sent {sent} frames; sending finish")
        await ws.send(json.dumps({"cmd": "finish"}))
        await done.wait()
        await recv_task
        print(f"statuses received: {counts['statuses']}, twin updates: {counts['updates']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", required=True)
    p.add_argument("--url", required=True, help="ws://host:port/live/<session_id>")
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--max-width", type=int, default=640, help="resize before sending (0 = native)")
    p.add_argument("--quality", type=int, default=85)
    p.add_argument("--max-frames", type=int, default=None)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
