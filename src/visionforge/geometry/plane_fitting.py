import open3d as o3d
import numpy as np
from typing import List, Dict, Any

def extract_dominant_planes(
    pcd: o3d.geometry.PointCloud, 
    distance_threshold: float = 0.05, 
    ransac_n: int = 3, 
    num_iterations: int = 1000,
    min_ratio: float = 0.05,
    max_planes: int = 10
) -> List[Dict[str, Any]]:
    
    planes = []
    remaining_pcd = pcd
    initial_points = len(pcd.points)
    
    for i in range(max_planes):
        if len(remaining_pcd.points) < initial_points * min_ratio:
            break
            
        plane_model, inliers = remaining_pcd.segment_plane(
            distance_threshold=distance_threshold,
            ransac_n=ransac_n,
            num_iterations=num_iterations
        )
        
        if len(inliers) < initial_points * min_ratio:
            break
            
        inlier_cloud = remaining_pcd.select_by_index(inliers)
        
        a, b, c, d = plane_model
        normal = np.array([a, b, c])
        normal = normal / np.linalg.norm(normal)
        
        centroid = inlier_cloud.get_center()
        
        # Orient normal to point towards the origin (or camera centroid if known, here origin is 0,0,0 usually)
        # To make things consistent, we just keep the normal as is, we will orient it later.
        
        planes.append({
            "id": f"plane_{i:03d}",
            "equation": [a, b, c, d],
            "normal": normal.tolist(),
            "inliers": len(inliers),
            "inlier_ratio": len(inliers) / initial_points,
            "centroid": centroid.tolist(),
            "cloud": inlier_cloud # Store cloud for visualization/area later
        })
        
        remaining_pcd = remaining_pcd.select_by_index(inliers, invert=True)
        
    return planes

def classify_planes(planes: List[Dict[str, Any]], all_points: np.ndarray) -> Dict[str, Any]:
    if not planes:
        return {"coordinate_system": None, "planes": []}
        
    # Assume the largest plane (first one) is the floor candidate
    floor_candidate = planes[0]
    up_vector = np.array(floor_candidate["normal"])
    
    # We want the UP vector to point "into" the room.
    # Check the dot product of (all_points - floor_centroid) with up_vector
    # The majority of the room points should be in the positive direction of UP.
    centroid = np.array(floor_candidate["centroid"])
    vecs = all_points - centroid
    dots = vecs.dot(up_vector)
    
    if np.sum(dots > 0) < np.sum(dots < 0):
        up_vector = -up_vector
        
    for p in planes:
        n = np.array(p["normal"])
        dot_up = abs(np.dot(n, up_vector))
        
        if dot_up > 0.85: # roughly parallel to floor
            # check height relative to floor
            height_diff = np.dot(np.array(p["centroid"]) - centroid, up_vector)
            if height_diff > 1.0: # arbitrary 1 unit distance to be considered ceiling
                p["classification"] = "ceiling"
            else:
                p["classification"] = "floor"
        elif dot_up < 0.25: # roughly orthogonal to floor
            p["classification"] = "wall"
        else:
            p["classification"] = "unknown"
            
    # Determine horizontal axes from the largest wall
    x_axis = None
    for p in planes:
        if p["classification"] == "wall":
            n = np.array(p["normal"])
            # project normal onto horizontal plane and normalize
            x_axis = n - np.dot(n, up_vector) * up_vector
            norm = np.linalg.norm(x_axis)
            if norm > 1e-6:
                x_axis = x_axis / norm
                break
                
    if x_axis is None:
        # Fallback if no walls found
        # Pick an arbitrary vector orthogonal to up_vector
        v = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(v, up_vector)) > 0.9:
            v = np.array([0.0, 1.0, 0.0])
        x_axis = v - np.dot(v, up_vector) * up_vector
        x_axis = x_axis / np.linalg.norm(x_axis)
        
    z_axis = np.cross(x_axis, up_vector)
    
    coord_system = {
        "up_axis": up_vector.tolist(),
        "horizontal_axes": [x_axis.tolist(), z_axis.tolist()]
    }
    
    return {"coordinate_system": coord_system, "planes": planes}
