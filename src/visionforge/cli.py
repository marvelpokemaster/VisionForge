import argparse
import sys
import json
import subprocess
from pathlib import Path
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.spatial.viewer import create_digital_twin, launch_viewer


def _run_stage(cmd, description):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Error: {description} failed with exit code {result.returncode}.")
        sys.exit(1)


def cmd_reconstruct(args):
    print("==================================================")
    print(" VisionForge: Offline Digital Twin Construction")
    print("==================================================")

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: {video_path} not found.")
        sys.exit(1)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run P0 (Video Ingestion)
    print("[1/5] Extracting frames from {}...".format(video_path))
    p0_dir = out_dir / "p0"
    _run_stage(
        [sys.executable, "-m", "visionforge.video.extract_frames",
         "--input", str(video_path), "--output", str(p0_dir)],
        "P0 (Video Extraction)"
    )

    # Run P1 (Reconstruction)
    print("[2/5] Running Classical Reconstruction (P1)...")
    p1_dir = out_dir / "p1"
    _run_stage(
        [sys.executable, "-m", "visionforge.reconstruction.pipeline",
         "--frames-dir", str(p0_dir / "frames"), "--output", str(p1_dir)],
        "P1 (Reconstruction)"
    )

    p1_cloud = p1_dir / "reconstruction" / "sparse_cloud.ply"
    if not p1_cloud.exists():
        print(f"Error: P1 did not produce a sparse cloud at {p1_cloud}.")
        print("This usually means the input video lacks sufficient camera translation "
              "(parallax) for classical SfM to triangulate points. Re-record with real "
              "camera movement through the scene, not a static shot or pure pan.")
        sys.exit(1)

    # Run P2 (Room Geometry)
    print("[3/5] Computing Room Geometry (P2)...")
    p2_dir = out_dir / "p2"
    _run_stage(
        [sys.executable, "-m", "visionforge.geometry.pipeline",
         "--input", str(p1_cloud), "--output", str(p2_dir)],
        "P2 (Room Geometry)"
    )

    # Final Phase (Scene Graph)
    print("[4/5] Generating Spatial Scene Graph...")
    room_model_file = p2_dir / "room_model.json"
    if not room_model_file.exists():
        print("Error: P2 room model missing.")
        sys.exit(1)

    with open(room_model_file, "r") as f:
        room_model = json.load(f)

    sg = build_scene_graph(room_model)
    save_scene_graph(sg, out_dir / "scene_graph.json")
    print(f"Scene graph saved to {out_dir / 'scene_graph.json'}")

    # Queries
    print("[5/5] Spatial Queries Demo...")
    sqe = SpatialQueryEngine(sg)
    print(f" - Room Dimensions: {sqe.get_room_dimensions()}")
    print(f" - Floor Area: {sqe.get_floor_area():.2f}")
    largest_wall = sqe.get_largest_wall()
    if largest_wall:
        print(f" - Largest Wall: {largest_wall}")

    print("\nOffline construction complete.")

    if not args.no_viewer:
        print("Launching Digital Twin Viewer...")
        geometries = create_digital_twin(str(p1_cloud), room_model)
        launch_viewer(geometries)


def cmd_live(args):
    from visionforge.live.tracker import run_live_tracker
    run_live_tracker()


def main():
    parser = argparse.ArgumentParser(description="VisionForge CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Offline command
    rec_parser = subparsers.add_parser("reconstruct", help="Run the full offline pipeline on a video")
    rec_parser.add_argument("--video", required=True, help="Input video file")
    rec_parser.add_argument("--output", default="outputs/final_demo", help="Output directory for pipeline artifacts")
    rec_parser.add_argument("--no-viewer", action="store_true", help="Skip launching the Open3D viewer at the end")

    # Live command
    live_parser = subparsers.add_parser("live", help="Run the live camera digital twin mode")

    args = parser.parse_args()

    if args.command == "reconstruct":
        cmd_reconstruct(args)
    elif args.command == "live":
        cmd_live(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
