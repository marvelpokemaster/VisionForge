import argparse
import sys
import json
import time
import numpy as np
import open3d as o3d
from pathlib import Path

from visionforge.geometry.point_cloud import process_point_cloud
from visionforge.geometry.plane_fitting import (
    extract_dominant_planes,
    classify_planes,
    merge_coplanar_planes,
)
from visionforge.geometry.room_model import align_and_measure_room, export_plane_plys


VOXEL_SIZE_FRACTION = 0.005
PLANE_THRESHOLD_FRACTION = 0.01


def _load_camera_data(output_dir: Path, explicit_path: str = None):
    """
    Load the reconstruction camera JSON for the Task-1 gravity prior.

    Default expected location from the repository contract:
        <output>/p1/reconstruction/cameras.json

    Geometry-only runs without that file continue to work, but the camera
    gravity source will be recorded as unavailable rather than fabricated.
    """
    if explicit_path:
        camera_path = Path(explicit_path)
        candidates = [camera_path]
    else:
        # In the full reconstruct command, geometry lives under <root>/p2
        # while the reconstruction cameras live under sibling <root>/p1.
        candidates = [
            output_dir.parent / "p1" / "reconstruction" / "cameras.json",
            output_dir / "p1" / "reconstruction" / "cameras.json",
        ]
        camera_path = next((p for p in candidates if p.exists()), candidates[0])

    if not camera_path.exists():
        print(f"Camera poses not found at {camera_path}; camera gravity prior unavailable.")
        return None

    try:
        with camera_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded camera poses from {camera_path}")
        return data
    except Exception as exc:
        print(f"Warning: could not read camera poses from {camera_path}: {exc}")
        return None


def visualize_results(
    output_dir: Path,
    cleaned_pcd: o3d.geometry.PointCloud,
    planes_data: dict,
    coord_sys: dict,
):
    vis_dir = output_dir / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)

    colormap = {
        "floor": [0, 1, 0],
        "ceiling": [0, 0, 1],
        "wall": [1, 0, 0],
        "unknown": [0.5, 0.5, 0.5],
    }

    merged = o3d.geometry.PointCloud()

    for p in planes_data["planes"]:
        c = colormap.get(p["classification"], [0, 0, 0])
        plane_cloud = o3d.geometry.PointCloud(p["cloud"])
        plane_cloud.paint_uniform_color(c)
        merged += plane_cloud

    if not merged.is_empty():
        o3d.io.write_point_cloud(
            str(vis_dir / "detected_planes.ply"),
            merged,
        )

    # Preserve the existing coordinate-frame output behavior.
    if coord_sys:
        frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=1.0)
        o3d.io.write_triangle_mesh(
            str(vis_dir / "coordinate_frame.ply"),
            frame,
        )


