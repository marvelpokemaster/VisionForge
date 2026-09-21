import math
import numpy as np
import pytest

from visionforge.spatial.scene_graph import (
    build_scene_graph,
    _quat_to_rotation_matrix,
    _camera_world_position,
    _point_in_polygon_2d,
)


# ---------------------------------------------------------------------------
# Quaternion -> world position: hand-built poses with independently known
# answers, not just round-trip self-consistency.
# ---------------------------------------------------------------------------

def test_quat_to_rotation_matrix_known_90deg_about_z():
    # +90 degree rotation about Z: q = [0, 0, sin(45deg), cos(45deg)]
    s = math.sin(math.radians(45))
    c = math.cos(math.radians(45))
    R = _quat_to_rotation_matrix(0.0, 0.0, s, c)

    expected = np.array([
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0]
    ])
    np.testing.assert_allclose(R, expected, atol=1e-9)

    # sanity: rotating the X axis by +90 deg about Z lands on +Y
    np.testing.assert_allclose(R @ np.array([1.0, 0.0, 0.0]), [0.0, 1.0, 0.0], atol=1e-9)


def test_camera_world_position_identity_rotation():
    # R = I, camera center C = (1, 2, 3) -> t = -R @ C = -C
    C = np.array([1.0, 2.0, 3.0])
    t = (-C).tolist()
    pos = _camera_world_position([0.0, 0.0, 0.0, 1.0], t)
    np.testing.assert_allclose(pos, C, atol=1e-9)


def test_camera_world_position_known_rotated_pose():
    # +90 deg about Z, camera center C = (2, 0, 0).
    # p_cam = R @ (p_world - C) => t = -R @ C.
    s = math.sin(math.radians(45))
    c = math.cos(math.radians(45))
    R = _quat_to_rotation_matrix(0.0, 0.0, s, c)
    C = np.array([2.0, 0.0, 0.0])
    t = (-R @ C).tolist()

    pos = _camera_world_position([0.0, 0.0, s, c], t)
    np.testing.assert_allclose(pos, C, atol=1e-9)


def test_point_in_polygon_2d_known_square():
    square = [[0, 0], [4, 0], [4, 3], [0, 3]]
    assert _point_in_polygon_2d([2, 1.5], square) is True
    assert _point_in_polygon_2d([10, 1.5], square) is False
    assert _point_in_polygon_2d([-1, 1.5], square) is False


# ---------------------------------------------------------------------------
# Hand-built box room (identity room frame: up=[0,1,0], x=[1,0,0], z=[0,0,1],
# origin=[0,0,0], so reconstruction frame == room frame and every expected
# number can be worked out by hand): floor (4x3, y=0), ceiling (4x3, y=2.5),
# and three walls (west x=0, south z=0, north z=3), each spanning y in [0,2.5].
# ---------------------------------------------------------------------------

def _plane(id_, ptype, normal, d, centroid, boundary):
    return {
        "id": id_,
        "type": ptype,
        "equation": [normal[0], normal[1], normal[2], d],
        "normal": normal,
        "centroid": centroid,
        "centroid_room": centroid,  # identity room frame
        "support": 500,
        "extent": {"width": 1.0, "height": 1.0},
        "area": 1.0,
        "boundary": boundary,
        "boundary_room": boundary,
        "ply_path": None
    }


@pytest.fixture
def box_room_model():
    floor = _plane("floor", "floor", [0, 1, 0], 0.0, [2, 0, 1.5],
                    [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]])
    ceiling = _plane("ceiling", "ceiling", [0, 1, 0], -2.5, [2, 2.5, 1.5],
                      [[0, 2.5, 0], [4, 2.5, 0], [4, 2.5, 3], [0, 2.5, 3]])
    wall_west = _plane("wall_west", "wall", [1, 0, 0], 0.0, [0, 1.25, 1.5],
                        [[0, 0, 0], [0, 0, 3], [0, 2.5, 3], [0, 2.5, 0]])
    wall_south = _plane("wall_south", "wall", [0, 0, 1], 0.0, [2, 1.25, 0],
                         [[0, 0, 0], [4, 0, 0], [4, 2.5, 0], [0, 2.5, 0]])
    wall_north = _plane("wall_north", "wall", [0, 0, 1], -3.0, [2, 1.25, 3],
                         [[0, 0, 3], [4, 0, 3], [4, 2.5, 3], [0, 2.5, 3]])

    planes = [floor, ceiling, wall_west, wall_south, wall_north]

    intersections = [
        {
            "plane_a": "floor", "plane_b": "wall_west",
            "point": [0, 0, 0], "direction": [0, 0, 1],
            "segment": [[0, 0, 0], [0, 0, 3]],
            "point_room": [0, 0, 0], "segment_room": [[0, 0, 0], [0, 0, 3]]
        }
    ]

    return {
        "coordinate_system": {
            "up_axis": [0, 1, 0],
            "horizontal_axes": [[1, 0, 0], [0, 0, 1]],
            "origin": [0, 0, 0]
        },
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": 4.0, "width": 3.0, "height": 2.5, "floor_area": 12.0,
            "bounding_polygon_room": [[0, 0], [4, 0], [4, 3], [0, 3]]
        },
        "planes": planes,
        "intersections": intersections
    }


def _edges(sg, relation, source=None, target=None):
    out = [e for e in sg["edges"] if e["relation"] == relation]
    if source is not None:
        out = [e for e in out if e["source"] == source]
    if target is not None:
        out = [e for e in out if e["target"] == target]
    return out


def test_contains(box_room_model):
    sg = build_scene_graph(box_room_model)
    contains = _edges(sg, "contains", source="room_001")
    targets = {e["target"] for e in contains}
    assert targets == {"floor", "ceiling", "wall_west", "wall_south", "wall_north"}


