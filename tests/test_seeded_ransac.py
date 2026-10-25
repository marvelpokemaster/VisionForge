import numpy as np
import open3d as o3d
import pytest

from visionforge.geometry.plane_fitting import _numpy_segment_plane, extract_dominant_planes


def test_numpy_segment_plane_horizontal_floor():
    """Verify that _numpy_segment_plane accurately identifies a horizontal plane."""
    rng = np.random.default_rng(42)
    # 200 points on z=0 with slight noise
    x = rng.uniform(-5, 5, 200)
    y = rng.uniform(-5, 5, 200)
    z = rng.normal(0, 0.005, 200)
    floor_pts = np.column_stack([x, y, z])

    # 50 outlier points scattered in space
    outliers = rng.uniform(-5, 5, size=(50, 3))
    outliers[:, 2] += 2.0  # elevate above floor

    all_pts = np.vstack([floor_pts, outliers])

    model, inliers = _numpy_segment_plane(
        all_pts,
        distance_threshold=0.03,
        ransac_n=3,
        num_iterations=200,
        seed=100,
    )

    a, b, c, d = model
    normal = np.array([a, b, c])
    # Normal must be aligned with world Z axis [0, 0, 1]
    assert abs(abs(normal[2]) - 1.0) < 0.01
    assert abs(normal[0]) < 0.02 and abs(normal[1]) < 0.02
    # Offset d must be close to 0
    assert abs(d) < 0.02
    # Should capture almost all 200 floor points
    assert len(inliers) >= 195


def test_numpy_segment_plane_is_strictly_deterministic():
    """Verify that calling _numpy_segment_plane with the same seed yields bit-identical outputs."""
    rng = np.random.default_rng(99)
    pts = rng.uniform(-3, 3, size=(300, 3))

    model1, inliers1 = _numpy_segment_plane(pts, distance_threshold=0.05, num_iterations=100, seed=7)
    model2, inliers2 = _numpy_segment_plane(pts, distance_threshold=0.05, num_iterations=100, seed=7)

    assert np.array_equal(model1, model2)
    assert inliers1 == inliers2


def test_extract_dominant_planes_seeded_reproducibility():
    """Verify that extract_dominant_planes with a seed returns identical planes across multiple calls."""
    rng = np.random.default_rng(123)
    # Generate points on two planes: z=0 and x=2
    plane1 = np.column_stack([rng.uniform(0, 5, 150), rng.uniform(0, 5, 150), np.zeros(150)])
    plane2 = np.column_stack([np.full(150, 2.0), rng.uniform(0, 5, 150), rng.uniform(0, 3, 150)])
    all_pts = np.vstack([plane1, plane2])

    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(all_pts)

    run1 = extract_dominant_planes(pcd, distance_threshold=0.05, min_ratio=0.1, seed=42)
    run2 = extract_dominant_planes(pcd, distance_threshold=0.05, min_ratio=0.1, seed=42)

    assert len(run1) == len(run2)
    for p1, p2 in zip(run1, run2):
        assert p1["id"] == p2["id"]
        assert np.allclose(p1["equation"], p2["equation"], atol=1e-7)
        assert np.allclose(p1["normal"], p2["normal"], atol=1e-7)
        assert p1["inliers"] == p2["inliers"]
        assert np.array_equal(p1["inlier_indices"], p2["inlier_indices"])

