import numpy as np
import pytest

from visionforge.spatial.clearance import (
    FURNITURE_CATALOG,
    get_oriented_box_corners,
    point_in_polygon_2d,
    polygons_intersect_2d,
    box_inside_polygon_2d,
    FloorClearanceEngine,
    PlacementItem,
)


def _make_box_room_model(length=6.0, width=4.0, height=2.8, scale_factor=1.0, metric_available=True):
    """Create a synthetic room_model with floor at Y=0, spanning [-length/2, length/2] in X
    and [-width/2, width/2] in Z."""
    half_l = length / 2.0
    half_w = width / 2.0
    bounding_polygon = [
        [-half_l, -half_w],
        [half_l, -half_w],
        [half_l, half_w],
        [-half_l, half_w],
    ]
    return {
        "coordinate_system": {
            "up_axis": [0.0, 1.0, 0.0],
            "origin": [0.0, 0.0, 0.0],
        },
        "scale": {
            "metric_available": metric_available,
            "scale_factor": scale_factor,
        },
        "room": {
            "length": float(length),
            "width": float(width),
            "height": float(height),
            "floor_area": float(length * width),
            "bounding_polygon_room": bounding_polygon,
        },
        "planes": [
            {
                "id": "plane_floor",
                "type": "floor",
                "equation": [0.0, 1.0, 0.0, 0.0],
                "normal": [0.0, 1.0, 0.0],
                "support": 1000,
            }
        ],
    }


def test_furniture_catalog_validity():
    """Ensure catalog contains standard architectural items with valid positive dimensions."""
    assert len(FURNITURE_CATALOG) >= 6
    for item_id, item in FURNITURE_CATALOG.items():
        assert item["length"] > 0
        assert item["width"] > 0
        assert item["height"] > 0
        assert "name" in item
        assert "category" in item


def test_oriented_box_corners():
    """Corners of a 2x1 rectangle at origin aligned with axes."""
    corners = get_oriented_box_corners(0.0, 0.0, length=2.0, width=1.0, angle_deg=0.0)
    assert len(corners) == 4
    # Expected: [-1, -0.5], [1, -0.5], [1, 0.5], [-1, 0.5]
    np.testing.assert_allclose(corners[0], [-1.0, -0.5])
    np.testing.assert_allclose(corners[1], [1.0, -0.5])
    np.testing.assert_allclose(corners[2], [1.0, 0.5])
    np.testing.assert_allclose(corners[3], [-1.0, 0.5])

    # Rotated 90 degrees: length along Z, width along X
    corners_90 = get_oriented_box_corners(0.0, 0.0, length=2.0, width=1.0, angle_deg=90.0)
    np.testing.assert_allclose(corners_90[0], [0.5, -1.0], atol=1e-7)
    np.testing.assert_allclose(corners_90[1], [0.5, 1.0], atol=1e-7)
    np.testing.assert_allclose(corners_90[2], [-0.5, 1.0], atol=1e-7)
    np.testing.assert_allclose(corners_90[3], [-0.5, -1.0], atol=1e-7)


def test_point_in_polygon_2d():
    poly = [[-2.0, -2.0], [2.0, -2.0], [2.0, 2.0], [-2.0, 2.0]]
    assert point_in_polygon_2d([0.0, 0.0], poly) is True
    assert point_in_polygon_2d([1.9, 1.9], poly) is True
    assert point_in_polygon_2d([2.5, 0.0], poly) is False
    assert point_in_polygon_2d([-3.0, 5.0], poly) is False


def test_polygons_intersect_sat():
    # Two overlapping squares
    sq1 = get_oriented_box_corners(0.0, 0.0, 2.0, 2.0, 0.0)
    sq2 = get_oriented_box_corners(1.0, 1.0, 2.0, 2.0, 0.0)
    assert polygons_intersect_2d(sq1, sq2) is True

    # Two disjoint squares
    sq3 = get_oriented_box_corners(5.0, 5.0, 2.0, 2.0, 0.0)
    assert polygons_intersect_2d(sq1, sq3) is False


def test_box_inside_polygon_2d():
    room_poly = [[-3.0, -2.0], [3.0, -2.0], [3.0, 2.0], [-3.0, 2.0]]
    # Bed centered inside room
    bed_in = get_oriented_box_corners(0.0, 0.0, 2.0, 1.0, 0.0)
    assert box_inside_polygon_2d(bed_in, room_poly) is True

    # Bed sticking out through wall (x=2.5, length=2.0 -> right edge at 3.5 > 3.0)
    bed_out = get_oriented_box_corners(2.5, 0.0, 2.0, 1.0, 0.0)
    assert box_inside_polygon_2d(bed_out, room_poly) is False


