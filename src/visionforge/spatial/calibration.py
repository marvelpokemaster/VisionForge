"""Metric scale calibration engine.

Allows calibrating monocular room models to real-world metric dimensions (meters)
using:
1. Known room dimension: "room_width" or "room_length".
2. Two-point distance reference: Euclidean distance between user-selected points.
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np


def calibrate_room_model_scale(
    room_model: Dict[str, Any],
    reference_type: str,
    known_distance_meters: float,
    pt_a: Optional[List[float]] = None,
    pt_b: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Return a new room_model dictionary with metric scale applied."""
    import math
    if math.isnan(known_distance_meters) or math.isinf(known_distance_meters) or known_distance_meters <= 0.0:
        raise ValueError("known_distance_meters must be a finite, strictly positive number.")
    if known_distance_meters < 0.05 or known_distance_meters > 500.0:
        raise ValueError(
            f"known_distance_meters ({known_distance_meters}m) is outside plausible room range [0.05m, 500m]."
        )

    model = copy.deepcopy(room_model)
    prev_scale = float(model.get("scale", {}).get("scale_factor", 1.0))
    if prev_scale <= 0 or math.isnan(prev_scale) or math.isinf(prev_scale):
        prev_scale = 1.0

    room = model.get("room", {})
    unscaled_length = float(room.get("length") or 0.0) / prev_scale
    unscaled_width = float(room.get("width") or 0.0) / prev_scale
    unscaled_height = float(room.get("height") or 0.0) / prev_scale
    unscaled_floor_area = float(room.get("floor_area") or 0.0) / (prev_scale ** 2)

    if reference_type == "room_width":
        if unscaled_width <= 0 or math.isnan(unscaled_width):
            raise ValueError("Room width is unavailable or zero for calibration.")
        scale_factor = known_distance_meters / unscaled_width

    elif reference_type == "room_length":
        if unscaled_length <= 0 or math.isnan(unscaled_length):
            raise ValueError("Room length is unavailable or zero for calibration.")
        scale_factor = known_distance_meters / unscaled_length

    elif reference_type == "two_points":
        if pt_a is None or pt_b is None:
            raise ValueError("Two points pt_a and pt_b are required for 'two_points' calibration.")
        if len(pt_a) != 3 or len(pt_b) != 3:
            raise ValueError("Reference points pt_a and pt_b must each have exactly 3 coordinates [X, Y, Z].")
        arr_a = np.asarray(pt_a, dtype=float)
        arr_b = np.asarray(pt_b, dtype=float)
        if not np.all(np.isfinite(arr_a)) or not np.all(np.isfinite(arr_b)):
            raise ValueError("Reference point coordinates must be finite numbers.")
        raw_dist = float(np.linalg.norm(arr_a - arr_b)) / prev_scale
        if raw_dist <= 1e-6:
            raise ValueError("Distance between reference points is zero.")
        scale_factor = known_distance_meters / raw_dist

    else:
        raise ValueError(f"Unknown reference_type '{reference_type}'. Expected 'room_width', 'room_length', or 'two_points'.")

    # Update scale metadata
    model["scale"] = {
        "metric_available": True,
        "scale_factor": float(scale_factor),
        "reference_type": reference_type,
        "known_distance_meters": float(known_distance_meters),
    }

    # Update room measurements
    poly = room.get("bounding_polygon_room") or []
    # If unscaled polygon is available, scale it
    unscaled_poly = [
        [float(pt[0]) / prev_scale, float(pt[1]) / prev_scale]
        for pt in poly
    ]
    scaled_poly = [
        [float(pt[0]) * scale_factor, float(pt[1]) * scale_factor]
        for pt in unscaled_poly
    ]

    model["room"]["length"] = float(unscaled_length * scale_factor)
    model["room"]["width"] = float(unscaled_width * scale_factor)
    model["room"]["height"] = float(unscaled_height * scale_factor)
    model["room"]["floor_area"] = float(unscaled_floor_area * (scale_factor ** 2))
    model["room"]["bounding_polygon_room"] = scaled_poly

    # Scale plane attributes where room frame measurements are recorded
    planes = model.get("planes", [])
    for p in planes:
        if "extent" in p and p["extent"]:
            p["extent"]["width"] = float(p["extent"]["width"] / prev_scale * scale_factor)
            p["extent"]["height"] = float(p["extent"]["height"] / prev_scale * scale_factor)
        if "area" in p and p["area"] is not None:
            p["area"] = float(p["area"] / (prev_scale ** 2) * (scale_factor ** 2))
        if "centroid_room" in p and p["centroid_room"]:
            p["centroid_room"] = [float(v) / prev_scale * scale_factor for v in p["centroid_room"]]
        if "boundary_room" in p and p["boundary_room"]:
            p["boundary_room"] = [
                [float(v) / prev_scale * scale_factor for v in pt]
                for pt in p["boundary_room"]
            ]

    return model


def apply_scale_to_session(
    session_dir: Path,
    reference_type: str,
    known_distance_meters: float,
    pt_a: Optional[List[float]] = None,
    pt_b: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Load room_model.json from session_dir, calibrate scale, and update disk files."""
    room_model_path = session_dir / "p2" / "room_model.json"
    if not room_model_path.exists():
        room_model_path = session_dir / "room_model.json"
    if not room_model_path.exists():
        raise FileNotFoundError(f"room_model.json not found in {session_dir}")

    room_model = json.loads(room_model_path.read_text())
    scaled_model = calibrate_room_model_scale(
        room_model,
        reference_type=reference_type,
        known_distance_meters=known_distance_meters,
        pt_a=pt_a,
        pt_b=pt_b,
    )

    room_model_path.write_text(json.dumps(scaled_model, indent=2))

    # Also update twin.json if present
    twin_path = session_dir / "twin.json"
    if twin_path.exists():
        twin = json.loads(twin_path.read_text())
        twin["scale"] = scaled_model["scale"]
        twin["measurements"] = scaled_model["room"]
        if "room_model" in twin and twin["room_model"]:
            twin["room_model"] = scaled_model
        twin_path.write_text(json.dumps(twin, indent=2))

    return scaled_model
