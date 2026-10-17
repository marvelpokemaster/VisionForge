"""Pure classical 2D computational geometry and furniture clearance engine.

Provides:
- Standard real-world furniture catalog with metric dimensions (meters).
- 2D oriented bounding box corners and transformations.
- Classical Point-in-Polygon (winding/ray casting) and Separating Axis Theorem (SAT)
  polygon-polygon intersection detection.
- Floor clearance validator ensuring candidate furniture fits inside the room
  boundary polygon without colliding with room boundaries, obstacles, or other items.
- Auto-packing layout analyzer determining how many units of a candidate item fit.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from pydantic import BaseModel


FURNITURE_CATALOG: Dict[str, Dict[str, Any]] = {
    "bed_queen": {
        "id": "bed_queen",
        "name": "Queen Bed",
        "category": "bedroom",
        "length": 2.1,  # meters along local X (head to foot)
        "width": 1.6,   # meters along local Z (side to side)
        "height": 0.9,  # meters
        "color": "#3b82f6",  # blue
    },
    "bed_single": {
        "id": "bed_single",
        "name": "Single Bed",
        "category": "bedroom",
        "length": 2.0,
        "width": 1.0,
        "height": 0.8,
        "color": "#60a5fa",
    },
    "sofa_3seater": {
        "id": "sofa_3seater",
        "name": "3-Seater Sofa",
        "category": "living",
        "length": 2.2,
        "width": 0.9,
        "height": 0.85,
        "color": "#10b981",  # emerald
    },
    "sofa_2seater": {
        "id": "sofa_2seater",
        "name": "2-Seater Sofa",
        "category": "living",
        "length": 1.5,
        "width": 0.85,
        "height": 0.85,
        "color": "#34d399",
    },
    "work_desk": {
        "id": "work_desk",
        "name": "Work Desk",
        "category": "office",
        "length": 1.4,
        "width": 0.7,
        "height": 0.75,
        "color": "#f59e0b",  # amber
    },
    "dining_table": {
        "id": "dining_table",
        "name": "Dining Table",
        "category": "dining",
        "length": 1.6,
        "width": 0.9,
        "height": 0.75,
        "color": "#8b5cf6",  # purple
    },
    "wardrobe": {
        "id": "wardrobe",
        "name": "Wardrobe",
        "category": "bedroom",
        "length": 1.2,
        "width": 0.6,
        "height": 2.0,
        "color": "#6b7280",  # gray
    },
    "nightstand": {
        "id": "nightstand",
        "name": "Nightstand",
        "category": "bedroom",
        "length": 0.5,
        "width": 0.5,
        "height": 0.55,
        "color": "#9ca3af",
    },
}


class PlacementItem(BaseModel):
    id: str
    furniture_id: str
    center_x: float
    center_z: float
    angle_deg: float = 0.0
    custom_length: Optional[float] = None
    custom_width: Optional[float] = None
    custom_height: Optional[float] = None


def get_oriented_box_corners(
    center_x: float,
    center_z: float,
    length: float,
    width: float,
    angle_deg: float = 0.0,
) -> List[List[float]]:
    """Compute the 4 corners of an oriented rectangle in 2D (X, Z) space.
    
    Order:
      0: [-L/2, -W/2]
      1: [+L/2, -W/2]
      2: [+L/2, +W/2]
      3: [-L/2, +W/2]
    rotated counter-clockwise by angle_deg around (center_x, center_z).
    """
    rad = np.radians(angle_deg)
    cos_a = np.cos(rad)
    sin_a = np.sin(rad)
    R = np.array([[cos_a, -sin_a], [sin_a, cos_a]])

    half_l = length / 2.0
    half_w = width / 2.0
    local_corners = np.array([
        [-half_l, -half_w],
        [half_l, -half_w],
        [half_l, half_w],
        [-half_l, half_w],
    ])

    rotated = local_corners @ R.T
    world_corners = rotated + np.array([center_x, center_z])
    return world_corners.tolist()


def point_on_segment_2d(p: np.ndarray, a: np.ndarray, b: np.ndarray, tol: float = 1e-5) -> bool:
    """Check if point p lies on line segment a-b within tolerance."""
    ab = b - a
    ap = p - a
    len_ab = np.linalg.norm(ab)
    if len_ab < 1e-12:
        return float(np.linalg.norm(ap)) <= tol
    cross = ab[0] * ap[1] - ab[1] * ap[0]
    if abs(cross) / len_ab > tol:
        return False
    dot = np.dot(ap, ab)
    return -tol <= dot <= np.dot(ab, ab) + tol


def point_in_polygon_2d(point: List[float], polygon: List[List[float]]) -> bool:
    """Test if a point (x, z) is inside or on the boundary of a 2D polygon."""
    p_arr = np.array([float(point[0]), float(point[1])])
    poly_arr = np.asarray(polygon, dtype=float)
    n = len(poly_arr)
    if n < 3:
        return False

    # 1. Boundary contact check (points flush against a wall segment are valid)
    for i in range(n):
        if point_on_segment_2d(p_arr, poly_arr[i], poly_arr[(i + 1) % n]):
            return True

    # 2. Ray-casting algorithm for interior
    x, z = float(point[0]), float(point[1])
    inside = False
    p1x, p1z = poly_arr[0][0], poly_arr[0][1]
    for i in range(1, n + 1):
        p2x, p2z = poly_arr[i % n][0], poly_arr[i % n][1]
        if min(p1z, p2z) < z <= max(p1z, p2z):
            if x <= max(p1x, p2x):
                if p1z != p2z:
                    x_inters = (z - p1z) * (p2x - p1x) / (p2z - p1z) + p1x
                    if p1x == p2x or x <= x_inters:
                        inside = not inside
        p1x, p1z = p2x, p2z
    return inside


def segments_cross_interior_2d(
    p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray, eps: float = 1e-4
) -> bool:
    """Check if line segment p1-p2 strictly crosses line segment p3-p4 at an interior point."""
    d1 = p2 - p1
    d2 = p4 - p3
    det = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(det) < 1e-10:
        return False
    dp = p3 - p1
    t = (dp[0] * d2[1] - dp[1] * d2[0]) / det
    u = (dp[0] * d1[1] - dp[1] * d1[0]) / det
    return (eps < t < 1.0 - eps) and (eps < u < 1.0 - eps)


def segments_intersect_2d(
    p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray
) -> bool:
    """Check if line segment p1-p2 intersects line segment p3-p4 (includes interior crossing)."""
    return segments_cross_interior_2d(p1, p2, p3, p4)


def polygons_intersect_2d(poly1: List[List[float]], poly2: List[List[float]]) -> bool:
    """Check if two 2D convex polygons intersect using the Separating Axis Theorem (SAT)."""
    p1 = np.asarray(poly1, dtype=float)
    p2 = np.asarray(poly2, dtype=float)

    for polygon in [p1, p2]:
        n = len(polygon)
        for i in range(n):
            edge = polygon[(i + 1) % n] - polygon[i]
            # Normal perpendicular to edge
            axis = np.array([-edge[1], edge[0]])
            norm = np.linalg.norm(axis)
            if norm < 1e-12:
                continue
            axis /= norm

            # Project poly1
            proj1 = p1 @ axis
            min1, max1 = proj1.min(), proj1.max()

            # Project poly2
            proj2 = p2 @ axis
            min2, max2 = proj2.min(), proj2.max()

            # If there is a separating axis with gap > 1e-6, they do not intersect
            if max1 < min2 - 1e-6 or max2 < min1 - 1e-6:
                return False

    return True


def box_inside_polygon_2d(
    box_corners: List[List[float]], polygon: List[List[float]]
) -> bool:
    """Check if an oriented box lies entirely inside a polygon without edge crossings."""
    # 1. All 4 corners must be inside or on the boundary of the polygon
    for corner in box_corners:
        if not point_in_polygon_2d(corner, polygon):
            return False

    # 2. No box edge may cross through any polygon boundary edge
    b_pts = np.asarray(box_corners, dtype=float)
    p_pts = np.asarray(polygon, dtype=float)
    n_b = len(b_pts)
    n_p = len(p_pts)

    for i in range(n_b):
        b1, b2 = b_pts[i], b_pts[(i + 1) % n_b]
        for j in range(n_p):
            p1, p2 = p_pts[j], p_pts[(j + 1) % n_p]
            if segments_cross_interior_2d(b1, b2, p1, p2):
                return False

    return True


class FloorClearanceEngine:
    """Evaluates 2D floor clearances and furniture arrangements for a room model."""

    def __init__(self, room_model: Dict[str, Any]):
        self.room_model = room_model
        self.scale = room_model.get("scale", {}) or {}
        self.scale_factor = float(self.scale.get("scale_factor", 1.0))
        self.metric_available = bool(self.scale.get("metric_available", False))

        room = room_model.get("room", {}) or {}
        poly = room.get("bounding_polygon_room") or []
        self.raw_polygon = poly
        # Polygon in scaled/metric room coordinates (meters)
        # Note: If metric_available is False, coordinates are treated in arbitrary units
        self.floor_polygon = [
            [float(pt[0]) * self.scale_factor, float(pt[1]) * self.scale_factor]
            for pt in poly
        ]
        self.floor_area = float(room.get("floor_area", 0.0) or 0.0) * (self.scale_factor ** 2)

    def _resolve_furniture_dims(
        self,
        furniture_id: str,
        custom_length: Optional[float] = None,
        custom_width: Optional[float] = None,
        custom_height: Optional[float] = None,
    ) -> Tuple[float, float, float, str]:
        if furniture_id in FURNITURE_CATALOG:
            cat = FURNITURE_CATALOG[furniture_id]
            length = custom_length or cat["length"]
            width = custom_width or cat["width"]
            height = custom_height or cat["height"]
            name = cat["name"]
        else:
            length = custom_length or 1.0
            width = custom_width or 1.0
            height = custom_height or 0.8
            name = f"Custom ({length:.1f}m x {width:.1f}m)"
        return float(length), float(width), float(height), name

    def validate_placement(
        self,
        furniture_id: str,
        center_x: float,
        center_z: float,
        angle_deg: float = 0.0,
        placed_items: Optional[List[PlacementItem]] = None,
        custom_length: Optional[float] = None,
        custom_width: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Validate whether a furniture item can be placed at (center_x, center_z) with angle_deg."""
        if not self.floor_polygon or len(self.floor_polygon) < 3:
            return {
                "valid": False,
                "reason": "Room floor boundary polygon is unavailable",
                "corners": [],
                "distance_to_boundary": None,
            }

        length, width, height, name = self._resolve_furniture_dims(
            furniture_id, custom_length, custom_width
        )
        corners = get_oriented_box_corners(center_x, center_z, length, width, angle_deg)

        # 1. Room boundary check
        if not box_inside_polygon_2d(corners, self.floor_polygon):
            return {
                "valid": False,
                "reason": f"Out of room boundary (item extends past walls)",
                "corners": corners,
                "distance_to_boundary": 0.0,
            }

        # 2. Collision with already placed items
        if placed_items:
            for item in placed_items:
                if isinstance(item, dict):
                    i_fid = item.get("furniture_id") or ""
                    i_clen = item.get("custom_length")
                    i_cwid = item.get("custom_width")
                    i_cx = float(item.get("center_x", 0.0))
                    i_cz = float(item.get("center_z", 0.0))
                    i_ang = float(item.get("angle_deg", 0.0))
                    i_id = item.get("id", "")
                else:
                    i_fid = getattr(item, "furniture_id", "")
                    i_clen = getattr(item, "custom_length", None)
                    i_cwid = getattr(item, "custom_width", None)
                    i_cx = float(getattr(item, "center_x", 0.0))
                    i_cz = float(getattr(item, "center_z", 0.0))
                    i_ang = float(getattr(item, "angle_deg", 0.0))
                    i_id = getattr(item, "id", "")

                i_len, i_wid, _, i_name = self._resolve_furniture_dims(
                    i_fid, i_clen, i_cwid
                )
                i_corners = get_oriented_box_corners(
                    i_cx, i_cz, i_len, i_wid, i_ang
                )
                if polygons_intersect_2d(corners, i_corners):
                    return {
                        "valid": False,
                        "reason": f"Collides with placed item '{i_name}' (ID: {i_id})",
                        "corners": corners,
                        "distance_to_boundary": None,
                    }

        return {
            "valid": True,
            "reason": "Clear",
            "corners": corners,
            "dimensions": {"length": length, "width": width, "height": height},
            "item_name": name,
        }

    def auto_pack(
        self,
        furniture_id: str,
        spacing: float = 0.3,
        max_items: int = 50,
        custom_length: Optional[float] = None,
        custom_width: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Determine maximum packing of a given furniture item inside the room floor boundary."""
        if not self.floor_polygon or len(self.floor_polygon) < 3:
            return {
                "max_count": 0,
                "placements": [],
                "floor_area_m2": 0.0,
                "occupied_area_m2": 0.0,
                "usable_free_area_m2": 0.0,
            }

        length, width, height, name = self._resolve_furniture_dims(
            furniture_id, custom_length, custom_width
        )
        poly = np.asarray(self.floor_polygon, dtype=float)
        min_x, max_x = poly[:, 0].min(), poly[:, 0].max()
        min_z, max_z = poly[:, 1].min(), poly[:, 1].max()

        effective_step_x = min(length, width) / 2.0
        effective_step_z = min(length, width) / 2.0

        placed: List[PlacementItem] = []
        item_counter = 1

        # Search grid
        x_coords = np.arange(min_x, max_x, effective_step_x)
        z_coords = np.arange(min_z, max_z, effective_step_z)

        # Try orientations: 0 deg and 90 deg
        for z in z_coords:
            for x in x_coords:
                if len(placed) >= max_items:
                    break
                for angle in [0.0, 90.0]:
                    res = self.validate_placement(
                        furniture_id=furniture_id,
                        center_x=float(x),
                        center_z=float(z),
                        angle_deg=angle,
                        placed_items=placed,
                        custom_length=length + spacing,
                        custom_width=width + spacing,
                    )
                    if res["valid"]:
                        placed.append(
                            PlacementItem(
                                id=f"auto_{item_counter}",
                                furniture_id=furniture_id,
                                center_x=float(x),
                                center_z=float(z),
                                angle_deg=angle,
                                custom_length=length,
                                custom_width=width,
                                custom_height=height,
                            )
                        )
                        item_counter += 1
                        break

        unit_area = length * width
        occupied_area = float(len(placed) * unit_area)
        free_area = max(0.0, self.floor_area - occupied_area)

        return {
            "furniture_id": furniture_id,
            "furniture_name": name,
            "unit_dimensions": {"length": length, "width": width, "height": height},
            "max_count": len(placed),
            "placements": [item.model_dump() for item in placed],
            "floor_area_m2": self.floor_area,
            "occupied_area_m2": occupied_area,
            "usable_free_area_m2": free_area,
            "coverage_ratio": occupied_area / self.floor_area if self.floor_area > 0 else 0.0,
        }
