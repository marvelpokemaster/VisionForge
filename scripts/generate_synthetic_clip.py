"""
Generates a real .mp4 video of a textured box room using pure OpenCV
perspective-warp rasterization of planar quads (no 3D GPU renderer, no ML).
The virtual camera dollies sideways across the room while smoothly tilting
from floor-level to ceiling-level, giving genuine translation and parallax
-- a legitimate rendered test input for the classical-CV pipeline, not a
fabricated pipeline output. This is the ONLY video the project has ever run
through end to end; it is not physical-camera footage (see
docs/PROJECT_STATE.md and docs/real_video_checklist.md).

Usage:
    python scripts/generate_synthetic_clip.py [--output PATH] [--frames N] [--fps FPS]
"""
import argparse
import sys
import numpy as np
import cv2
from pathlib import Path

W, H = 800, 600
FOCAL = float(max(W, H))  # matches two_view.py's own focal heuristic
PP = (W / 2.0, H / 2.0)
K = np.array([[FOCAL, 0, PP[0]], [0, FOCAL, PP[1]], [0, 0, 1]], dtype=np.float64)

HALF_X, HALF_Z, CEIL_Y = 3.0, 3.0, 2.5
TEX_SIZE = 512


def make_face_texture(seed):
    rng = np.random.default_rng(seed)
    tex = np.full((TEX_SIZE, TEX_SIZE, 3), int(rng.integers(20, 60)), dtype=np.uint8)
    for _ in range(220):
        color = tuple(int(c) for c in rng.integers(30, 255, size=3))
        cx, cy = rng.integers(0, TEX_SIZE, size=2)
        r = rng.integers(6, 50)
        if rng.integers(0, 2) == 0:
            cv2.circle(tex, (int(cx), int(cy)), int(r), color, -1)
        else:
            x2, y2 = cx + rng.integers(-r, r), cy + rng.integers(-r, r)
            cv2.rectangle(tex, (int(cx), int(cy)), (int(x2), int(y2)), color, -1)
    return tex


# Each face: 4 world-space corners (CCW as seen from inside the room) + inward normal
FACES = [
    dict(corners=[(-HALF_X, 0, -HALF_Z), (HALF_X, 0, -HALF_Z), (HALF_X, 0, HALF_Z), (-HALF_X, 0, HALF_Z)],
         normal=(0, 1, 0)),   # floor y=0
    dict(corners=[(-HALF_X, CEIL_Y, -HALF_Z), (HALF_X, CEIL_Y, -HALF_Z), (HALF_X, CEIL_Y, HALF_Z), (-HALF_X, CEIL_Y, HALF_Z)],
         normal=(0, -1, 0)),  # ceiling y=CEIL_Y
    dict(corners=[(-HALF_X, 0, -HALF_Z), (-HALF_X, 0, HALF_Z), (-HALF_X, CEIL_Y, HALF_Z), (-HALF_X, CEIL_Y, -HALF_Z)],
         normal=(1, 0, 0)),   # wall x=-HALF_X
    dict(corners=[(HALF_X, 0, HALF_Z), (HALF_X, 0, -HALF_Z), (HALF_X, CEIL_Y, -HALF_Z), (HALF_X, CEIL_Y, HALF_Z)],
         normal=(-1, 0, 0)),  # wall x=+HALF_X
    dict(corners=[(HALF_X, 0, -HALF_Z), (-HALF_X, 0, -HALF_Z), (-HALF_X, CEIL_Y, -HALF_Z), (HALF_X, CEIL_Y, -HALF_Z)],
         normal=(0, 0, 1)),   # wall z=-HALF_Z
    dict(corners=[(-HALF_X, 0, HALF_Z), (HALF_X, 0, HALF_Z), (HALF_X, CEIL_Y, HALF_Z), (-HALF_X, CEIL_Y, HALF_Z)],
         normal=(0, 0, -1)),  # wall z=+HALF_Z
]

for i, f in enumerate(FACES):
    f["texture"] = make_face_texture(seed=100 + i)
    f["corners"] = np.array(f["corners"], dtype=np.float64)
    f["normal"] = np.array(f["normal"], dtype=np.float64)
    f["center"] = f["corners"].mean(axis=0)

TEX_CORNERS = np.array([[0, 0], [TEX_SIZE, 0], [TEX_SIZE, TEX_SIZE], [0, TEX_SIZE]], dtype=np.float64)


def look_at_RT(eye, target, world_up=(0, 1, 0)):
    eye = np.array(eye, dtype=np.float64)
    target = np.array(target, dtype=np.float64)
    world_up = np.array(world_up, dtype=np.float64)

    zc = target - eye
    zc = zc / np.linalg.norm(zc)
    xc = np.cross(world_up, zc)
    xc = xc / np.linalg.norm(xc)
    yc = np.cross(zc, xc)

    R = np.stack([xc, yc, zc], axis=0)  # world -> camera rotation
    t = -R @ eye
    return R, t


def project(R, t, pts_world):
    pts_cam = (R @ pts_world.T).T + t
    z = pts_cam[:, 2]
    pts_2d = (K @ pts_cam.T).T
    pts_2d = pts_2d[:, :2] / pts_2d[:, 2:3]
    return pts_2d, z


