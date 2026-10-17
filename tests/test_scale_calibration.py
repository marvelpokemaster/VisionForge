import json
import pytest
from pathlib import Path
import tempfile
import shutil

from visionforge.spatial.calibration import calibrate_room_model_scale, apply_scale_to_session


def test_calibrate_room_model_scale_by_width():
    # Synthetic unscaled room: width=8.0, length=12.0
    room_model = {
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": 12.0,
            "width": 8.0,
            "height": 4.0,
            "floor_area": 96.0,
            "bounding_polygon_room": [
                [-6.0, -4.0], [6.0, -4.0], [6.0, 4.0], [-6.0, 4.0]
            ],
        },
        "planes": [
            {
                "id": "plane_000",
                "type": "floor",
                "equation": [0.0, 1.0, 0.0, 0.0],
                "normal": [0.0, 1.0, 0.0],
                "centroid": [0.0, 0.0, 0.0],
                "centroid_room": [0.0, 0.0, 0.0],
                "boundary_room": [[-6.0, 0.0, -4.0], [6.0, 0.0, 4.0]],
                "extent": {"width": 12.0, "height": 8.0},
                "area": 96.0,
            }
        ],
    }

    # User says: "The real width of the room is 4.0 meters"
    scaled = calibrate_room_model_scale(room_model, reference_type="room_width", known_distance_meters=4.0)

    assert scaled["scale"]["metric_available"] is True
    assert scaled["scale"]["scale_factor"] == pytest.approx(0.5)
    assert scaled["room"]["width"] == pytest.approx(4.0)
    assert scaled["room"]["length"] == pytest.approx(6.0)
    assert scaled["room"]["height"] == pytest.approx(2.0)
    assert scaled["room"]["floor_area"] == pytest.approx(24.0)
    # Check polygon was scaled
    assert scaled["room"]["bounding_polygon_room"][0] == pytest.approx([-3.0, -2.0])


def test_calibrate_room_model_scale_by_two_points():
    room_model = {
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": 10.0,
            "width": 5.0,
            "height": 3.0,
            "floor_area": 50.0,
            "bounding_polygon_room": [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]],
        },
        "planes": [],
    }

    # Two points 2 units apart in unscaled model; user says known distance is 1.0m
    pt_a = [0.0, 0.0, 0.0]
    pt_b = [2.0, 0.0, 0.0]
    scaled = calibrate_room_model_scale(
        room_model,
        reference_type="two_points",
        known_distance_meters=1.0,
        pt_a=pt_a,
        pt_b=pt_b,
    )

    assert scaled["scale"]["scale_factor"] == pytest.approx(0.5)
    assert scaled["room"]["length"] == pytest.approx(5.0)
