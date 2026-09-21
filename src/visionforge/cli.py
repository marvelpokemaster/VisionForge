import argparse
import sys
import json
import subprocess
from pathlib import Path
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.spatial.viewer import create_digital_twin, launch_viewer
from visionforge.twin.digital_twin import DigitalTwin


def _run_stage(cmd, description):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Error: {description} failed with exit code {result.returncode}.")
        sys.exit(1)


def _write_run_status(out_dir: Path, status: dict):
    with open(out_dir / "run_status.json", "w") as f:
        json.dump(status, f, indent=2)


def _build_and_save_twin(out_dir: Path, status: dict) -> DigitalTwin:
    """Marks the twin stage "running" before the build so a twin.json built
    from THIS status (or a concurrent reader of run_status.json) reflects
    the truth, not a silently-missing stage; marks it "success" after."""
    status["stages"]["twin"] = "running"
    _write_run_status(out_dir, status)

    twin = DigitalTwin.build_from_run_dir(out_dir)
    twin.save(out_dir / "twin.json")

    status["stages"]["twin"] = "success"
    _write_run_status(out_dir, status)
    return twin


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

    status = {
        "input_type": args.input_type or "unknown",
        "video": str(video_path),
        "stages": {}
    }
    _write_run_status(out_dir, status)

    # Run P0 (Video Ingestion)
    print("[1/6] Extracting frames from {}...".format(video_path))
    p0_dir = out_dir / "p0"
    _run_stage(
        [sys.executable, "-m", "visionforge.video.extract_frames",
         "--input", str(video_path), "--output", str(p0_dir)],
        "P0 (Video Extraction)"
    )
    status["stages"]["p0_frame_extraction"] = "success"
    _write_run_status(out_dir, status)

    # Run P1 (Reconstruction)
    print("[2/6] Running Classical Reconstruction (P1)...")
    p1_dir = out_dir / "p1"
    _run_stage(
        [sys.executable, "-m", "visionforge.reconstruction.pipeline",
         "--frames-dir", str(p0_dir / "frames"), "--output", str(p1_dir)],
        "P1 (Reconstruction)"
    )

    p1_cloud = p1_dir / "reconstruction" / "sparse_cloud.ply"
    if not p1_cloud.exists():
        status["stages"]["p1_reconstruction"] = "failed"
        _write_run_status(out_dir, status)
        print(f"Error: P1 did not produce a sparse cloud at {p1_cloud}.")
        print("This usually means the input video lacks sufficient camera translation "
              "(parallax) for classical SfM to triangulate points. Re-record with real "
              "camera movement through the scene, not a static shot or pure pan.")
        sys.exit(1)
    status["stages"]["p1_reconstruction"] = "success"
    _write_run_status(out_dir, status)

    # Run P2 (Room Geometry)
    print("[3/6] Computing Room Geometry (P2)...")
    p2_dir = out_dir / "p2"
    _run_stage(
        [sys.executable, "-m", "visionforge.geometry.pipeline",
         "--input", str(p1_cloud), "--output", str(p2_dir)],
        "P2 (Room Geometry)"
    )
    status["stages"]["p2_room_geometry"] = "success"
    _write_run_status(out_dir, status)

    # Final Phase (Scene Graph)
    print("[4/6] Generating Spatial Scene Graph...")
    room_model_file = p2_dir / "room_model.json"
    if not room_model_file.exists():
        status["stages"]["scene_graph"] = "failed"
        _write_run_status(out_dir, status)
        print("Error: P2 room model missing.")
        sys.exit(1)

    with open(room_model_file, "r") as f:
        room_model = json.load(f)

    cameras_file = p1_dir / "reconstruction" / "cameras.json"
    cameras = None
    if cameras_file.exists():
        with open(cameras_file, "r") as f:
            cameras = json.load(f)

    sg = build_scene_graph(room_model, cameras=cameras)
    save_scene_graph(sg, out_dir / "scene_graph.json")
    print(f"Scene graph saved to {out_dir / 'scene_graph.json'}")
    status["stages"]["scene_graph"] = "success"
    _write_run_status(out_dir, status)

    # Queries
    print("[5/6] Spatial Queries Demo...")
    sqe = SpatialQueryEngine(sg)
    print(f" - Room Dimensions: {sqe.get_room_dimensions()}")
    floor_area = sqe.get_floor_area()
    print(f" - Floor Area: {floor_area['value']:.2f} {floor_area['units']}" if floor_area else " - Floor Area: not measurable")
    largest_wall = sqe.get_largest_wall()
    if largest_wall:
        print(f" - Largest Wall: {largest_wall}")
    nearest_wall = sqe.get_nearest_wall_to_camera()
    if nearest_wall:
        print(f" - Camera distance to nearest wall: {nearest_wall['value']:.3f} {nearest_wall['units']} ({nearest_wall['wall_id']})")

    # Digital Twin
    print("[6/6] Building Digital Twin (twin.json)...")
    _build_and_save_twin(out_dir, status)
    print(f"Digital twin saved to {out_dir / 'twin.json'}")

    print("\nOffline construction complete.")

    if not args.no_viewer:
        print("Launching Digital Twin Viewer...")
        geometries = create_digital_twin(str(p1_cloud), room_model)
        launch_viewer(geometries)


def cmd_live(args):
    from visionforge.live.tracker import run_live_tracker
    run_live_tracker()


def cmd_twin_build(args):
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: run directory {run_dir} not found.")
        sys.exit(1)

    twin = DigitalTwin.build_from_run_dir(run_dir)
    out_path = run_dir / "twin.json"
    twin.save(out_path)
    print(f"Digital twin saved to {out_path}")
    print(json.dumps(twin.provenance, indent=2))


def main():
    parser = argparse.ArgumentParser(description="VisionForge CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Offline command
    rec_parser = subparsers.add_parser("reconstruct", help="Run the full offline pipeline on a video")
    rec_parser.add_argument("--video", required=True, help="Input video file")
    rec_parser.add_argument("--output", default="outputs/final_demo", help="Output directory for pipeline artifacts")
    rec_parser.add_argument("--no-viewer", action="store_true", help="Skip launching the Open3D viewer at the end")
    rec_parser.add_argument("--input-type", choices=["synthetic", "real"], default=None,
                             help="Whether --video is a synthetic rendered clip or real (physical-camera) footage; "
                                  "recorded in run_status.json / twin.json provenance. Defaults to 'unknown' if omitted.")

    # Live command
    live_parser = subparsers.add_parser("live", help="Run the live camera digital twin mode")

    # Twin command
    twin_parser = subparsers.add_parser("twin", help="Digital twin data layer commands")
    twin_subparsers = twin_parser.add_subparsers(dest="twin_command")
    twin_build_parser = twin_subparsers.add_parser("build", help="Build/rebuild twin.json from an existing run directory")
    twin_build_parser.add_argument("--run-dir", required=True, help="Run directory produced by `visionforge reconstruct`")

    args = parser.parse_args()

    if args.command == "reconstruct":
        cmd_reconstruct(args)
    elif args.command == "live":
        cmd_live(args)
    elif args.command == "twin":
        if args.twin_command == "build":
            cmd_twin_build(args)
        else:
            twin_parser.print_help()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
