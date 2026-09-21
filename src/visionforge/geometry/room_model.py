import numpy as np
import json
import open3d as o3d
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PERPENDICULAR_DOT_THRESHOLD = 0.25  # matches the convention used in plane_fitting/scene_graph


def _in_plane_axes(normal: np.ndarray, up_axis: np.ndarray, x_axis: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Orthonormal basis (axis_u, axis_v) spanning the plane. axis_v is the
    projection of up_axis onto the plane (a wall's true vertical direction);
    for near-horizontal planes (floor/ceiling), where up_axis is ~parallel to
    the normal, falls back to the projection of the room's x_axis instead."""
    v = up_axis - np.dot(up_axis, normal) * normal
    if np.linalg.norm(v) < 1e-3:
        v = x_axis - np.dot(x_axis, normal) * normal
    v = v / np.linalg.norm(v)
    u = np.cross(normal, v)
    u = u / np.linalg.norm(u)
    return u, v


def _convex_hull_2d(points: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain convex hull (no scipy dependency). points: (N,2).
    Returns ordered hull vertices CCW."""
    pts = np.unique(points, axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    return np.array(hull)


def _polygon_area_2d(hull: np.ndarray) -> float:
    if len(hull) < 3:
        return 0.0
    x = hull[:, 0]
    y = hull[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _plane_boundary(cloud: o3d.geometry.PointCloud, centroid: np.ndarray, axis_u: np.ndarray, axis_v: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Convex hull of the plane's inliers projected onto the plane, lifted
    back to 3D. Returns (hull_3d (N,3), hull_2d (N,2))."""
    pts = np.asarray(cloud.points)
    rel = pts - centroid
    coords_2d = np.column_stack([rel @ axis_u, rel @ axis_v])
    hull_2d = _convex_hull_2d(coords_2d)
    if len(hull_2d) == 0:
        return np.zeros((0, 3)), hull_2d
    hull_3d = centroid + hull_2d[:, 0:1] * axis_u + hull_2d[:, 1:2] * axis_v
    return hull_3d, hull_2d


def _room_frame_point(p: np.ndarray, origin: np.ndarray, x_axis: np.ndarray, up_axis: np.ndarray, z_axis: np.ndarray) -> List[float]:
    rel = p - origin
    return [float(np.dot(rel, x_axis)), float(np.dot(rel, up_axis)), float(np.dot(rel, z_axis))]


def _room_origin(planes: List[Dict[str, Any]]) -> np.ndarray:
    """Floor centroid (largest floor by support) if a floor was detected,
    else the mean of all plane centroids. Never fabricated: just a reference
    point for expressing coordinates in the room frame, not a measurement."""
    floors = [p for p in planes if p["classification"] == "floor"]
    if floors:
        largest = max(floors, key=lambda p: p["inliers"])
        return np.array(largest["centroid"])
    return np.mean([p["centroid"] for p in planes], axis=0)


def _plane_intersection(
    plane_a: Dict[str, Any], plane_b: Dict[str, Any],
    boundary_a_3d: np.ndarray, boundary_b_3d: np.ndarray
) -> Optional[Dict[str, Any]]:
    """Intersection line of two planes, clipped to the overlap of their
    boundary extents along the line direction. Returns None if the planes
    aren't (near-)perpendicular, are degenerate, or their extents don't
    overlap -- an intersection is never fabricated when it doesn't exist."""
    n1 = np.array(plane_a["normal"])
    d1 = plane_a["equation"][3]
    n2 = np.array(plane_b["normal"])
    d2 = plane_b["equation"][3]

    if abs(np.dot(n1, n2)) >= PERPENDICULAR_DOT_THRESHOLD:
        return None

    direction = np.cross(n1, n2)
    norm_dir = np.linalg.norm(direction)
    if norm_dir < 1e-6:
        return None
    direction = direction / norm_dir

    ref_point = (np.array(plane_a["centroid"]) + np.array(plane_b["centroid"])) / 2.0
    M = np.array([n1, n2, direction])
    rhs = np.array([-d1, -d2, np.dot(direction, ref_point)])
    try:
        point_on_line = np.linalg.solve(M, rhs)
    except np.linalg.LinAlgError:
        return None

    if len(boundary_a_3d) == 0 or len(boundary_b_3d) == 0:
        return None

    t_a = (boundary_a_3d - point_on_line) @ direction
    t_b = (boundary_b_3d - point_on_line) @ direction
    lo = max(t_a.min(), t_b.min())
    hi = min(t_a.max(), t_b.max())
    if hi <= lo:
        return None  # extents do not overlap

    p_start = point_on_line + lo * direction
    p_end = point_on_line + hi * direction

    return {
        "plane_a": plane_a["id"],
        "plane_b": plane_b["id"],
        "point": point_on_line.tolist(),
        "direction": direction.tolist(),
        "segment": [p_start.tolist(), p_end.tolist()]
    }


def export_plane_plys(planes: List[Dict[str, Any]], output_dir: Path) -> Dict[str, str]:
    """Save each plane's (post-merge) inlier cloud as its own PLY file.
    Returns {plane_id: path relative to output_dir}."""
    planes_dir = output_dir / "planes"
    planes_dir.mkdir(parents=True, exist_ok=True)
    ply_paths = {}
    for p in planes:
        filename = f"{p['id']}.ply"
        o3d.io.write_point_cloud(str(planes_dir / filename), p["cloud"])
        ply_paths[p["id"]] = f"planes/{filename}"
    return ply_paths


def align_and_measure_room(
    planes_data: Dict[str, Any],
    ref_distance: float = None,
    rec_distance: float = None,
    ply_paths: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:

    coord_sys = planes_data.get("coordinate_system")
    planes = planes_data.get("planes", [])
    
    scale_factor = 1.0
    metric_available = False
    
    if ref_distance is not None and rec_distance is not None and rec_distance > 0:
        scale_factor = ref_distance / rec_distance
        metric_available = True
        
    # Find floor bounds to estimate length/width
    length, width, height, area = 0.0, 0.0, 0.0, 0.0
    # Provenance of each measurement, so the query engine/UI can say how
    # confident to be: "floor_to_ceiling" (measured, strongest), vs.
    # "wall_extent_estimate" (a weaker estimate from wall point extent when no
    # ceiling was detected), vs. "floor_extent" (length/width/area, always
    # derived from the floor boundary's own extent).
    height_method = None
    length_method = None
    width_method = None
    floor_area_method = None

    if coord_sys:
        up = np.array(coord_sys["up_axis"])
        x_ax = np.array(coord_sys["horizontal_axes"][0])
        z_ax = np.array(coord_sys["horizontal_axes"][1])

        # Estimate height
        floors = [p for p in planes if p["classification"] == "floor"]
        ceilings = [p for p in planes if p["classification"] == "ceiling"]

        if floors and ceilings:
            f_c = np.array(floors[0]["centroid"])
            c_c = np.array(ceilings[0]["centroid"])
            height = abs(np.dot(c_c - f_c, up)) * scale_factor
            height_method = "floor_to_ceiling"
        elif floors:
            # Try to guess height from the highest point in walls
            f_c = np.array(floors[0]["centroid"])
            max_h = 0
            found_wall_points = False
            for p in planes:
                if p["classification"] == "wall":
                    pts = np.asarray(p["cloud"].points)
                    if len(pts) > 0:
                        found_wall_points = True
                        h = np.max(np.dot(pts - f_c, up))
                        max_h = max(max_h, h)
            height = max_h * scale_factor
            if found_wall_points:
                height_method = "wall_extent_estimate"

        # Estimate length and width from floor boundary
        if floors:
            floor_pts = np.asarray(floors[0]["cloud"].points)
            if len(floor_pts) > 0:
                # project onto X and Z
                x_coords = np.dot(floor_pts, x_ax)
                z_coords = np.dot(floor_pts, z_ax)

                l_min, l_max = np.min(x_coords), np.max(x_coords)
                w_min, w_max = np.min(z_coords), np.max(z_coords)

                length = (l_max - l_min) * scale_factor
                width = (w_max - w_min) * scale_factor
                area = length * width
                length_method = width_method = floor_area_method = "floor_extent"

    # Per-plane boundary polygon / extent / area / room-frame coordinates,
    # plus room-wide intersection lines and bounding polygon. All computed
    # in raw reconstruction-frame units (unscaled), consistent with the
    # existing per-plane equation/normal/centroid fields above -- only the
    # top-level "room" summary applies scale_factor, as it already did.
    boundaries_3d: Dict[str, np.ndarray] = {}
    plane_extras: Dict[str, Dict[str, Any]] = {}
    bounding_polygon_room = []
    intersections = []

    if coord_sys and planes:
        up = np.array(coord_sys["up_axis"])
        x_ax = np.array(coord_sys["horizontal_axes"][0])
        z_ax = np.array(coord_sys["horizontal_axes"][1])
        origin = _room_origin(planes)
        coord_sys["origin"] = origin.tolist()  # reconstruction-frame reference point for the room frame

        for p in planes:
            normal = np.array(p["normal"])
            centroid = np.array(p["centroid"])
            axis_u, axis_v = _in_plane_axes(normal, up, x_ax)

            hull_3d, hull_2d = _plane_boundary(p["cloud"], centroid, axis_u, axis_v)
            boundaries_3d[p["id"]] = hull_3d

            if len(hull_2d) > 0:
                extent_width = float(hull_2d[:, 0].max() - hull_2d[:, 0].min())
                extent_height = float(hull_2d[:, 1].max() - hull_2d[:, 1].min())
            else:
                extent_width, extent_height = 0.0, 0.0
            plane_area = _polygon_area_2d(hull_2d)

            boundary_room = [_room_frame_point(v, origin, x_ax, up, z_ax) for v in hull_3d]

            plane_extras[p["id"]] = {
                "in_plane_axes": {"axis_u": axis_u.tolist(), "axis_v": axis_v.tolist()},
                "extent": {"width": extent_width, "height": extent_height},
                "area": plane_area,
                "boundary": hull_3d.tolist(),
                "boundary_room": boundary_room,
                "centroid_room": _room_frame_point(centroid, origin, x_ax, up, z_ax),
                "ply_path": ply_paths.get(p["id"]) if ply_paths else None
            }

        # Plane-plane intersection lines: perpendicular pairs whose extents overlap.
        for i in range(len(planes)):
            for j in range(i + 1, len(planes)):
                pa, pb = planes[i], planes[j]
                result = _plane_intersection(pa, pb, boundaries_3d[pa["id"]], boundaries_3d[pb["id"]])
                if result:
                    result["point_room"] = _room_frame_point(np.array(result["point"]), origin, x_ax, up, z_ax)
                    result["segment_room"] = [
                        _room_frame_point(np.array(v), origin, x_ax, up, z_ax) for v in result["segment"]
                    ]
                    intersections.append(result)

        # Room bounding polygon: convex hull of every plane's inliers, projected
        # onto the room's horizontal (x, z) plane -- the room's footprint outline.
        all_points = np.concatenate([np.asarray(p["cloud"].points) for p in planes], axis=0)
        rel = all_points - origin
        horiz_2d = np.column_stack([rel @ x_ax, rel @ z_ax])
        hull_room_2d = _convex_hull_2d(horiz_2d)
        bounding_polygon_room = (hull_room_2d * scale_factor).tolist()

    # Prepare JSON output
    out_planes = []
    for p in planes:
        extras = plane_extras.get(p["id"], {})
        out_planes.append({
            "id": p["id"],
            "type": p["classification"],
            "equation": p["equation"],
            "normal": p["normal"],
            "support": p["inliers"],
            "centroid": p["centroid"],
            **extras
        })

    room_model = {
        "coordinate_system": coord_sys,
        "scale": {
            "metric_available": metric_available,
            "scale_factor": scale_factor
        },
        "room": {
            "length": float(length),
            "width": float(width),
            "height": float(height),
            "floor_area": float(area),
            "length_method": length_method,
            "width_method": width_method,
            "height_method": height_method,
            "floor_area_method": floor_area_method,
            "bounding_polygon_room": bounding_polygon_room
        },
        "planes": out_planes,
        "intersections": intersections
    }

    return room_model
