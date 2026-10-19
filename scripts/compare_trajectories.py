"""Sim(3)-aligned trajectory RMSE between a live-tracker export and a
reference (COLMAP) reconstruction of the same video.

    python scripts/compare_trajectories.py --live outputs/live_synth --ref outputs/final_demo [--ref-step N] [--output cmp.json]

Both arguments accept a run directory (p1/reconstruction/cameras.json is
used) or a cameras.json path. --ref-step defaults to P0's sampling step read
from <ref>/p0/metadata.json, else 1. See visionforge/live/compare.py.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from visionforge.live.compare import compare_trajectories, load_cameras, ref_step_from_run_dir  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", required=True, help="Live run directory or its cameras.json")
    parser.add_argument("--ref", required=True, help="Reference (COLMAP) run directory or its cameras.json")
    parser.add_argument("--ref-step", type=int, default=None,
                        help="Video frames per reference camera (P0 sampling step); default from p0/metadata.json, else 1")
    parser.add_argument("--live-offset", type=int, default=0,
                        help="video_frame = (number in name - offset) for --live; 0 for the live export's frame_000000 "
                             "naming, 1 for a P0/COLMAP run's 1-based frame_000001.jpg")
    parser.add_argument("--ref-offset", type=int, default=1,
                        help="same for --ref (default 1: P0/COLMAP naming; use 0 for a live export or "
                             "scripts/synthetic_clip_gt_cameras.py output)")
    parser.add_argument("--output", default=None, help="Write the comparison JSON here as well")
    args = parser.parse_args()

    ref_step = args.ref_step if args.ref_step is not None else (ref_step_from_run_dir(args.ref) or 1)
    result = compare_trajectories(load_cameras(args.live), load_cameras(args.ref), ref_step=ref_step,
                                  live_offset=args.live_offset, ref_offset=args.ref_offset)
    result["live"] = str(args.live)
    result["ref"] = str(args.ref)

    print(f"live cameras: {result['n_live']}   reference cameras: {result['n_ref']}   matched by video frame: {result['n_matched']}")
    if result["rmse"] is None:
        print(result["note"])
    else:
        print(f"sim(3) scale live->ref: {result['scale']:.4f}")
        print(f"aligned RMSE: {result['rmse']:.4f} {result['units']}")
        print(f"  = {100 * result['rmse_fraction_of_extent']:.2f}% of the reference trajectory extent ({result['reference_extent']:.3f})")
        print(f"median residual: {result['median_residual']:.4f}   max residual: {result['max_residual']:.4f}")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