def render_frame(eye, target):
    R, t = look_at_RT(eye, target)
    canvas = np.full((H, W, 3), 15, dtype=np.uint8)

    depths = []
    for f in FACES:
        pts2d, z = project(R, t, f["corners"])
        eye_to_center = np.array(eye) - f["center"]
        front_facing = np.dot(f["normal"], eye_to_center) > 0  # camera on inward-normal side
        avg_depth = z.mean()
        visible = front_facing and np.all(z > 0.15)
        depths.append((avg_depth, f, pts2d, visible))

    depths.sort(key=lambda d: -d[0])  # painter's algorithm: farthest first

    for avg_depth, f, pts2d, visible in depths:
        if not visible:
            continue
        Hmat, _ = cv2.findHomography(TEX_CORNERS, pts2d.astype(np.float64))
        if Hmat is None:
            continue
        warped = cv2.warpPerspective(f["texture"], Hmat, (W, H))
        mask = np.zeros((H, W), dtype=np.uint8)
        cv2.fillConvexPoly(mask, pts2d.astype(np.int32), 255)
        canvas[mask > 0] = warped[mask > 0]

    return canvas


H264_FOURCCS = {"avc1", "h264", "x264"}

H264_HINT = (
    "This OpenCV build cannot encode H.264 ({fourcc}): its FFmpeg has no built-in H.264 encoder and looks for "
    "Cisco's openh264 DLL (download the openh264-<version>-win64.dll named in the warning above from "
    "https://github.com/cisco/openh264/releases and put it on PATH), and no other backend took the job. "
    "Alternatives: --fourcc VP80 --output <clip>.webm (VP8/WebM, needs a VP8-capable WebView/browser), or "
    "transcode with ffmpeg: ffmpeg -i <clip>.mp4 -c:v libx264 -pix_fmt yuv420p <clip>_h264.mp4"
)


def open_writer(output_path: Path, fourcc: str, fps: float) -> cv2.VideoWriter:
    """A VideoWriter for `fourcc`, or a SystemExit that says why not.

    H.264 (avc1) is what every Android WebView / browser plays, but OpenCV's
    pip wheels ship an FFmpeg without an H.264 encoder (it prints 'Failed to
    load OpenH264 library' and 'Could not open codec libopenh264'). On
    Windows the Media Foundation backend encodes H.264 natively, so for H.264
    fourccs it is tried first and the FFmpeg noise is skipped."""
    code = cv2.VideoWriter_fourcc(*fourcc)
    size = (W, H)
    if fourcc.lower() in H264_FOURCCS and sys.platform == "win32":
        writer = cv2.VideoWriter(str(output_path), cv2.CAP_MSMF, code, fps, size)
        if writer.isOpened():
            return writer
    writer = cv2.VideoWriter(str(output_path), code, fps, size)
    if writer.isOpened():
        return writer
    if fourcc.lower() in H264_FOURCCS:
        raise SystemExit(H264_HINT.format(fourcc=fourcc))
    raise SystemExit(f"OpenCV could not open a VideoWriter for fourcc {fourcc!r} / {output_path.suffix}")


def verify_written(output_path: Path, fourcc: str, n_frames: int) -> None:
    """isOpened() can be True while the encoder silently writes nothing (seen
    with an H.264 writer whose codec failed to initialise); re-read the file."""
    cap = cv2.VideoCapture(str(output_path))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
    tag = int(cap.get(cv2.CAP_PROP_FOURCC)) if cap.isOpened() else 0
    cap.release()
    written = "".join(chr((tag >> (8 * i)) & 255) for i in range(4)).strip("\0") or "?"
    if count < n_frames or output_path.stat().st_size < 1024:
        msg = f"{output_path} re-reads as {count}/{n_frames} frames ({output_path.stat().st_size} bytes, codec {written!r})"
        if fourcc.lower() in H264_FOURCCS:
            msg += "\n" + H264_HINT.format(fourcc=fourcc)
        raise SystemExit(msg)
    print(f"Codec on disk: {written} (requested {fourcc})")


def generate(output_path: Path, n_frames: int = 24, fps: float = 2.0, save_previews: bool = False,
             fourcc: str = "mp4v") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    eye_y = 1.4
    eye_z = HALF_Z - 0.6

    xs = np.linspace(-1.8, 1.8, n_frames)
    target_ys = np.linspace(0.15, 2.2, n_frames)  # smooth tilt: floor -> ceiling across the clip
    frames = []
    for x, ty in zip(xs, target_ys):
        eye = (x, eye_y, eye_z)
        target = np.array([0.0, ty, -0.5])
        frames.append(render_frame(eye, target))

    writer = open_writer(output_path, fourcc, fps)
    for frame in frames:
        writer.write(frame)
    writer.release()
    verify_written(output_path, fourcc, len(frames))

    if save_previews:
        for idx in (0, n_frames // 4, n_frames // 2, 3 * n_frames // 4, n_frames - 1):
            cv2.imwrite(str(output_path.parent / f"_preview_frame{idx}.png"), frames[idx])

    print(f"Wrote {len(frames)} frames to {output_path} at {fps} fps")
    print(f"File size: {output_path.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="data/input/synthetic_box_room.mp4", help="Output video path")
    parser.add_argument("--frames", type=int, default=24, help="Number of frames")
    parser.add_argument("--fps", type=float, default=2.0, help="Video fps (matches extract_frames.py's default "
                                                                  "target sampling fps, so every frame is extracted)")
    parser.add_argument("--save-previews", action="store_true", help="Also save a few preview PNGs alongside the video")
    parser.add_argument("--fourcc", default="mp4v",
                        help="VideoWriter codec (default mp4v = MPEG-4 part 2, which OpenCV reads but browsers do not play). "
                             "For the frontend's file source: --fourcc avc1 with a .mp4 --output (H.264, plays in every "
                             "Android WebView; needs an H.264 encoder on this machine -- the script says so if there is "
                             "none) or --fourcc VP80 with a .webm --output (VP8, needs a VP8-capable WebView)")
    args = parser.parse_args()

    generate(Path(args.output), n_frames=args.frames, fps=args.fps, save_previews=args.save_previews, fourcc=args.fourcc)


if __name__ == "__main__":
    main()
