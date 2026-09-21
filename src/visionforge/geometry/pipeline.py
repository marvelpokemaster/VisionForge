import argparse
import sys
import json
import time
import numpy as np
import open3d as o3d
from pathlib import Path

from visionforge.geometry.point_cloud import process_point_cloud
from visionforge.geometry.plane_fitting import extract_dominant_planes, classify_planes, merge_coplanar_planes
from visionforge.geometry.room_model import align_and_measure_room, export_plane_plys

VOXEL_SIZE_FRACTION = 0.005   # 0.5% of the raw cloud's bounding-box diagonal
PLANE_THRESHOLD_FRACTION = 0.01  # 1% of the raw cloud's bounding-box diagonal

def visualize_results(output_dir: Path, cleaned_pcd: o3d.geometry.PointCloud, planes_data: dict, coord_sys: dict):
    vis_dir = output_dir / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    
    # We can colorize the planes
    colored_pcd = o3d.geometry.PointCloud(cleaned_pcd)
    colors = np.zeros((len(colored_pcd.points), 3))
    
    # default color gray
    colors[:] = [0.7, 0.7, 0.7]
    
    colormap = {
        "floor": [0, 1, 0],   # Green
        "ceiling": [0, 0, 1], # Blue
        "wall": [1, 0, 0],    # Red
        "unknown": [0.5, 0.5, 0.5]
    }
    
    # Note: we need to find the indices again, or we just rely on the stored clouds.
    # It's easier to just merge the plane point clouds with colors.
    
    geometries = []
    for p in planes_data["planes"]:
        c = colormap.get(p["classification"], [0, 0, 0])
        pcd_p = p["cloud"]
        pcd_p.paint_uniform_color(c)
        geometries.append(pcd_p)
        
    # Coordinate frame
    if coord_sys:
        # up is Y in open3d default, but we can just draw a coordinate frame at the origin
        frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=1.0)
        # we could rotate it to match the room coords, but for now just add it.
        geometries.append(frame)
        
    # We cannot render to screen automatically if running in headless server, 
    # but we can save the colored planes as a PLY.
    
    merged = o3d.geometry.PointCloud()
    for g in geometries:
        if isinstance(g, o3d.geometry.PointCloud):
            merged += g
            
    o3d.io.write_point_cloud(str(vis_dir / "detected_planes.ply"), merged)

def main():
    parser = argparse.ArgumentParser(description="VisionForge Prototype 2: Room Geometry")
    parser.add_argument("--input", required=True, help="Input sparse point cloud (PLY)")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--voxel-size", type=float, default=None,
                         help=f"Voxel downsampling size (default: {VOXEL_SIZE_FRACTION*100:.1f}%% of the raw cloud's bounding-box diagonal)")
    parser.add_argument("--plane-distance-threshold", type=float, default=None,
                         help=f"RANSAC distance threshold (default: {PLANE_THRESHOLD_FRACTION*100:.1f}%% of the raw cloud's bounding-box diagonal)")
    parser.add_argument("--min-plane-inliers", type=float, default=0.05, help="Min ratio of points for a plane")
    parser.add_argument("--max-planes", type=int, default=10, help="Max planes to extract")
    parser.add_argument("--reference-distance", type=float, default=None, help="Known real-world distance (meters)")
    parser.add_argument("--reference-reconstruction-distance", type=float, default=None, help="Reconstruction distance corresponding to reference")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    start_time = time.time()

    print(f"Loading point cloud from {input_path}...")
    raw_pcd = o3d.io.read_point_cloud(str(input_path))
    if raw_pcd.is_empty():
        print("Error: input point cloud is empty.")
        sys.exit(1)

    bbox = raw_pcd.get_axis_aligned_bounding_box()
    bbox_diagonal = float(np.linalg.norm(bbox.get_max_bound() - bbox.get_min_bound()))

    voxel_size = args.voxel_size if args.voxel_size is not None else VOXEL_SIZE_FRACTION * bbox_diagonal
    plane_distance_threshold = (
        args.plane_distance_threshold if args.plane_distance_threshold is not None
        else PLANE_THRESHOLD_FRACTION * bbox_diagonal
    )
    print(f"Raw cloud bounding-box diagonal: {bbox_diagonal:.4f} (reconstruction units)")
    print(f"Using voxel_size={voxel_size:.5f}, plane_distance_threshold={plane_distance_threshold:.5f}")

    try:
        pcd_clean, pc_stats = process_point_cloud(
            input_path, output_dir, voxel_size=voxel_size
        )
    except Exception as e:
        print(f"Error processing point cloud: {e}")
        sys.exit(1)

    print(f"Cleaned point cloud: {pc_stats['cleaned_points']} / {pc_stats['raw_points']} points retained.")

    all_points = np.asarray(pcd_clean.points)

    print("Extracting dominant planes...")
    planes = extract_dominant_planes(
        pcd_clean,
        distance_threshold=plane_distance_threshold,
        min_ratio=args.min_plane_inliers,
        max_planes=args.max_planes
    )
    print(f"Found {len(planes)} dominant plane segments before merging coplanar segments.")

    planes = merge_coplanar_planes(planes, distance_threshold=plane_distance_threshold)
    print(f"{len(planes)} planes remain after merging coplanar segments.")

    planes_data = classify_planes(planes, all_points)
    
    # Classifications count
    c_counts = {"floor": 0, "ceiling": 0, "wall": 0, "unknown": 0}
    for p in planes_data["planes"]:
        c_counts[p["classification"]] += 1
        
    print(f"Classifications: {c_counts}")
    
    print("Exporting per-plane point clouds...")
    ply_paths = export_plane_plys(planes_data["planes"], output_dir)

    print("Measuring room and exporting model...")
    room_model = align_and_measure_room(
        planes_data,
        ref_distance=args.reference_distance,
        rec_distance=args.reference_reconstruction_distance,
        ply_paths=ply_paths
    )
    
    with open(output_dir / "room_model.json", "w") as f:
        json.dump(room_model, f, indent=2)
        
    print("Generating visualizations...")
    visualize_results(output_dir, pcd_clean, planes_data, planes_data.get("coordinate_system"))
    
    end_time = time.time()
    
    stats = {
        "point_cloud": pc_stats,
        "resolved_thresholds": {
            "bbox_diagonal": bbox_diagonal,
            "voxel_size": voxel_size,
            "plane_distance_threshold": plane_distance_threshold
        },
        "geometry": {
            "num_planes": len(planes),
            "classifications": c_counts,
            "metric_scale_available": room_model["scale"]["metric_available"]
        },
        "room_measurements": room_model["room"],
        "processing_time_seconds": end_time - start_time
    }
    
    with open(output_dir / "statistics.json", "w") as f:
        json.dump(stats, f, indent=2)
        
    print(f"Prototype 2 finished in {end_time - start_time:.2f}s. Outputs saved to {output_dir}")

if __name__ == "__main__":
    main()
