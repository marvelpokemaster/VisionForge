import numpy as np
import json
from pathlib import Path
from typing import Dict, Any, List

def align_and_measure_room(
    planes_data: Dict[str, Any], 
    ref_distance: float = None, 
    rec_distance: float = None
) -> Dict[str, Any]:
    
    coord_sys = planes_data.get("coordinate_system")
    planes = planes_data.get("planes", [])
    
    scale_factor = 1.0
    metric_available = False
    
    if ref_distance is not None and rec_distance is not None and rec_distance > 0:
        scale_factor = ref_distance / rec_distance
        metric_available = True
        
    # Find floor bounds to estimate length/width
    length, width, height, area = 0.0, 0.0, 0.0, 0.0
    
    if coord_sys:
        up = np.array(coord_sys["up_axis"])
        x_ax = np.array(coord_sys["horizontal_axes"][0])
        z_ax = np.array(coord_sys["horizontal_axes"][1])
        
        # Estimate height
        floors = [p for p in planes if p["classification"] == "floor"]
        ceilings = [p for p in planes if p["classification"] == "ceiling"]
        
        if floors and ceilings:
            f_c = np.array(floors[0]["centroid"])
            c_c = np.array(ceilings[0]["centroid"])
            height = abs(np.dot(c_c - f_c, up)) * scale_factor
        elif floors:
            # Try to guess height from the highest point in walls
            f_c = np.array(floors[0]["centroid"])
            max_h = 0
            for p in planes:
                if p["classification"] == "wall":
                    pts = np.asarray(p["cloud"].points)
                    if len(pts) > 0:
                        h = np.max(np.dot(pts - f_c, up))
                        max_h = max(max_h, h)
            height = max_h * scale_factor
            
        # Estimate length and width from floor boundary
        if floors:
            floor_pts = np.asarray(floors[0]["cloud"].points)
            if len(floor_pts) > 0:
                # project onto X and Z
                x_coords = np.dot(floor_pts, x_ax)
                z_coords = np.dot(floor_pts, z_ax)
                
                l_min, l_max = np.min(x_coords), np.max(x_coords)
                w_min, w_max = np.min(z_coords), np.max(z_coords)
                
                length = (l_max - l_min) * scale_factor
                width = (w_max - w_min) * scale_factor
                area = length * width
                
    # Prepare JSON output
    out_planes = []
    for p in planes:
        out_planes.append({
            "id": p["id"],
            "type": p["classification"],
            "equation": p["equation"],
            "normal": p["normal"],
            "support": p["inliers"],
            "centroid": p["centroid"]
        })
        
    room_model = {
        "coordinate_system": coord_sys,
        "scale": {
            "metric_available": metric_available,
            "scale_factor": scale_factor
        },
        "room": {
            "length": float(length),
            "width": float(width),
            "height": float(height),
            "floor_area": float(area)
        },
        "planes": out_planes
    }
    
    return room_model
