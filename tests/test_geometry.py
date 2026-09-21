import pytest
import numpy as np
import open3d as o3d
from pathlib import Path

from visionforge.geometry.point_cloud import process_point_cloud
from visionforge.geometry.plane_fitting import extract_dominant_planes, classify_planes, merge_coplanar_planes
from visionforge.geometry.room_model import align_and_measure_room


def _make_plane_dict(plane_id, points, normal, d, total_points):
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)
    return {
        "id": plane_id,
        "equation": [normal[0], normal[1], normal[2], d],
        "normal": list(normal),
        "inliers": len(points),
        "inlier_ratio": len(points) / total_points,
        "centroid": points.mean(axis=0).tolist(),
        "cloud": pcd,
    }

@pytest.fixture
def synthetic_room_pcd(tmp_path):
    # Create a synthetic room:
    # Floor: z=0, 5x5
    # Ceiling: z=2.5, 5x5
    # Wall 1: x=0, 5x2.5
    # Wall 2: y=0, 5x2.5
    
    points = []
    
    # Floor (z=0)
    for _ in range(2000):
        points.append([np.random.uniform(0, 5), np.random.uniform(0, 5), 0.0])
        
    # Ceiling (z=2.5)
    for _ in range(2000):
        points.append([np.random.uniform(0, 5), np.random.uniform(0, 5), 2.5])
        
    # Wall 1 (x=0)
    for _ in range(1000):
        points.append([0.0, np.random.uniform(0, 5), np.random.uniform(0, 2.5)])
        
    # Wall 2 (y=0)
    for _ in range(1000):
        points.append([np.random.uniform(0, 5), 0.0, np.random.uniform(0, 2.5)])
        
    # Add some noise
    pts = np.array(points)
    pts += np.random.normal(0, 0.01, pts.shape)
    
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    
    pcd_path = tmp_path / "synthetic_room.ply"
    o3d.io.write_point_cloud(str(pcd_path), pcd)
    
    return pcd_path

def test_geometry_pipeline(synthetic_room_pcd, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    # Stage 1: Load and clean
    pcd_clean, stats = process_point_cloud(synthetic_room_pcd, output_dir, voxel_size=0.1)
    
    assert stats["raw_points"] == 6000
    assert stats["cleaned_points"] > 0
    assert (output_dir / "pointcloud" / "cleaned.ply").exists()
    
    all_points = np.asarray(pcd_clean.points)
    
    # Stage 2: Plane extraction
    planes = extract_dominant_planes(pcd_clean, distance_threshold=0.1, min_ratio=0.1, max_planes=5)
    
    # Should find at least 4 planes (floor, ceiling, wall1, wall2)
    assert len(planes) >= 4
    
    # Stage 3: Classification
    planes_data = classify_planes(planes, all_points)
    
    classifications = [p["classification"] for p in planes_data["planes"]]
    assert "floor" in classifications
    assert "ceiling" in classifications
    assert "wall" in classifications
    
    # Stage 4: Room Model
    # supply a reference distance (e.g. 5 units in reconstruction = 5 meters)
    model = align_and_measure_room(planes_data, ref_distance=5.0, rec_distance=5.0)
    
    assert model["scale"]["metric_available"] is True
    assert model["scale"]["scale_factor"] == 1.0
    
    # Height should be approx 2.5
    assert 2.0 < model["room"]["height"] < 3.0
    
    # Area should be approx 25
    assert 20.0 < model["room"]["floor_area"] < 30.0


def test_merge_coplanar_planes_merges_split_wall():
    rng = np.random.default_rng(42)

    # Two segments of the same physical surface (same normal, offsets 0.001 apart)
    # -- the kind of split RANSAC produces when a real plane gets segmented twice.
    pts_a = np.column_stack([
        rng.uniform(0, 2, 50), rng.uniform(0, 2, 50), np.zeros(50)
    ])
    pts_b = np.column_stack([
        rng.uniform(2, 4, 50), rng.uniform(0, 2, 50), np.full(50, 0.001)
    ])
    # A genuinely different, perpendicular plane that must NOT be merged.
    pts_c = np.column_stack([
        np.zeros(30), rng.uniform(0, 2, 30), rng.uniform(0, 2, 30)
    ])

    plane_a = _make_plane_dict("plane_000", pts_a, (0, 0, 1), 0.0, 130)
    plane_b = _make_plane_dict("plane_001", pts_b, (0, 0, 1), -0.001, 130)
    plane_c = _make_plane_dict("plane_002", pts_c, (1, 0, 0), 0.0, 130)

    merged = merge_coplanar_planes([plane_a, plane_b, plane_c], distance_threshold=0.01)

    assert len(merged) == 2
    by_inliers = {p["inliers"]: p for p in merged}

    assert 100 in by_inliers  # a + b merged
    assert 30 in by_inliers   # c untouched

    ab = by_inliers[100]
    expected_centroid = np.vstack([pts_a, pts_b]).mean(axis=0)
    np.testing.assert_allclose(ab["centroid"], expected_centroid, atol=1e-6)
    assert len(np.asarray(ab["cloud"].points)) == 100

    c = by_inliers[30]
    assert len(np.asarray(c["cloud"].points)) == 30


def test_merge_coplanar_planes_keeps_distinct_parallel_planes_separate():
    rng = np.random.default_rng(7)

    # Floor and ceiling: same normal, but offset far beyond the merge tolerance.
    pts_floor = np.column_stack([
        rng.uniform(0, 2, 40), rng.uniform(0, 2, 40), np.zeros(40)
    ])
    pts_ceiling = np.column_stack([
        rng.uniform(0, 2, 40), rng.uniform(0, 2, 40), np.full(40, 2.5)
    ])

    floor = _make_plane_dict("plane_000", pts_floor, (0, 0, 1), 0.0, 80)
    ceiling = _make_plane_dict("plane_001", pts_ceiling, (0, 0, 1), -2.5, 80)

    merged = merge_coplanar_planes([floor, ceiling], distance_threshold=0.01)

    assert len(merged) == 2
    assert {p["inliers"] for p in merged} == {40, 40}