def test_parallel_to_with_angle(box_room_model):
    sg = build_scene_graph(box_room_model)
    parallel = _edges(sg, "parallel_to")
    pairs = {frozenset((e["source"], e["target"])) for e in parallel}
    assert frozenset(("floor", "ceiling")) in pairs
    assert frozenset(("wall_south", "wall_north")) in pairs
    for e in parallel:
        assert e["angle_deg"] == pytest.approx(0.0, abs=1e-6)


def test_perpendicular_to_with_angle(box_room_model):
    sg = build_scene_graph(box_room_model)
    perp = _edges(sg, "perpendicular_to")
    pairs = {frozenset((e["source"], e["target"])) for e in perp}
    assert frozenset(("floor", "wall_west")) in pairs
    assert frozenset(("floor", "wall_south")) in pairs
    assert frozenset(("wall_west", "wall_south")) in pairs
    # not perpendicular
    assert frozenset(("floor", "ceiling")) not in pairs
    for e in perp:
        assert e["angle_deg"] == pytest.approx(90.0, abs=1e-6)


def test_adjacent_to_uses_boundary_distance_not_centroid(box_room_model):
    sg = build_scene_graph(box_room_model)
    adjacent = _edges(sg, "adjacent_to")
    pairs = {frozenset((e["source"], e["target"])) for e in adjacent}

    # floor touches every wall along a shared edge -> distance 0, adjacent
    assert frozenset(("floor", "wall_west")) in pairs
    assert frozenset(("floor", "wall_south")) in pairs
    assert frozenset(("floor", "wall_north")) in pairs
    assert frozenset(("ceiling", "wall_west")) in pairs

    for e in adjacent:
        assert e["distance"] == pytest.approx(0.0, abs=1e-6)


def test_intersects_reuses_task_a_segment_unmodified(box_room_model):
    sg = build_scene_graph(box_room_model)
    inter = _edges(sg, "intersects", source="floor", target="wall_west")
    assert len(inter) == 1
    assert inter[0]["segment"] == [[0, 0, 0], [0, 0, 3]]
    assert inter[0]["point"] == [0, 0, 0]


def test_above_below_between_horizontal_surfaces(box_room_model):
    sg = build_scene_graph(box_room_model)
    above = _edges(sg, "above", source="ceiling", target="floor")
    below = _edges(sg, "below", source="floor", target="ceiling")
    assert len(above) == 1
    assert above[0]["height_difference"] == pytest.approx(2.5, abs=1e-6)
    assert len(below) == 1
    assert below[0]["height_difference"] == pytest.approx(2.5, abs=1e-6)


def _camera(cam_id, name, world_center):
    # identity rotation: t = -C
    C = np.array(world_center, dtype=float)
    return {
        "id": cam_id, "name": name,
        "rotation_quat": [0.0, 0.0, 0.0, 1.0],
        "translation": (-C).tolist(),
        "camera_model": "SIMPLE_RADIAL",
        "camera_params": [900.0, 400.0, 300.0, 0.0]
    }


def test_camera_inside_room(box_room_model):
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5])]  # room center
    sg = build_scene_graph(box_room_model, cameras=cameras)

    cam_node = next(n for n in sg["nodes"] if n["type"] == "camera")
    np.testing.assert_allclose(cam_node["properties"]["position"], [2.0, 1.25, 1.5], atol=1e-6)

    inside_edges = _edges(sg, "inside", source="camera_001")
    assert len(inside_edges) == 1
    assert inside_edges[0]["inside"] is True
    assert inside_edges[0]["distance_to_boundary"] == pytest.approx(0.0, abs=1e-6)


def test_camera_outside_room_is_reported_not_dropped(box_room_model):
    cameras = [_camera(2, "frame_000002.jpg", [10.0, 1.25, 1.5])]  # well outside in x
    sg = build_scene_graph(box_room_model, cameras=cameras)

    inside_edges = _edges(sg, "inside", source="camera_002")
    assert len(inside_edges) == 1  # must still be reported, not silently dropped
    assert inside_edges[0]["inside"] is False
    assert inside_edges[0]["distance_to_boundary"] == pytest.approx(6.0, abs=1e-6)


def test_camera_above_floor_and_below_ceiling(box_room_model):
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5])]
    sg = build_scene_graph(box_room_model, cameras=cameras)

    above_floor = _edges(sg, "above", source="camera_001", target="floor")
    below_ceiling = _edges(sg, "below", source="camera_001", target="ceiling")
    assert len(above_floor) == 1
    assert above_floor[0]["height_difference"] == pytest.approx(1.25, abs=1e-6)
    assert len(below_ceiling) == 1
    assert below_ceiling[0]["height_difference"] == pytest.approx(1.25, abs=1e-6)


def test_trajectory_node_and_path_length(box_room_model):
    cameras = [
        _camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5]),
        _camera(2, "frame_000002.jpg", [10.0, 1.25, 1.5]),
    ]
    sg = build_scene_graph(box_room_model, cameras=cameras)

    traj = next(n for n in sg["nodes"] if n["type"] == "trajectory")
    assert traj["properties"]["num_cameras"] == 2
    assert traj["properties"]["path_length"] == pytest.approx(8.0, abs=1e-6)
    # ordered by frame name, not insertion order
    assert traj["properties"]["positions"][0] == pytest.approx([2.0, 1.25, 1.5])
    assert traj["properties"]["positions"][1] == pytest.approx([10.0, 1.25, 1.5])

    contains_traj = _edges(sg, "contains", source="room_001", target="trajectory_001")
    assert len(contains_traj) == 1
