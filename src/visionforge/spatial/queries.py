import numpy as np
from typing import Dict, Any, List, Optional

class SpatialQueryEngine:
    def __init__(self, scene_graph: Dict[str, Any]):
        self.graph = scene_graph
        self.nodes = {n["id"]: n for n in scene_graph["nodes"]}
        self.edges = scene_graph["edges"]
        
    def get_room_dimensions(self) -> Dict[str, float]:
        for n in self.graph["nodes"]:
            if n["type"] == "room":
                return n["properties"]
        return {}
        
    def get_floor_area(self) -> float:
        dims = self.get_room_dimensions()
        return dims.get("floor_area", 0.0)
        
    def get_wall_area(self, wall_id: str) -> float:
        # P2 didn't explicitly compute wall area, we approximate it using height and width heuristic
        # If we just have support, we could estimate it, but here we just return a bounding box area if known
        # We can fall back to using support points as a rough proxy if actual extent wasn't saved
        dims = self.get_room_dimensions()
        h = dims.get("height", 0.0)
        w = dims.get("width", 0.0) # very rough
        return h * w
        
    def get_largest_wall(self) -> Optional[str]:
        max_support = -1
        largest_id = None
        for n in self.graph["nodes"]:
            if n["type"] == "wall":
                support = n["properties"].get("support", 0)
                if support > max_support:
                    max_support = support
                    largest_id = n["id"]
        return largest_id
        
    def distance_between(self, entity_a: str, entity_b: str) -> float:
        node_a = self.nodes.get(entity_a)
        node_b = self.nodes.get(entity_b)
        if not node_a or not node_b:
            return -1.0
            
        c1 = np.array(node_a["properties"].get("centroid", [0,0,0]))
        c2 = np.array(node_b["properties"].get("centroid", [0,0,0]))
        
        # If they are parallel walls, we can use the plane equation distance
        if node_a["type"] == "wall" and node_b["type"] == "wall":
            # check if parallel
            for e in self.edges:
                if (e["source"] == entity_a and e["target"] == entity_b) or \
                   (e["source"] == entity_b and e["target"] == entity_a):
                    if e["relation"] == "parallel_to":
                        # distance between parallel planes: |d1 - d2| / |n|
                        d1 = node_a["properties"]["equation"][3]
                        d2 = node_b["properties"]["equation"][3]
                        return abs(d1 - d2)
                        
        return float(np.linalg.norm(c1 - c2))
        
    def check_rectangular_fit(self, req_length: float, req_width: float) -> bool:
        dims = self.get_room_dimensions()
        l = dims.get("length", 0.0)
        w = dims.get("width", 0.0)
        
        # Allow rotation
        can_fit = (req_length <= l and req_width <= w) or (req_length <= w and req_width <= l)
        return can_fit
