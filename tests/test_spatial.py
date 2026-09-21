import math
import numpy as np
import pytest

from visionforge.spatial.scene_graph import (
    build_scene_graph,
    _quat_to_rotation_matrix,
    _camera_world_position,
)
from visionforge.spatial.geometry_utils import point_in_polygon_2d
from visionforge.spatial.queries import SpatialQueryEngine


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
    assert point_in_polygon_2d([2, 1.5], square) is True
    assert point_in_polygon_2d([10, 1.5], square) is False
    assert point_in_polygon_2d([-1, 1.5], square) is False


# ---------------------------------------------------------------------------
# Hand-built box room (identity room frame: up=[0,1,0], x=[1,0,0], z=[0,0,1],
# origin=[0,0,0], so reconstruction frame == room frame and every expected
# number can be worked out by hand): floor (4x3, y=0), ceiling (4x3, y=2.5),
# and three walls (west x=0, south z=0, north z=3), each spanning y in [0,2.5].
# ---------------------------------------------------------------------------

def _plane(id_, ptype, normal, d, centroid, boundary, area=1.0, axis_u=None, axis_v=None):
    return {
        "id": id_,
        "type": ptype,
        "equation": [normal[0], normal[1], normal[2], d],
        "normal": normal,
        "centroid": centroid,
        "centroid_room": centroid,  # identity room frame
        "support": 500,
        "extent": {"width": 1.0, "height": 1.0},
        "area": area,
        "boundary": boundary,
        "boundary_room": boundary,
        "in_plane_axes": {"axis_u": axis_u, "axis_v": axis_v} if axis_u is not None else None,
        "ply_path": None
    }


@pytest.fixture
def box_room_model():
    floor = _plane("floor", "floor", [0, 1, 0], 0.0, [2, 0, 1.5],
                    [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    area=12.0, axis_u=[0, 0, -1], axis_v=[1, 0, 0])
    ceiling = _plane("ceiling", "ceiling", [0, 1, 0], -2.5, [2, 2.5, 1.5],
                      [[0, 2.5, 0], [4, 2.5, 0], [4, 2.5, 3], [0, 2.5, 3]],
                      area=12.0, axis_u=[0, 0, -1], axis_v=[1, 0, 0])
    wall_west = _plane("wall_west", "wall", [1, 0, 0], 0.0, [0, 1.25, 1.5],
                        [[0, 0, 0], [0, 0, 3], [0, 2.5, 3], [0, 2.5, 0]],
                        area=7.5, axis_u=[0, 0, 1], axis_v=[0, 1, 0])
    wall_south = _plane("wall_south", "wall", [0, 0, 1], 0.0, [2, 1.25, 0],
                         [[0, 0, 0], [4, 0, 0], [4, 2.5, 0], [0, 2.5, 0]],
                         area=10.0, axis_u=[-1, 0, 0], axis_v=[0, 1, 0])
    wall_north = _plane("wall_north", "wall", [0, 0, 1], -3.0, [2, 1.25, 3],
                         [[0, 0, 3], [4, 0, 3], [4, 2.5, 3], [0, 2.5, 3]],
                         area=8.0, axis_u=[-1, 0, 0], axis_v=[0, 1, 0])

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


# ---------------------------------------------------------------------------
# Task C: SpatialQueryEngine, on the same hand-built box room -- every
# expected number is known ahead of time.
# ---------------------------------------------------------------------------

@pytest.fixture
def floor_only_room_model():
    """No ceiling, no walls -- height must come back None (not 0.0), while
    length/width/floor_area (which only need the floor) stay measurable."""
    floor = _plane("floor", "floor", [0, 1, 0], 0.0, [2, 0, 1.5],
                    [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]],
                    area=12.0, axis_u=[0, 0, -1], axis_v=[1, 0, 0])
    return {
        "coordinate_system": {"up_axis": [0, 1, 0], "horizontal_axes": [[1, 0, 0], [0, 0, 1]], "origin": [0, 0, 0]},
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {"length": 4.0, "width": 3.0, "height": 0.0, "floor_area": 12.0,
                 "bounding_polygon_room": [[0, 0], [4, 0], [4, 3], [0, 3]]},
        "planes": [floor],
        "intersections": []
    }


