#point cloud.py
import open3d as o3d
import numpy as np
from pathlib import Path
from typing import Tuple, Dict, Any

def process_point_cloud(
    input_path: Path, 
    output_dir: Path, 
    voxel_size: float = 0.05, 
    outlier_nb_neighbors: int = 20, 
    outlier_std_ratio: float = 2.0
) -> Tuple[o3d.geometry.PointCloud, Dict[str, Any]]:
    
    if not input_path.exists():
        raise FileNotFoundError(f"Point cloud file not found: {input_path}")
        
    pcd = o3d.io.read_point_cloud(str(input_path))
    
    if pcd.is_empty():
        raise ValueError("Point cloud is empty or invalid.")
        
    raw_points = len(pcd.points)
    
    # 1. Voxel downsampling
    pcd_down = pcd.voxel_down_sample(voxel_size=voxel_size)
    
    # 2. Statistical outlier removal
    pcd_clean, ind = pcd_down.remove_statistical_outlier(
        nb_neighbors=outlier_nb_neighbors, 
        std_ratio=outlier_std_ratio
    )
    
    # 3. Normal estimation
    pcd_clean.estimate_normals(
        search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 2, max_nn=30)
    )
    
    cleaned_points = len(pcd_clean.points)
    
    # Calculate bounding box
    bbox = pcd_clean.get_axis_aligned_bounding_box()
    min_bound = bbox.get_min_bound().tolist()
    max_bound = bbox.get_max_bound().tolist()
    centroid = pcd_clean.get_center().tolist()
    
    stats = {
        "raw_points": raw_points,
        "cleaned_points": cleaned_points,
        "retention_ratio": cleaned_points / raw_points if raw_points > 0 else 0,
        "min_bound": min_bound,
        "max_bound": max_bound,
        "centroid": centroid,
        "approx_dimensions": [
            max_bound[0] - min_bound[0],
            max_bound[1] - min_bound[1],
            max_bound[2] - min_bound[2]
        ]
    }
    
    # Save outputs
    pcd_dir = output_dir / "pointcloud"
    pcd_dir.mkdir(parents=True, exist_ok=True)
    
    o3d.io.write_point_cloud(str(pcd_dir / "raw.ply"), pcd)
    o3d.io.write_point_cloud(str(pcd_dir / "cleaned.ply"), pcd_clean)
    
    return pcd_clean, stats
