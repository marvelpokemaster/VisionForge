import argparse
import sys
import json
from pathlib import Path
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.spatial.viewer import create_digital_twin, launch_viewer

def cmd_reconstruct(args):
    print("==================================================")
    print(" VisionForge: Offline Digital Twin Construction")
    print("==================================================")
    
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: {video_path} not found.")
        sys.exit(1)
        
    print(f"[1/5] Extracting frames from {video_path}...")
    # Typically we'd call P0 here. Since we mock this in offline testing:
    # We will assume outputs exist or run the sub-modules directly.
    import subprocess
    
    out_dir = Path("outputs/final_demo")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Run P0 (Video Ingestion)
    print("Running P0 (Video Extraction)...")
    subprocess.run([sys.executable, "-m", "visionforge.video.extract_frames", str(video_path), str(out_dir / "p0")])
    
    # Run P1 (Reconstruction)
    print("[2/5] Running Classical Reconstruction (P1)...")
    # For a real pipeline, we'd call pipeline.py from P1. Since P1 takes frames and makes sparse_cloud, we'd call it.
    subprocess.run([sys.executable, "-m", "visionforge.reconstruction.pipeline", str(out_dir / "p0" / "frames"), str(out_dir / "p1")])
    
    # Run P2 (Room Geometry)
    print("[3/5] Computing Room Geometry (P2)...")
    p1_cloud = out_dir / "p1" / "sparse_cloud.ply"
    
    if not p1_cloud.exists():
        print("Warning: P1 did not produce a sparse cloud (perhaps due to lack of motion).")
        print("Using dummy sparse cloud for demonstration purposes...")
        # Fallback to dummy generation if P1 fails (for test purposes)
        import open3d as o3d
        import numpy as np
        pts = np.random.uniform(-5, 5, (1000, 3))
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        p1_cloud.parent.mkdir(parents=True, exist_ok=True)
        o3d.io.write_point_cloud(str(p1_cloud), pcd)
        
    subprocess.run([sys.executable, "-m", "visionforge.geometry.pipeline", "--input", str(p1_cloud), "--output", str(out_dir / "p2")])
    
    # Final Phase (Scene Graph)
    print("[4/5] Generating Spatial Scene Graph...")
    room_model_file = out_dir / "p2" / "room_model.json"
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
    
    print("\nOffline construction complete! Launching Digital Twin Viewer...")
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
