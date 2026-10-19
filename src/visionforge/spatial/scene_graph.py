import numpy as np
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from visionforge.spatial.geometry_utils import (
    polygon_min_distance,
    point_in_polygon_2d,
    point_polygon_distance_2d,
    PARALLEL_DOT_THRESHOLD,
    PERPENDICULAR_DOT_THRESHOLD,
)

# Scale-relative thresholds (fractions of the room's own bounding-box diagonal,
# derived from the plane boundaries already computed in Task A). Monocular SfM
# scale is arbitrary, so no absolute distance constant belongs here.
ADJACENCY_DISTANCE_FRACTION = 0.05
ABOVE_BELOW_EPSILON_FRACTION = 0.02


def _quat_to_rotation_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """Unit-quaternion [x, y, z, w] -> 3x3 rotation matrix (hand-written, no scipy)."""
    n = (qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]
    ])


def _camera_world_position(rotation_quat: List[float], translation: List[float]) -> np.ndarray:
    """cameras.json stores cam_from_world: p_cam = R @ p_world + t. The camera
    center in world coordinates is the point that maps to the camera's own
    origin, i.e. R @ C + t = 0 -> C = -R^T @ t."""
    qx, qy, qz, qw = rotation_quat
    R = _quat_to_rotation_matrix(qx, qy, qz, qw)
    t = np.array(translation, dtype=float)
    return -R.T @ t


def _room_frame_point(p: np.ndarray, origin: np.ndarray, x_axis: np.ndarray, up_axis: np.ndarray, z_axis: np.ndarray) -> List[float]:
    rel = np.array(p) - origin
    return [float(np.dot(rel, x_axis)), float(np.dot(rel, up_axis)), float(np.dot(rel, z_axis))]


def _room_scale(planes: List[Dict[str, Any]]) -> float:
    """Bounding-box diagonal of every plane's boundary polygon (or centroid,
    if a boundary isn't available) -- the room's own scale, used to derive
    every distance threshold below instead of an absolute constant."""
    pts = []
    for p in planes:
        boundary = p.get("boundary")
        if boundary:
            pts.extend(boundary)
        else:
            pts.append(p["centroid"])
    if len(pts) < 2:
        return 1.0
    arr = np.array(pts, dtype=float)
    diag = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))
    return diag if diag > 1e-9 else 1.0


