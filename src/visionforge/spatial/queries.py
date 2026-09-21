import re
import numpy as np
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

from visionforge.spatial.geometry_utils import (
    polygon_min_distance,
    point_in_polygon_2d,
    PARALLEL_DOT_THRESHOLD,
)

PLANE_TYPES = ("floor", "wall", "ceiling", "unknown")


def _scale_value(value, factor):
    if isinstance(value, (list, tuple)):
        return [_scale_value(v, factor) for v in value]
    return value * factor


class SpatialQueryEngine:
    def __init__(self, scene_graph: Dict[str, Any]):
        self.graph = scene_graph

        self.nodes_by_id: Dict[str, Dict[str, Any]] = {n["id"]: n for n in scene_graph["nodes"]}
        self.nodes_by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for n in scene_graph["nodes"]:
            self.nodes_by_type[n["type"]].append(n)

        self.edges_by_source_relation: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.edges_by_target_relation: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for e in scene_graph["edges"]:
            self.edges_by_source_relation[(e["source"], e["relation"])].append(e)
            self.edges_by_target_relation[(e["target"], e["relation"])].append(e)

        room_nodes = self.nodes_by_type.get("room", [])
        self.room_node = room_nodes[0] if room_nodes else None
        scale = (self.room_node["properties"].get("scale") if self.room_node else None) or {}
        self.metric_available: bool = bool(scale.get("metric_available", False))
        self.scale_factor: float = float(scale.get("scale_factor", 1.0))

    # ------------------------------------------------------------------
    # Measurement wrapping: every returned number carries its unit context.
    # None (not 0.0) is returned for anything not measurable.
    # ------------------------------------------------------------------

    def _measurement(self, raw_value, power: int = 1) -> Optional[Dict[str, Any]]:
        if raw_value is None:
            return None
        factor = self.scale_factor ** power
        return {
            "value": _scale_value(raw_value, factor),
            "metric": self.metric_available,
            "units": "m" if self.metric_available else "reconstruction_units"
        }

    def _measurement_prescaled(self, raw_value) -> Optional[Dict[str, Any]]:
        """For values (room.length/width/height/floor_area) that already had
        scale_factor applied upstream in room_model.py -- wrap without
        scaling again."""
        if raw_value is None:
            return None
        return {
            "value": raw_value,
            "metric": self.metric_available,
            "units": "m" if self.metric_available else "reconstruction_units"
        }

    # ------------------------------------------------------------------
    # Room dimensions
    # ------------------------------------------------------------------

    def get_room_length(self) -> Optional[Dict[str, Any]]:
        if not self.nodes_by_type.get("floor"):
            return None
        return self._measurement_prescaled(self.room_node["properties"].get("length"))

    def get_room_width(self) -> Optional[Dict[str, Any]]:
        if not self.nodes_by_type.get("floor"):
            return None
        return self._measurement_prescaled(self.room_node["properties"].get("width"))

    def get_room_height(self) -> Optional[Dict[str, Any]]:
        # height is only ever computed (in room_model.py) when a floor exists
        # AND either a ceiling or at least one wall was also detected.
        if not self.nodes_by_type.get("floor"):
            return None
        if not (self.nodes_by_type.get("ceiling") or self.nodes_by_type.get("wall")):
            return None
        return self._measurement_prescaled(self.room_node["properties"].get("height"))

    def get_floor_area(self) -> Optional[Dict[str, Any]]:
        if not self.nodes_by_type.get("floor"):
            return None
        return self._measurement_prescaled(self.room_node["properties"].get("floor_area"))

    def get_room_dimensions(self) -> Dict[str, Any]:
        return {
            "length": self.get_room_length(),
            "width": self.get_room_width(),
            "height": self.get_room_height(),
            "floor_area": self.get_floor_area()
        }

    def check_rectangular_fit(self, req_length: float, req_width: float) -> bool:
        length = self.get_room_length()
        width = self.get_room_width()
        if length is None or width is None:
            return False
        l, w = length["value"], width["value"]
        return (req_length <= l and req_width <= w) or (req_length <= w and req_width <= l)

    # ------------------------------------------------------------------
    # Walls
    # ------------------------------------------------------------------

    def get_wall_area(self, wall_id: str) -> Optional[Dict[str, Any]]:
        node = self.nodes_by_id.get(wall_id)
        if node is None or node["type"] != "wall":
            return None
        area = node["properties"].get("area")
        if area is None:
            return None
        return self._measurement(area, power=2)

    def get_largest_wall(self) -> Optional[str]:
        walls = self.nodes_by_type.get("wall", [])
        if not walls:
            return None
        return max(walls, key=lambda w: w["properties"].get("area") or 0.0)["id"]

    def get_smallest_wall(self) -> Optional[str]:
        walls = self.nodes_by_type.get("wall", [])
        if not walls:
            return None
        return min(walls, key=lambda w: w["properties"].get("area") or 0.0)["id"]

    # ------------------------------------------------------------------
    # Plane-plane relations (read straight from the indexed edge lookups)
    # ------------------------------------------------------------------

    def _related_surfaces(self, plane_id: str, relation: str) -> List[str]:
        out = set()
        for e in self.edges_by_source_relation.get((plane_id, relation), []):
            out.add(e["target"])
        for e in self.edges_by_target_relation.get((plane_id, relation), []):
            out.add(e["source"])
        return sorted(out)

    def get_parallel_surfaces(self, plane_id: str) -> List[str]:
        return self._related_surfaces(plane_id, "parallel_to")

    def get_adjacent_surfaces(self, plane_id: str) -> List[str]:
        return self._related_surfaces(plane_id, "adjacent_to")

    def get_perpendicular_surfaces(self, plane_id: str) -> List[str]:
        return self._related_surfaces(plane_id, "perpendicular_to")

    def distance_between_surfaces(self, id_a: str, id_b: str) -> Optional[Dict[str, Any]]:
        a = self.nodes_by_id.get(id_a)
        b = self.nodes_by_id.get(id_b)
        if a is None or b is None or a["type"] not in PLANE_TYPES or b["type"] not in PLANE_TYPES:
            return None

        n1 = np.array(a["properties"]["normal"])
        n2 = np.array(b["properties"]["normal"])
        dot = float(np.dot(n1, n2))

        if abs(dot) > PARALLEL_DOT_THRESHOLD:
            d1 = a["properties"]["equation"][3]
            d2 = b["properties"]["equation"][3]
            d2_aligned = d2 if dot > 0 else -d2
            dist = abs(d1 - d2_aligned)
        else:
            boundary_a = a["properties"].get("boundary") or [a["properties"]["centroid"]]
            boundary_b = b["properties"].get("boundary") or [b["properties"]["centroid"]]
            dist = polygon_min_distance(boundary_a, boundary_b)

        return self._measurement(dist)

    def get_surface_intersection(self, id_a: str, id_b: str) -> Optional[Dict[str, Any]]:
        for e in self.edges_by_source_relation.get((id_a, "intersects"), []):
            if e["target"] == id_b:
                return {"point": e["point"], "direction": e["direction"], "segment": e["segment"], "segment_room": e.get("segment_room")}
        for e in self.edges_by_source_relation.get((id_b, "intersects"), []):
            if e["target"] == id_a:
                return {"point": e["point"], "direction": e["direction"], "segment": e["segment"], "segment_room": e.get("segment_room")}
        return None

    # ------------------------------------------------------------------
    # Cameras / trajectory (read directly from camera + trajectory nodes)
    # ------------------------------------------------------------------

    def _get_camera(self, index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        cameras = self.nodes_by_type.get("camera", [])
        if not cameras:
            return None
        if index is None:
            return cameras[-1]
        if 0 <= index < len(cameras):
            return cameras[index]
        return None

    def get_camera_position(self, index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        cam = self._get_camera(index)
        if cam is None:
            return None
        props = cam["properties"]
        return {
            "camera_id": cam["id"],
            "name": props.get("name"),
            "position": self._measurement(props["position"]),
            "position_room": self._measurement(props["position_room"]) if props.get("position_room") is not None else None
        }

    def get_camera_trajectory(self) -> Optional[Dict[str, Any]]:
        traj_nodes = self.nodes_by_type.get("trajectory", [])
        if not traj_nodes:
            return None
        props = traj_nodes[0]["properties"]
        return {
            "positions": self._measurement(props["positions"]),
            "positions_room": self._measurement(props["positions_room"]) if props.get("positions_room") else None,
            "num_cameras": props["num_cameras"],
            "path_length": self._measurement(props["path_length"])
        }

    def get_trajectory_length(self) -> Optional[Dict[str, Any]]:
        traj_nodes = self.nodes_by_type.get("trajectory", [])
        if not traj_nodes:
            return None
        return self._measurement(traj_nodes[0]["properties"]["path_length"])

    def _point_to_plane_distance_and_flag(self, point: List[float], plane_node: Dict[str, Any]) -> Tuple[float, Optional[bool]]:
        props = plane_node["properties"]
        normal = np.array(props["normal"])
        d = props["equation"][3]
        p = np.array(point)
        signed = float(np.dot(normal, p) + d)
        dist = abs(signed)
        foot = p - signed * normal

        within = None
        axes = props.get("in_plane_axes")
        boundary = props.get("boundary")
        if axes and boundary:
            axis_u = np.array(axes["axis_u"])
            axis_v = np.array(axes["axis_v"])
            centroid = np.array(props["centroid"])
            rel = foot - centroid
            uv = [float(rel @ axis_u), float(rel @ axis_v)]
            boundary_2d = []
            for pt in boundary:
                r = np.array(pt) - centroid
                boundary_2d.append([float(r @ axis_u), float(r @ axis_v)])
            within = point_in_polygon_2d(uv, boundary_2d)

        return dist, within

    def distance_from_camera_to_surface(self, surface_id: str, camera_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        cam = self._get_camera(camera_index)
        plane = self.nodes_by_id.get(surface_id)
        if cam is None or plane is None or plane["type"] not in PLANE_TYPES:
            return None
        dist, within = self._point_to_plane_distance_and_flag(cam["properties"]["position"], plane)
        result = self._measurement(dist)
        result["surface_id"] = surface_id
        result["camera_id"] = cam["id"]
        result["within_boundary"] = within
        return result

    def distance_from_camera_to_all_surfaces(self, camera_index: Optional[int] = None) -> Optional[Dict[str, Dict[str, Any]]]:
        cam = self._get_camera(camera_index)
        if cam is None:
            return None
        out = {}
        for ptype in PLANE_TYPES:
            for plane in self.nodes_by_type.get(ptype, []):
                dist, within = self._point_to_plane_distance_and_flag(cam["properties"]["position"], plane)
                m = self._measurement(dist)
                m["within_boundary"] = within
                out[plane["id"]] = m
        return out

    def get_nearest_wall_to_camera(self, camera_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        cam = self._get_camera(camera_index)
        walls = self.nodes_by_type.get("wall", [])
        if cam is None or not walls:
            return None

        best_id, best_dist, best_within = None, None, None
        for w in walls:
            dist, within = self._point_to_plane_distance_and_flag(cam["properties"]["position"], w)
            if best_dist is None or dist < best_dist:
                best_id, best_dist, best_within = w["id"], dist, within

        result = self._measurement(best_dist)
        result["wall_id"] = best_id
        result["camera_id"] = cam["id"]
        result["within_boundary"] = best_within
        return result

    # ------------------------------------------------------------------
    # Keyword/regex question dispatcher. Unknown questions never guess --
    # they return a clear "unsupported" response naming what IS supported.
    # ------------------------------------------------------------------

    def _answer_room_height(self, match=None) -> Dict[str, Any]:
        return {"question_type": "room_height", "supported": True, "answer": self.get_room_height()}

    def _answer_largest_wall(self, match=None) -> Dict[str, Any]:
        wall_id = self.get_largest_wall()
        return {
            "question_type": "largest_wall", "supported": True,
            "answer": {"wall_id": wall_id, "area": self.get_wall_area(wall_id) if wall_id else None}
        }

    def _answer_parallel_walls(self, match=None) -> Dict[str, Any]:
        walls = self.nodes_by_type.get("wall", [])
        answer = {w["id"]: self.get_parallel_surfaces(w["id"]) for w in walls}
        return {"question_type": "parallel_walls", "supported": True, "answer": answer}

    def _answer_camera_nearest_wall(self, match=None) -> Dict[str, Any]:
        return {"question_type": "camera_nearest_wall", "supported": True, "answer": self.get_nearest_wall_to_camera()}

    QUESTION_PATTERNS = [
        (re.compile(r"room.*height|height.*room|how (tall|high).*room", re.I),
         "_answer_room_height", "What is the room height?"),
        (re.compile(r"(largest|biggest).*wall|wall.*(largest|biggest|most area)", re.I),
         "_answer_largest_wall", "Which wall is largest?"),
        (re.compile(r"(which|what).*walls?.*parallel|parallel.*walls?", re.I),
         "_answer_parallel_walls", "Which walls are parallel?"),
        (re.compile(r"camera.*(nearest|closest).*wall|(nearest|closest).*wall.*camera|distance.*camera.*wall", re.I),
         "_answer_camera_nearest_wall", "How far is the camera from the nearest wall?"),
    ]

    def answer_question(self, question: str) -> Dict[str, Any]:
        for pattern, handler_name, _description in self.QUESTION_PATTERNS:
            if pattern.search(question):
                return getattr(self, handler_name)()

        return {
            "question_type": None,
            "supported": False,
            "answer": None,
            "message": "Unsupported question.",
            "supported_question_types": [desc for _, _, desc in self.QUESTION_PATTERNS]
        }
