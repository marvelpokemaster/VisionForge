"""P2 room geometry, file-based CLI.

A thin wrapper around ``geometry/api.py``'s ``build_room_model``: read the
PLY + cameras.json, build the model in memory, write the same files as
before. Side effects, in order:

  1. ``<output>/`` created.
  2. progress lines on stdout (the "Loaded camera poses" line now comes
     before the cloud statistics instead of after plane extraction; the
     "Exporting per-plane point clouds..." line now follows "Measuring room";
     nothing parses these).
  3. exit 1 with the same messages for an empty cloud, a zero-extent cloud,
     or a cleaning failure.
  4. ``pointcloud/raw.ply``, ``pointcloud/cleaned.ply``
  5. ``planes/<plane_id>.ply`` per merged plane (paths recorded in room_model)
  6. ``room_model.json``
  7. ``visualizations/detected_planes.ply`` (if any plane) and
     ``visualizations/coordinate_frame.ply`` (if a coordinate system was found)
  8. ``statistics.json`` (``processing_time_seconds`` = whole run incl. writes)
"""
import argparse
import sys
import json
import time
import numpy as np
import open3d as o3d
from pathlib import Path

from visionforge.geometry.api import (
    GeometryOptions,
    PLANE_THRESHOLD_FRACTION,
    VOXEL_SIZE_FRACTION,
    build_room_model,
)
from visionforge.geometry.point_cloud import write_point_cloud_files
from visionforge.geometry.room_model import export_plane_plys


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


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed Open3D's and numpy's RNGs before plane extraction (default: unseeded, as before). "
             "Note: Open3D 0.20's segment_plane is not reproducible even when seeded; see geometry/api.py.",
    )
    return parser


def options_from_args(args) -> GeometryOptions:
    return GeometryOptions(
        voxel_size=args.voxel_size,
        plane_distance_threshold=args.plane_distance_threshold,
        min_plane_inliers=args.min_plane_inliers,
        max_planes=args.max_planes,
        reference_distance=args.reference_distance,
        reference_reconstruction_distance=args.reference_reconstruction_distance,
    )


def main():
    args = build_parser().parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    print(f"Loading point cloud from {input_path}...")
    raw_pcd = o3d.io.read_point_cloud(str(input_path))
    if raw_pcd.is_empty():
        print("Error: input point cloud is empty.")
        sys.exit(1)
    points = np.asarray(raw_pcd.points)
    colors = np.asarray(raw_pcd.colors) if raw_pcd.has_colors() else None

    camera_data = _load_camera_data(output_dir, args.cameras)

    try:
        result = build_room_model(points, camera_data, options_from_args(args), seed=args.seed,
                                  colors=colors, log=print)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Error processing point cloud: {exc}")
        sys.exit(1)

    write_point_cloud_files(output_dir, raw_pcd, result.cleaned_pcd)

    print("Exporting per-plane point clouds...")
    ply_paths = export_plane_plys(result.planes_data["planes"], output_dir)
    assert all(result.room_model["planes"][i]["ply_path"] == ply_paths[p["id"]]
               for i, p in enumerate(result.room_model["planes"]))

    with (output_dir / "room_model.json").open("w", encoding="utf-8") as f:
        json.dump(result.room_model, f, indent=2)

    print("Generating visualizations...")
    visualize_results(
        output_dir,
        result.cleaned_pcd,
        result.planes_data,
        result.planes_data.get("coordinate_system"),
    )

    end_time = time.time()
    stats = dict(result.statistics)
    stats["processing_time_seconds"] = end_time - start_time

    with (output_dir / "statistics.json").open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(
        f"Prototype 2 finished in {end_time - start_time:.2f}s. "
        f"Outputs saved to {output_dir}"
    )


if __name__ == "__main__":
    main()