def build_scene_graph(room_model: Dict[str, Any], cameras: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    nodes = []
    edges = []

    room_id = "room_001"
    room_props = dict(room_model.get("room", {}))
    room_props["scale"] = room_model.get("scale", {"metric_available": False, "scale_factor": 1.0})
    nodes.append({
        "id": room_id,
        "type": "room",
        "properties": room_props
    })

    planes = room_model.get("planes", [])
    coord_sys = room_model.get("coordinate_system") or {}
    up_axis = np.array(coord_sys["up_axis"]) if "up_axis" in coord_sys else None
    x_axis = np.array(coord_sys["horizontal_axes"][0]) if "horizontal_axes" in coord_sys else None
    z_axis = np.array(coord_sys["horizontal_axes"][1]) if "horizontal_axes" in coord_sys else None
    if "origin" in coord_sys:
        origin = np.array(coord_sys["origin"])
    elif planes:
        origin = np.mean([p["centroid"] for p in planes], axis=0)
    else:
        origin = np.zeros(3)

    bounding_polygon_room = room_model.get("room", {}).get("bounding_polygon_room", [])

    room_scale = _room_scale(planes) if planes else 1.0
    adjacency_threshold = ADJACENCY_DISTANCE_FRACTION * room_scale
    height_epsilon = ABOVE_BELOW_EPSILON_FRACTION * room_scale

    # Plane nodes
    for p in planes:
        nodes.append({
            "id": p["id"],
            "type": p["type"],
            "properties": {
                "equation": p["equation"],
                "normal": p["normal"],
                "centroid": p["centroid"],
                "centroid_room": p.get("centroid_room"),
                "support": p["support"],
                "extent": p.get("extent"),
                "area": p.get("area"),
                "boundary": p.get("boundary"),
                "boundary_room": p.get("boundary_room"),
                "in_plane_axes": p.get("in_plane_axes"),
                "ply_path": p.get("ply_path")
            }
        })
        edges.append({"source": room_id, "target": p["id"], "relation": "contains"})

    # Plane-plane relationships
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            p1, p2 = planes[i], planes[j]
            n1 = np.array(p1["normal"])
            n2 = np.array(p2["normal"])
            dot_prod = float(np.dot(n1, n2))
            abs_dot = abs(dot_prod)
            angle_deg = float(np.degrees(np.arccos(np.clip(abs_dot, -1.0, 1.0))))

            if abs_dot > PARALLEL_DOT_THRESHOLD:
                edges.append({
                    "source": p1["id"], "target": p2["id"], "relation": "parallel_to",
                    "angle_deg": angle_deg
                })
            elif abs_dot < PERPENDICULAR_DOT_THRESHOLD:
                edges.append({
                    "source": p1["id"], "target": p2["id"], "relation": "perpendicular_to",
                    "angle_deg": angle_deg
                })

                boundary_a = p1.get("boundary") or [p1["centroid"]]
                boundary_b = p2.get("boundary") or [p2["centroid"]]
                min_dist = polygon_min_distance(boundary_a, boundary_b)
                if min_dist <= adjacency_threshold:
                    edges.append({
                        "source": p1["id"], "target": p2["id"], "relation": "adjacent_to",
                        "distance": float(min_dist)
                    })

            # above / below between horizontal surfaces, via room-frame height
            if p1["type"] in ("floor", "ceiling") and p2["type"] in ("floor", "ceiling"):
                h1 = (p1.get("centroid_room") or [0, 0, 0])[1]
                h2 = (p2.get("centroid_room") or [0, 0, 0])[1]
                diff = h1 - h2
                if diff > height_epsilon:
                    edges.append({"source": p1["id"], "target": p2["id"], "relation": "above", "height_difference": float(diff)})
                    edges.append({"source": p2["id"], "target": p1["id"], "relation": "below", "height_difference": float(diff)})
                elif diff < -height_epsilon:
                    edges.append({"source": p2["id"], "target": p1["id"], "relation": "above", "height_difference": float(-diff)})
                    edges.append({"source": p1["id"], "target": p2["id"], "relation": "below", "height_difference": float(-diff)})

    # intersects: reuse Task A's precomputed intersection segments, never recomputed here
    for inter in room_model.get("intersections", []):
        edges.append({
            "source": inter["plane_a"],
            "target": inter["plane_b"],
            "relation": "intersects",
            "point": inter["point"],
            "direction": inter["direction"],
            "segment": inter["segment"],
            "segment_room": inter.get("segment_room")
        })

    # Camera nodes + trajectory
    if cameras:
        ordered = sorted(cameras, key=lambda c: c.get("name") or str(c.get("id", "")))
        camera_positions = []
        camera_positions_room = []

        for cam in ordered:
            pos = _camera_world_position(cam["rotation_quat"], cam["translation"])
            pos_room = _room_frame_point(pos, origin, x_axis, up_axis, z_axis) if up_axis is not None else None

            cam_id = f"camera_{cam['id']:03d}"
            nodes.append({
                "id": cam_id,
                "type": "camera",
                "properties": {
                    "name": cam.get("name"),
                    "position": pos.tolist(),
                    "position_room": pos_room,
                    "camera_model": cam.get("camera_model"),
                    "camera_params": cam.get("camera_params")
                }
            })
            edges.append({"source": room_id, "target": cam_id, "relation": "contains"})
            camera_positions.append(pos)
            camera_positions_room.append(pos_room)

            # inside: camera vs room bounding polygon -- always reported, never dropped
            if pos_room is not None and bounding_polygon_room:
                point_xz = [pos_room[0], pos_room[2]]
                is_inside = point_in_polygon_2d(point_xz, bounding_polygon_room)
                dist_to_boundary = 0.0 if is_inside else point_polygon_distance_2d(point_xz, bounding_polygon_room)
                edges.append({
                    "source": cam_id, "target": room_id, "relation": "inside",
                    "inside": bool(is_inside), "distance_to_boundary": float(dist_to_boundary)
                })

            # above / below vs floor / ceiling
            if pos_room is not None:
                for p in planes:
                    if p["type"] not in ("floor", "ceiling"):
                        continue
                    h_plane = (p.get("centroid_room") or [0, 0, 0])[1]
                    diff = pos_room[1] - h_plane
                    if diff > height_epsilon:
                        edges.append({"source": cam_id, "target": p["id"], "relation": "above", "height_difference": float(diff)})
                        edges.append({"source": p["id"], "target": cam_id, "relation": "below", "height_difference": float(diff)})
                    elif diff < -height_epsilon:
                        edges.append({"source": p["id"], "target": cam_id, "relation": "above", "height_difference": float(-diff)})
                        edges.append({"source": cam_id, "target": p["id"], "relation": "below", "height_difference": float(-diff)})

        if camera_positions:
            path_length = float(sum(
                np.linalg.norm(camera_positions[k + 1] - camera_positions[k])
                for k in range(len(camera_positions) - 1)
            ))
            trajectory_id = "trajectory_001"
            nodes.append({
                "id": trajectory_id,
                "type": "trajectory",
                "properties": {
                    "positions": [pos.tolist() for pos in camera_positions],
                    "positions_room": camera_positions_room,
                    "num_cameras": len(camera_positions),
                    "path_length": path_length
                }
            })
            edges.append({"source": room_id, "target": trajectory_id, "relation": "contains"})

    return {
        "nodes": nodes,
        "edges": edges
    }

def save_scene_graph(scene_graph: Dict[str, Any], output_path: Path):
    with open(output_path, 'w') as f:
        json.dump(scene_graph, f, indent=2)
