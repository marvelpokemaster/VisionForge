import argparse
import sys
import json
from pathlib import Path

from visionforge.reconstruction.two_view import run_two_view
from visionforge.reconstruction.incremental import run_incremental_sfm

def main():
    parser = argparse.ArgumentParser(description="VisionForge Prototype 1: 3D Reconstruction")
    parser.add_argument("--frames-dir", required=True, help="Directory containing extracted frames")
    parser.add_argument("--output", required=True, help="Output directory for reconstruction")
    
    args = parser.parse_args()
    
    frames_dir = Path(args.frames_dir)
    output_dir = Path(args.output)
    
    if not frames_dir.exists():
        print(f"Error: Frames directory {frames_dir} does not exist.")
        sys.exit(1)
        
    frames = sorted([f for f in frames_dir.iterdir() if f.suffix.lower() in ('.jpg', '.png')])
    if len(frames) < 2:
        print(f"Error: Need at least 2 frames in {frames_dir}, found {len(frames)}")
        sys.exit(1)
        
    print(f"Found {len(frames)} frames. Starting Pipeline P1.")
    
    # 1. Run Two-View Explicit Pipeline (Stages 1-5)
    print("\n--- Running Two-View Checkout (Stages 1-5) ---")
    two_view_dir = output_dir / "two_view"
    vis_dir = output_dir / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    
    # Pick first two frames
    f1, f2 = frames[0], frames[1]
    stats_2v = run_two_view(f1, f2, two_view_dir)
    print(f"Two-View Stats: {stats_2v}")
    
    # move visualization images to vis_dir
    if (two_view_dir / "features.jpg").exists():
        (two_view_dir / "features.jpg").rename(vis_dir / "features.jpg")
    if (two_view_dir / "matches.jpg").exists():
        (two_view_dir / "matches.jpg").rename(vis_dir / "matches.jpg")
        
    # 2. Run Incremental SfM (Stage 6)
    print("\n--- Running Incremental SfM (Stage 6) ---")
    rec_dir = output_dir / "reconstruction"
    stats_sfm = run_incremental_sfm(frames_dir, rec_dir)
    print(f"Incremental SfM Stats: {stats_sfm}")
    
    # Global statistics
    global_stats = {
        "frames_processed": len(frames),
        "two_view": stats_2v,
        "incremental": stats_sfm
    }
    
    with open(output_dir / "statistics.json", "w") as f:
        json.dump(global_stats, f, indent=2)
        
    print(f"\nPrototype 1 finished. Outputs saved in {output_dir}")
    print(f"Point cloud: {rec_dir / 'sparse_cloud.ply'}")

if __name__ == "__main__":
    main()