def test_clearance_engine_validate_placement():
    room_model = _make_box_room_model(length=6.0, width=4.0)
    engine = FloorClearanceEngine(room_model)

    # Valid placement: Queen bed at center
    res = engine.validate_placement(
        furniture_id="bed_queen",
        center_x=0.0,
        center_z=0.0,
        angle_deg=0.0,
    )
    assert res["valid"] is True
    assert "corners" in res
    assert res["reason"] == "Clear"

    # Invalid placement: Bed sticking past x=3.0 wall
    res_bad = engine.validate_placement(
        furniture_id="bed_queen",
        center_x=2.5,
        center_z=0.0,
        angle_deg=0.0,
    )
    assert res_bad["valid"] is False
    assert "boundary" in res_bad["reason"].lower()

    # Collision with existing placed item
    placed_items = [
        PlacementItem(id="item_1", furniture_id="bed_queen", center_x=0.0, center_z=0.0, angle_deg=0.0)
    ]
    res_collide = engine.validate_placement(
        furniture_id="work_desk",
        center_x=0.5,
        center_z=0.5,
        angle_deg=0.0,
        placed_items=placed_items,
    )
    assert res_collide["valid"] is False
    assert "collides" in res_collide["reason"].lower()

    # Non-colliding adjacent placement
    res_adj = engine.validate_placement(
        furniture_id="nightstand",
        center_x=-2.0,
        center_z=-1.2,
        angle_deg=0.0,
        placed_items=placed_items,
    )
    assert res_adj["valid"] is True


def test_clearance_engine_auto_pack():
    # 6m x 4m room = 24m²
    room_model = _make_box_room_model(length=6.0, width=4.0)
    engine = FloorClearanceEngine(room_model)

    # Single bed: 2.0m x 1.0m (2.0 m²)
    pack = engine.auto_pack(furniture_id="bed_single", spacing=0.2)
    assert pack["max_count"] >= 4
    assert pack["occupied_area_m2"] > 0
    assert pack["usable_free_area_m2"] <= pack["floor_area_m2"]
    assert len(pack["placements"]) == pack["max_count"]


def test_furniture_flush_boundary_contact():
    """Verify that furniture placed flush against any room boundary wall is valid."""
    # Room [-3, 3] in X, [-2, 2] in Z
    room_model = _make_box_room_model(length=6.0, width=4.0)
    engine = FloorClearanceEngine(room_model)

    # Work desk: 1.4m length (X) x 0.7m width (Z)
    # Half dimensions: length=0.7, width=0.35

    # 1. Flush against left wall (x = -3.0): center_x = -3.0 + 0.7 = -2.3
    res_left = engine.validate_placement("work_desk", center_x=-2.3, center_z=0.0, angle_deg=0.0)
    assert res_left["valid"] is True, f"Failed flush left: {res_left.get('reason')}"

    # 2. Flush against right wall (x = 3.0): center_x = 3.0 - 0.7 = 2.3
    res_right = engine.validate_placement("work_desk", center_x=2.3, center_z=0.0, angle_deg=0.0)
    assert res_right["valid"] is True, f"Failed flush right: {res_right.get('reason')}"

    # 3. Flush against bottom wall (z = -2.0): center_z = -2.0 + 0.35 = -1.65
    res_bottom = engine.validate_placement("work_desk", center_x=0.0, center_z=-1.65, angle_deg=0.0)
    assert res_bottom["valid"] is True, f"Failed flush bottom: {res_bottom.get('reason')}"

    # 4. Flush against top wall (z = 2.0): center_z = 2.0 - 0.35 = 1.65
    res_top = engine.validate_placement("work_desk", center_x=0.0, center_z=1.65, angle_deg=0.0)
    assert res_top["valid"] is True, f"Failed flush top: {res_top.get('reason')}"

    # 5. Over-the-wall protrusion (1cm beyond left wall): center_x = -2.31
    res_protrude = engine.validate_placement("work_desk", center_x=-2.31, center_z=0.0, angle_deg=0.0)
    assert res_protrude["valid"] is False


def test_furniture_rotated_and_concave_room():
    """Verify clearance for rotated furniture and L-shaped concave rooms."""
    # L-shaped room: 4x4 with top-right 2x2 corner missing
    # Vertices: [0,0], [4,0], [4,2], [2,2], [2,4], [0,4]
    l_poly = [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [2.0, 2.0], [2.0, 4.0], [0.0, 4.0]]
    room_model = {
        "coordinate_system": {"up_axis": [0.0, 1.0, 0.0]},
        "scale": {"metric_available": True, "scale_factor": 1.0},
        "room": {
            "length": 4.0,
            "width": 4.0,
            "height": 2.5,
            "floor_area": 12.0,
            "bounding_polygon_room": l_poly,
        },
        "planes": [],
    }
    engine = FloorClearanceEngine(room_model)

    # 1. Rotated 45 degrees safely inside bottom wing: center (1.0, 1.0)
    res_rot = engine.validate_placement("work_desk", center_x=1.0, center_z=1.0, angle_deg=45.0)
    assert res_rot["valid"] is True

    # 2. Placed across the missing L-corner (bridging over the cutout): center (2.0, 2.0)
    res_bridge = engine.validate_placement("bed_single", center_x=2.0, center_z=2.0, angle_deg=45.0)
    assert res_bridge["valid"] is False
