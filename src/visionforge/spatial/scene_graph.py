import numpy as np
import json
from pathlib import Path
from typing import Dict, Any, List

def build_scene_graph(room_model: Dict[str, Any]) -> Dict[str, Any]:
    nodes = []
    edges = []
    
    # Add room node
    room_id = "room_001"
    nodes.append({
        "id": room_id,
        "type": "room",
        "properties": room_model.get("room", {})
    })
    
    planes = room_model.get("planes", [])
    
    # Add plane nodes
    for p in planes:
        nodes.append({
            "id": p["id"],
            "type": p["type"],
            "properties": {
                "equation": p["equation"],
                "normal": p["normal"],
                "centroid": p["centroid"],
                "support": p["support"]
            }
        })
        
        # Every plane is contained by the room
        edges.append({
            "source": room_id,
            "target": p["id"],
            "relation": "contains"
        })
        
    # Discover geometric relationships between planes
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            p1 = planes[i]
            p2 = planes[j]
            n1 = np.array(p1["normal"])
            n2 = np.array(p2["normal"])
            
            dot_prod = abs(np.dot(n1, n2))
            
            if dot_prod > 0.85:
                edges.append({
                    "source": p1["id"],
                    "target": p2["id"],
                    "relation": "parallel_to"
                })
            elif dot_prod < 0.25:
                edges.append({
                    "source": p1["id"],
                    "target": p2["id"],
                    "relation": "perpendicular_to"
                })
                
                # Check if they are adjacent/intersecting by looking at centroid distances
                c1 = np.array(p1["centroid"])
                c2 = np.array(p2["centroid"])
                dist = np.linalg.norm(c1 - c2)
                # Heuristic: if centroids are reasonably close relative to typical room scale, call them adjacent
                # For an indoor room, 10 units might be close enough
                if dist < 10.0:
                    edges.append({
                        "source": p1["id"],
                        "target": p2["id"],
                        "relation": "adjacent_to"
                    })
                    
    return {
        "nodes": nodes,
        "edges": edges
    }

def save_scene_graph(scene_graph: Dict[str, Any], output_path: Path):
    with open(output_path, 'w') as f:
        json.dump(scene_graph, f, indent=2)
