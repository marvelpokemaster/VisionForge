import numpy as np
import open3d as o3d

from visionforge.geometry.plane_fitting import classify_planes


def _plane(plane_id, points, normal, d, total_points):
    points = np.asarray(points, dtype=float)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    normal = np.asarray(normal, dtype=float)
    normal = normal / np.linalg.norm(normal)

    return {
        "id": plane_id,
        "equation": [float(normal[0]), float(normal[1]), float(normal[2]), float(d)],
        "normal": normal.tolist(),
        "inliers": int(len(points)),
        "inlier_ratio": float(len(points) / total_points),
        "centroid": points.mean(axis=0).tolist(),
        "cloud": cloud,
    }


def _box_room(
    floor_count=1000,
    ceiling_count=1000,
    wall_counts=(500, 500, 500, 500),
    rotation=None,
):
    rng = np.random.default_rng(1234)

    room = []
    planes = []

    # z=0 floor
    floor_pts = np.column_stack(
        [
            rng.uniform(0, 5, floor_count),
            rng.uniform(0, 5, floor_count),
            np.zeros(floor_count),
        ]
    )
    room.append(floor_pts)

    # z=2.5 ceiling
    ceiling_pts = np.column_stack(
        [
            rng.uniform(0, 5, ceiling_count),
            rng.uniform(0, 5, ceiling_count),
            np.full(ceiling_count, 2.5),
        ]
    )
    room.append(ceiling_pts)

    wall_specs = [
        ((1, 0, 0), 0.0, lambda n: np.column_stack([np.zeros(n), rng.uniform(0, 5, n), rng.uniform(0, 2.5, n)])),
        ((1, 0, 0), -5.0, lambda n: np.column_stack([np.full(n, 5.0), rng.uniform(0, 5, n), rng.uniform(0, 2.5, n)])),
        ((0, 1, 0), 0.0, lambda n: np.column_stack([rng.uniform(0, 5, n), np.zeros(n), rng.uniform(0, 2.5, n)])),
        ((0, 1, 0), -5.0, lambda n: np.column_stack([rng.uniform(0, 5, n), np.full(n, 5.0), rng.uniform(0, 2.5, n)])),
    ]

    for count, (normal, d, make_points) in zip(wall_counts, wall_specs):
        pts = make_points(count)
        room.append(pts)

    all_points = np.vstack(room)
    total_points = len(all_points)

    if rotation is not None:
        all_points = all_points @ rotation.T

    # Build exact plane dicts from the transformed geometry.
    floor_pts = room[0]
    ceiling_pts = room[1]

    plane_specs = [
        ("plane_000", floor_pts, np.array([0, 0, 1.0]), 0.0),
        ("plane_001", ceiling_pts, np.array([0, 0, 1.0]), -2.5),
    ]

    for i, (count, (normal, d, _)) in enumerate(zip(wall_counts, wall_specs)):
        pts = room[i + 2]
        plane_specs.append((f"plane_{i + 2:03d}", pts, np.asarray(normal, dtype=float), d))

    if rotation is not None:
        for idx in range(len(plane_specs)):
            plane_id, pts, normal, d = plane_specs[idx]
            rotated_pts = pts @ rotation.T
            rotated_normal = normal @ rotation.T
            # Recompute d from the transformed centroid/normal.
            rotated_normal = rotated_normal / np.linalg.norm(rotated_normal)
            rotated_d = -float(np.dot(rotated_normal, rotated_pts[0]))
            plane_specs[idx] = (plane_id, rotated_pts, rotated_normal, rotated_d)

    planes = [
        _plane(plane_id, pts, normal, d, total_points)
        for plane_id, pts, normal, d in plane_specs
    ]

    if rotation is not None:
        all_points = np.vstack([np.asarray(p["cloud"].points) for p in planes])

    return planes, all_points


def test_architectural_classifier_box_room():
    planes, all_points = _box_room()

    result = classify_planes(planes, all_points)
    labels = {p["id"]: p["classification"] for p in result["planes"]}

    assert labels["plane_000"] == "floor"
    assert labels["plane_001"] == "ceiling"

    wall_ids = {"plane_002", "plane_003", "plane_004", "plane_005"}
    assert all(labels[pid] == "wall" for pid in wall_ids)

    assert result["coordinate_system"]["up_source"]
    assert result["coordinate_system"]["up_sources"]["camera_gravity"]["confidence"] == 0.0


def test_architectural_classifier_wall_dominant():
    # Make one wall much larger than the floor and ceiling.
    planes, all_points = _box_room(
        floor_count=500,
        ceiling_count=500,
        wall_counts=(5000, 300, 300, 300),
    )

    result = classify_planes(planes, all_points)
    by_id = {p["id"]: p for p in result["planes"]}

    assert by_id["plane_000"]["classification"] == "floor"
    assert by_id["plane_001"]["classification"] == "ceiling"
    assert by_id["plane_002"]["classification"] == "wall"


def test_architectural_classifier_no_floor_does_not_fabricate_one():
    rng = np.random.default_rng(77)

    ceiling = np.column_stack(
        [
            rng.uniform(0, 5, 1000),
            rng.uniform(0, 5, 1000),
            np.full(1000, 2.5),
        ]
    )
    wall_a = np.column_stack(
        [
            np.zeros(800),
            rng.uniform(0, 5, 800),
            rng.uniform(0, 2.5, 800),
        ]
    )
    wall_b = np.column_stack(
        [
            np.full(800, 5.0),
            rng.uniform(0, 5, 800),
            rng.uniform(0, 2.5, 800),
        ]
    )

    all_points = np.vstack([ceiling, wall_a, wall_b])
    planes = [
        _plane("plane_000", ceiling, (0, 0, 1), -2.5, len(all_points)),
        _plane("plane_001", wall_a, (1, 0, 0), 0.0, len(all_points)),
        _plane("plane_002", wall_b, (1, 0, 0), -5.0, len(all_points)),
    ]

    result = classify_planes(planes, all_points)
    labels = [p["classification"] for p in result["planes"]]

    assert "floor" not in labels


def test_architectural_classifier_rotated_room_is_label_invariant():
    # Random but deterministic 3D rotation.
    rng = np.random.default_rng(99)
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    angle = 0.73

    K = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    R = (
        np.eye(3)
        + np.sin(angle) * K
        + (1.0 - np.cos(angle)) * (K @ K)
    )

    base_planes, base_points = _box_room()
    rotated_planes, rotated_points = _box_room(rotation=R)

    base_result = classify_planes(base_planes, base_points)
    rotated_result = classify_planes(rotated_planes, rotated_points)

    base_by_geom = sorted(
        (p["classification"] for p in base_result["planes"])
    )
    rotated_by_geom = sorted(
        (p["classification"] for p in rotated_result["planes"])
    )

    assert base_by_geom == rotated_by_geom
