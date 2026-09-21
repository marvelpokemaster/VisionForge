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

def merge_coplanar_planes(
    planes: List[Dict[str, Any]],
    distance_threshold: float,
    normal_dot_threshold: float = 0.98,
    offset_factor: float = 2.0
) -> List[Dict[str, Any]]:
    """Merge RANSAC plane segments that are really the same physical surface
    split by noise/thresholding: normals agree (|dot| > normal_dot_threshold)
    and plane offsets differ by less than offset_factor * distance_threshold.
    Support counts are summed, inlier clouds concatenated, centroid recomputed.
    The surviving equation/normal/id are taken from the larger (base) segment.
    """
    used = [False] * len(planes)
    merged = []

    for i in range(len(planes)):
        if used[i]:
            continue
        used[i] = True

        base = dict(planes[i])
        base_normal = np.array(base["normal"])
        base_d = base["equation"][3]
        combined_cloud = base["cloud"]
        combined_inliers = base["inliers"]
        combined_ratio = base.get("inlier_ratio", 0.0)

        for j in range(i + 1, len(planes)):
            if used[j]:
                continue

            other = planes[j]
            other_normal = np.array(other["normal"])
            other_d = other["equation"][3]

            dot = float(np.dot(base_normal, other_normal))
            if abs(dot) <= normal_dot_threshold:
                continue

            # normalize sign so offsets are comparable regardless of normal direction
            other_d_aligned = other_d if dot > 0 else -other_d
            if abs(base_d - other_d_aligned) >= offset_factor * distance_threshold:
                continue

            used[j] = True
            combined_cloud = combined_cloud + other["cloud"]
            combined_inliers += other["inliers"]
            combined_ratio += other.get("inlier_ratio", 0.0)

        base["cloud"] = combined_cloud
        base["inliers"] = combined_inliers
        base["inlier_ratio"] = combined_ratio
        base["centroid"] = combined_cloud.get_center().tolist()
        merged.append(base)

    return merged

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