def test_room_dimensions_measurable(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    length = sqe.get_room_length()
    width = sqe.get_room_width()
    height = sqe.get_room_height()
    area = sqe.get_floor_area()

    assert length == {"value": 4.0, "metric": False, "units": "reconstruction_units"}
    assert width == {"value": 3.0, "metric": False, "units": "reconstruction_units"}
    assert height == {"value": 2.5, "metric": False, "units": "reconstruction_units"}
    assert area == {"value": 12.0, "metric": False, "units": "reconstruction_units"}


def test_room_height_none_without_ceiling_or_walls(floor_only_room_model):
    sg = build_scene_graph(floor_only_room_model)
    sqe = SpatialQueryEngine(sg)

    assert sqe.get_room_height() is None
    # length/width/area only need the floor, so they stay measurable
    assert sqe.get_room_length()["value"] == 4.0
    assert sqe.get_floor_area()["value"] == 12.0


def test_room_dimensions_none_without_floor():
    empty_room_model = {
        "coordinate_system": None,
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {"length": 0.0, "width": 0.0, "height": 0.0, "floor_area": 0.0, "bounding_polygon_room": []},
        "planes": [],
        "intersections": []
    }
    sg = build_scene_graph(empty_room_model)
    sqe = SpatialQueryEngine(sg)

    assert sqe.get_room_length() is None
    assert sqe.get_room_width() is None
    assert sqe.get_room_height() is None
    assert sqe.get_floor_area() is None


def test_wall_area_from_hull_not_height_times_width(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    assert sqe.get_wall_area("wall_west") == {"value": 7.5, "metric": False, "units": "reconstruction_units"}
    assert sqe.get_wall_area("wall_south") == {"value": 10.0, "metric": False, "units": "reconstruction_units"}
    assert sqe.get_wall_area("floor") is None  # not a wall


def test_largest_and_smallest_wall(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    assert sqe.get_largest_wall() == "wall_south"   # area 10.0
    assert sqe.get_smallest_wall() == "wall_west"    # area 7.5


def test_parallel_adjacent_perpendicular_surface_queries(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    assert sqe.get_parallel_surfaces("wall_south") == ["wall_north"]
    assert sqe.get_perpendicular_surfaces("wall_west") == ["wall_south", "wall_north"] or \
           set(sqe.get_perpendicular_surfaces("wall_west")) == {"wall_south", "wall_north", "floor", "ceiling"}
    assert "wall_west" in sqe.get_adjacent_surfaces("floor")


def test_distance_between_surfaces_parallel_uses_plane_offset(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    dist = sqe.distance_between_surfaces("wall_south", "wall_north")
    assert dist == {"value": 3.0, "metric": False, "units": "reconstruction_units"}


def test_distance_between_surfaces_perpendicular_uses_boundary(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    dist = sqe.distance_between_surfaces("floor", "wall_west")
    assert dist["value"] == pytest.approx(0.0, abs=1e-6)


def test_surface_intersection_returns_task_a_segment_or_none(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    inter = sqe.get_surface_intersection("floor", "wall_west")
    assert inter["segment"] == [[0, 0, 0], [0, 0, 3]]

    assert sqe.get_surface_intersection("wall_south", "wall_north") is None


def test_camera_position_last_and_by_index(box_room_model):
    cameras = [
        _camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5]),
        _camera(2, "frame_000002.jpg", [10.0, 1.25, 1.5]),
    ]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    last = sqe.get_camera_position()
    assert last["position"]["value"] == pytest.approx([10.0, 1.25, 1.5])

    first = sqe.get_camera_position(index=0)
    assert first["position"]["value"] == pytest.approx([2.0, 1.25, 1.5])

    assert sqe.get_camera_position(index=5) is None


def test_camera_trajectory_and_length(box_room_model):
    cameras = [
        _camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5]),
        _camera(2, "frame_000002.jpg", [10.0, 1.25, 1.5]),
    ]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    traj = sqe.get_camera_trajectory()
    assert traj["num_cameras"] == 2
    assert traj["path_length"] == {"value": 8.0, "metric": False, "units": "reconstruction_units"}

    length = sqe.get_trajectory_length()
    assert length["value"] == pytest.approx(8.0)


def test_distance_from_camera_to_surface_flags_outside_boundary(box_room_model):
    # Camera well beyond the room's z-extent: its perpendicular foot on
    # wall_west (x=0) falls outside that wall's finite z in [0,3] boundary.
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 10.0])]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    result = sqe.distance_from_camera_to_surface("wall_west")
    assert result["value"] == pytest.approx(2.0, abs=1e-6)
    assert result["within_boundary"] is False


