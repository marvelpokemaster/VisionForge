import pytest
import numpy as np
import open3d as o3d
from pathlib import Path

from visionforge.geometry.point_cloud import process_point_cloud
from visionforge.geometry.plane_fitting import extract_dominant_planes, classify_planes
from visionforge.geometry.room_model import align_and_measure_room

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
