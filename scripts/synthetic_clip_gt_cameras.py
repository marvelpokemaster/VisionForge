"""Write the GROUND-TRUTH camera poses of data/input/synthetic_box_room.mp4
as a P1-format cameras.json, straight from the camera path
scripts/generate_synthetic_clip.py renders (so any trajectory produced from
that clip — COLMAP's or the live tracker's — can be scored against truth
with scripts/compare_trajectories.py).

    python scripts/synthetic_clip_gt_cameras.py [--output outputs/synthetic_gt_cameras.json] [--frames 24]

Names are frame_{video_frame_index:06d} (0-based), i.e. the live export's
convention; compare against a P0/COLMAP run with --live-offset 1.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_synthetic_clip import HALF_Z, FOCAL, PP, look_at_RT  # noqa: E402
from visionforge.live.tracker import rotation_matrix_to_quat_xyzw  # noqa: E402


def ground_truth_cameras(n_frames: int = 24):
    # identical to generate_synthetic_clip.generate()
    eye_y = 1.4
    eye_z = HALF_Z - 0.6
    xs = np.linspace(-1.8, 1.8, n_frames)
    target_ys = np.linspace(0.15, 2.2, n_frames)
    cams = []
    for i, (x, ty) in enumerate(zip(xs, target_ys)):
        R, t = look_at_RT((x, eye_y, eye_z), np.array([0.0, ty, -0.5]))
        cams.append({
            "id": i + 1,
            "name": f"frame_{i:06d}",
            "rotation_quat": rotation_matrix_to_quat_xyzw(R),
            "translation": [float(v) for v in t],
            "camera_model": "PINHOLE",
            "camera_params": [FOCAL, FOCAL, PP[0], PP[1]],
        })
    return cams


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="outputs/synthetic_gt_cameras.json")
    parser.add_argument("--frames", type=int, default=24)
    args = parser.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cams = ground_truth_cameras(args.frames)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cams, f, indent=2)
    print(f"Wrote {len(cams)} ground-truth cameras to {out}")


if __name__ == "__main__":
    main()