def test_distance_from_camera_to_surface_within_boundary(box_room_model):
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5])]  # room center
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    result = sqe.distance_from_camera_to_surface("floor")
    assert result["value"] == pytest.approx(1.25, abs=1e-6)
    assert result["within_boundary"] is True


def test_distance_from_camera_to_all_surfaces(box_room_model):
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.5])]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    result = sqe.distance_from_camera_to_all_surfaces()
    assert set(result.keys()) == {"floor", "ceiling", "wall_west", "wall_south", "wall_north"}


def test_nearest_wall_to_camera(box_room_model):
    # z=1.0: distance to wall_south (z=0) is 1.0, to wall_north (z=3) is 2.0,
    # to wall_west (x=0) is 2.0 -- wall_south is the unique nearest wall.
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.0])]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    nearest = sqe.get_nearest_wall_to_camera()
    assert nearest["wall_id"] == "wall_south"
    assert nearest["value"] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Question dispatcher: the four example questions, two paraphrases each,
# and one genuinely unsupported question.
# ---------------------------------------------------------------------------

DISPATCH_CASES = [
    ("What is the room height?", "room_height"),
    ("How tall is the room?", "room_height"),
    ("What's the height of the room?", "room_height"),

    ("Which wall is largest?", "largest_wall"),
    ("What is the biggest wall?", "largest_wall"),
    ("Which wall has the most area?", "largest_wall"),

    ("Which walls are parallel?", "parallel_walls"),
    ("What walls are parallel to each other?", "parallel_walls"),
    ("List parallel walls.", "parallel_walls"),

    ("How far is the camera from the nearest wall?", "camera_nearest_wall"),
    ("What is the distance from the camera to the closest wall?", "camera_nearest_wall"),
    ("How close is the camera to the nearest wall?", "camera_nearest_wall"),
]


@pytest.mark.parametrize("question,expected_type", DISPATCH_CASES)
def test_dispatcher_recognizes_question_and_paraphrases(box_room_model, question, expected_type):
    cameras = [_camera(1, "frame_000001.jpg", [2.0, 1.25, 1.0])]
    sg = build_scene_graph(box_room_model, cameras=cameras)
    sqe = SpatialQueryEngine(sg)

    result = sqe.answer_question(question)
    assert result["supported"] is True
    assert result["question_type"] == expected_type
    assert result["answer"] is not None


def test_dispatcher_unsupported_question_lists_supported_types(box_room_model):
    sg = build_scene_graph(box_room_model)
    sqe = SpatialQueryEngine(sg)

    result = sqe.answer_question("What color is the floor?")
    assert result["supported"] is False
    assert result["answer"] is None
    assert len(result["supported_question_types"]) == 4
    assert "room height" in result["supported_question_types"][0].lower()