def main():
    parser = argparse.ArgumentParser(
        description="VisionForge Prototype 2: Room Geometry"
    )
    parser.add_argument("--input", required=True, help="Input sparse point cloud (PLY)")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument(
        "--voxel-size",
        type=float,
        default=None,
        help=(
            f"Voxel downsampling size (default: "
            f"{VOXEL_SIZE_FRACTION * 100:.1f}% of raw cloud bbox diagonal)"
        ),
    )
    parser.add_argument(
        "--plane-distance-threshold",
        type=float,
        default=None,
        help=(
            f"RANSAC distance threshold (default: "
            f"{PLANE_THRESHOLD_FRACTION * 100:.1f}% of raw cloud bbox diagonal)"
        ),
    )
    parser.add_argument(
        "--min-plane-inliers",
        type=float,
        default=0.05,
        help="Min ratio of points for a plane",
    )
    parser.add_argument(
        "--max-planes",
        type=int,
        default=10,
        help="Max planes to extract",
    )
    parser.add_argument(
        "--reference-distance",
        type=float,
        default=None,
        help="Known real-world distance (meters)",
    )
    parser.add_argument(
        "--reference-reconstruction-distance",
        type=float,
        default=None,
        help="Reconstruction distance corresponding to reference",
    )
    parser.add_argument(
        "--cameras",
        type=str,
        default=None,
        help="Optional path to reconstruction cameras.json",
    )

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
    bbox_diagonal = float(
        np.linalg.norm(bbox.get_max_bound() - bbox.get_min_bound())
    )
    if bbox_diagonal <= 0.0:
        print("Error: input point cloud has zero spatial extent.")
        sys.exit(1)

    voxel_size = (
        args.voxel_size
        if args.voxel_size is not None
        else VOXEL_SIZE_FRACTION * bbox_diagonal
    )
    plane_distance_threshold = (
        args.plane_distance_threshold
        if args.plane_distance_threshold is not None
        else PLANE_THRESHOLD_FRACTION * bbox_diagonal
    )

    print(
        f"Raw cloud bounding-box diagonal: {bbox_diagonal:.4f} "
        "(reconstruction units)"
    )
    print(
        f"Using voxel_size={voxel_size:.5f}, "
        f"plane_distance_threshold={plane_distance_threshold:.5f}"
    )

    try:
        pcd_clean, pc_stats = process_point_cloud(
            input_path,
            output_dir,
            voxel_size=voxel_size,
        )
    except Exception as exc:
        print(f"Error processing point cloud: {exc}")
        sys.exit(1)

    print(
        f"Cleaned point cloud: {pc_stats['cleaned_points']} / "
        f"{pc_stats['raw_points']} points retained."
    )

    all_points = np.asarray(pcd_clean.points)

    print("Extracting dominant planes...")
    planes = extract_dominant_planes(
        pcd_clean,
        distance_threshold=plane_distance_threshold,
        min_ratio=args.min_plane_inliers,
        max_planes=args.max_planes,
    )
    print(
        f"Found {len(planes)} dominant plane segments before "
        "merging coplanar segments."
    )

    planes = merge_coplanar_planes(
        planes,
        distance_threshold=plane_distance_threshold,
    )
    print(f"{len(planes)} planes remain after merging coplanar segments.")

    camera_data = _load_camera_data(output_dir, args.cameras)

    print("Classifying planes using architectural constraints...")
    planes_data = classify_planes(
        planes,
        all_points,
        camera_data=camera_data,
    )

    coord_sys = planes_data.get("coordinate_system")
    if coord_sys:
        print(
            f"UP source: {coord_sys.get('up_source')} "
            f"(confidence={coord_sys.get('up_confidence', 0.0):.3f})"
        )
        print(
            "UP sources agreeing with final axis: "
            f"{coord_sys.get('up_source_agreement', [])}"
        )

    c_counts = {"floor": 0, "ceiling": 0, "wall": 0, "unknown": 0}
    for p in planes_data["planes"]:
        label = p.get("classification", "unknown")
        c_counts[label] = c_counts.get(label, 0) + 1

    print(f"Classifications: {c_counts}")

    print("Exporting per-plane point clouds...")
    ply_paths = export_plane_plys(planes_data["planes"], output_dir)

    print("Measuring room and exporting model...")
    room_model = align_and_measure_room(
        planes_data,
        ref_distance=args.reference_distance,
        rec_distance=args.reference_reconstruction_distance,
        ply_paths=ply_paths,
    )

    with (output_dir / "room_model.json").open("w", encoding="utf-8") as f:
        json.dump(room_model, f, indent=2)

    print("Generating visualizations...")
    visualize_results(
        output_dir,
        pcd_clean,
        planes_data,
        planes_data.get("coordinate_system"),
    )

    end_time = time.time()

    up_sources = {}
    if room_model.get("coordinate_system"):
        up_sources = room_model["coordinate_system"].get("up_sources", {})

    stats = {
        "point_cloud": pc_stats,
        "resolved_thresholds": {
            "bbox_diagonal": bbox_diagonal,
            "voxel_size": voxel_size,
            "plane_distance_threshold": plane_distance_threshold,
        },
        "geometry": {
            "num_planes": len(planes),
            "classifications": c_counts,
            "metric_scale_available": room_model["scale"]["metric_available"],
            "up_source": (
                room_model.get("coordinate_system", {}) or {}
            ).get("up_source"),
            "up_confidence": (
                room_model.get("coordinate_system", {}) or {}
            ).get("up_confidence"),
            "up_sources": up_sources,
        },
        "room_measurements": room_model["room"],
        "processing_time_seconds": end_time - start_time,
    }

    with (output_dir / "statistics.json").open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(
        f"Prototype 2 finished in {end_time - start_time:.2f}s. "
        f"Outputs saved to {output_dir}"
    )


if __name__ == "__main__":
    main()
