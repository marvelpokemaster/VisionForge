"""In-memory P2 room geometry.

``build_room_model(points, cameras, options, seed)`` runs the exact stage
sequence of ``geometry/pipeline.py`` — clean (voxel + outlier removal +
normals) -> iterative RANSAC planes -> coplanar merge -> architectural
classification -> room measurement — on a numpy array and returns the
``room_model`` dict exactly as ``room_model.json`` would contain it, the
per-plane inlier index arrays, and the statistics dict. No files, no prints
(progress lines go to the optional ``log`` callback). ``pipeline.main()`` is
a thin file-reading / file-writing wrapper around it.

Randomness: the only random step is Open3D's ``PointCloud.segment_plane``
RANSAC. ``seed`` calls ``o3d.utility.random.seed`` and ``numpy.random.seed``
— but in Open3D 0.20 that does NOT make ``segment_plane`` reproducible (the
same seeded call on the same cloud returns different models; shown by
``tests/test_geometry_api.py::test_seeded_segment_plane_is_not_reproducible``).
Equivalence with the file-based path is therefore proven exactly by
replaying recorded RANSAC draws, and with real RANSAC only up to tolerance.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

import numpy as np
import open3d as o3d

from visionforge.geometry.plane_fitting import (
    classify_planes,
    extract_dominant_planes,
    merge_coplanar_planes,
)
from visionforge.geometry.point_cloud import clean_point_cloud
from visionforge.geometry.room_model import align_and_measure_room

VOXEL_SIZE_FRACTION = 0.005
PLANE_THRESHOLD_FRACTION = 0.01
CLASS_LABELS = ("floor", "ceiling", "wall", "unknown")


@dataclass
class GeometryOptions:
    """Mirrors pipeline.main()'s CLI arguments, same defaults."""
    voxel_size: Optional[float] = None                 # default: 0.5% of the raw bbox diagonal
    plane_distance_threshold: Optional[float] = None   # default: 1% of the raw bbox diagonal
    min_plane_inliers: float = 0.05
    max_planes: int = 10
    reference_distance: Optional[float] = None
    reference_reconstruction_distance: Optional[float] = None


@dataclass
class RoomModelResult:
    room_model: Dict[str, Any]
    plane_inliers: Dict[str, np.ndarray]   # plane id -> indices into cleaned_points
    statistics: Dict[str, Any]
    cleaned_points: np.ndarray             # (M, 3): the cloud the planes were fitted to
    n_input_points: int
    reason: Optional[str] = None           # set when no model was fitted (e.g. too few points)
    # internal, for the file writer (Open3D clouds with colours/normals)
    planes_data: Optional[Dict[str, Any]] = field(default=None, repr=False)
    cleaned_pcd: Optional[o3d.geometry.PointCloud] = field(default=None, repr=False)

    @property
    def n_planes(self) -> int:
        return len(self.room_model.get("planes", []))


def seed_everything(seed: int) -> None:
    """Seeds Open3D's global RNG and numpy. See the module docstring for what
    this does NOT guarantee."""
    o3d.utility.random.seed(int(seed))
    np.random.seed(int(seed))


def resolve_thresholds(points: np.ndarray, options: GeometryOptions):
    """(bbox_diagonal, voxel_size, plane_distance_threshold) exactly as main() resolves them."""
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    bbox_diagonal = float(np.linalg.norm(hi - lo))
    if bbox_diagonal <= 0.0:
        raise ValueError("input point cloud has zero spatial extent.")
    voxel_size = options.voxel_size if options.voxel_size is not None else VOXEL_SIZE_FRACTION * bbox_diagonal
    thr = (options.plane_distance_threshold if options.plane_distance_threshold is not None
           else PLANE_THRESHOLD_FRACTION * bbox_diagonal)
    return bbox_diagonal, voxel_size, thr


def classification_counts(planes: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {label: 0 for label in CLASS_LABELS}
    for p in planes:
        label = p.get("classification", "unknown")
        counts[label] = counts.get(label, 0) + 1
    return counts


def build_room_model(points: np.ndarray, cameras: Optional[list], options: Optional[GeometryOptions] = None,
                     seed: Optional[int] = None, *, colors: Optional[np.ndarray] = None,
                     log: Optional[Callable[[str], None]] = None) -> RoomModelResult:
    """Pure in-memory P2. ``cameras`` is the cameras.json list (or None:
    camera gravity prior recorded as unavailable). ``colors`` (N,3 in 0..1)
    only matter for the file writer's cleaned.ply. Raises ValueError for an
    empty cloud or one with zero spatial extent."""
    log = log or (lambda msg: None)
    options = options or GeometryOptions()
    start = time.time()

    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(pts) == 0:
        raise ValueError("input point cloud is empty.")
    raw_pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    if colors is not None:
        raw_pcd.colors = o3d.utility.Vector3dVector(np.asarray(colors, dtype=np.float64).reshape(-1, 3))

    bbox_diagonal, voxel_size, plane_distance_threshold = resolve_thresholds(pts, options)
    log(f"Raw cloud bounding-box diagonal: {bbox_diagonal:.4f} (reconstruction units)")
    log(f"Using voxel_size={voxel_size:.5f}, plane_distance_threshold={plane_distance_threshold:.5f}")

    if seed is not None:
        seed_everything(seed)

    pcd_clean, pc_stats = clean_point_cloud(raw_pcd, voxel_size=voxel_size)
    log(f"Cleaned point cloud: {pc_stats['cleaned_points']} / {pc_stats['raw_points']} points retained.")
    all_points = np.asarray(pcd_clean.points)

    log("Extracting dominant planes...")
    planes = extract_dominant_planes(
        pcd_clean,
        distance_threshold=plane_distance_threshold,
        min_ratio=options.min_plane_inliers,
        max_planes=options.max_planes,
        seed=seed,
    )
    log(f"Found {len(planes)} dominant plane segments before merging coplanar segments.")
    planes = merge_coplanar_planes(planes, distance_threshold=plane_distance_threshold)
    log(f"{len(planes)} planes remain after merging coplanar segments.")
    plane_inliers = {p["id"]: np.asarray(p["inlier_indices"], dtype=int) for p in planes}

    log("Classifying planes using architectural constraints...")
    planes_data = classify_planes(planes, all_points, camera_data=cameras)
    coord_sys = planes_data.get("coordinate_system")
    if coord_sys:
        log(f"UP source: {coord_sys.get('up_source')} (confidence={coord_sys.get('up_confidence', 0.0):.3f})")
        log(f"UP sources agreeing with final axis: {coord_sys.get('up_source_agreement', [])}")
    c_counts = classification_counts(planes_data["planes"])
    log(f"Classifications: {c_counts}")

    # the writer puts each plane at planes/<id>.ply; the dict records that path
    # exactly as the file-based path does, whether or not anything is written
    ply_paths = {p["id"]: f"planes/{p['id']}.ply" for p in planes_data["planes"]}

    log("Measuring room and exporting model...")
    room_model = align_and_measure_room(
        planes_data,
        ref_distance=options.reference_distance,
        rec_distance=options.reference_reconstruction_distance,
        ply_paths=ply_paths,
    )

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
            "up_source": (room_model.get("coordinate_system", {}) or {}).get("up_source"),
            "up_confidence": (room_model.get("coordinate_system", {}) or {}).get("up_confidence"),
            "up_sources": up_sources,
        },
        "room_measurements": room_model["room"],
        "processing_time_seconds": time.time() - start,
    }
    return RoomModelResult(
        room_model=room_model,
        plane_inliers=plane_inliers,
        statistics=stats,
        cleaned_points=all_points,
        n_input_points=len(pts),
        reason=None,
        planes_data=planes_data,
        cleaned_pcd=pcd_clean,
    )


def empty_room_model_result(n_points: int, reason: str) -> RoomModelResult:
    """An honest "nothing fitted" result: zero planes, every room measurement
    null, and the reason. Never a guess."""
    room_model = {
        "coordinate_system": None,
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": None, "width": None, "height": None, "floor_area": None,
            "length_method": None, "width_method": None, "height_method": None, "floor_area_method": None,
            "bounding_polygon_room": None,
        },
        "planes": [],
        "intersections": [],
        "reason": reason,
    }
    stats = {
        "point_cloud": {"raw_points": int(n_points), "cleaned_points": 0},
        "geometry": {"num_planes": 0, "classifications": {label: 0 for label in CLASS_LABELS},
                     "metric_scale_available": False, "up_source": None, "up_confidence": None, "up_sources": {}},
        "room_measurements": room_model["room"],
        "reason": reason,
    }
    return RoomModelResult(room_model, {}, stats, np.zeros((0, 3)), int(n_points), reason=reason)
