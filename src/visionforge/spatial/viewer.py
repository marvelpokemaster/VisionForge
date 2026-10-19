import open3d as o3d
import numpy as np

def create_digital_twin(sparse_cloud_path: str, room_model: dict) -> o3d.geometry.PointCloud:
    pcd = o3d.io.read_point_cloud(sparse_cloud_path)
    
    geometries = [pcd]
    
    planes = room_model.get("planes", [])
    
    colormap = {
        "floor": [0.0, 1.0, 0.0],
        "ceiling": [0.0, 0.0, 1.0],
        "wall": [1.0, 0.0, 0.0],
        "unknown": [0.5, 0.5, 0.5]
    }
    
    # We will generate a bounding box for each plane for visual representation
    for p in planes:
        center = np.array(p["centroid"])
        normal = np.array(p["normal"])
        
        # Create a simple box representation for the architectural surface
        # For a robust offline demo, showing normals or meshes is nice
        mesh_box = o3d.geometry.TriangleMesh.create_box(width=1.0, height=1.0, depth=0.05)
        mesh_box.paint_uniform_color(colormap.get(p["type"], [0, 0, 0]))
        
        # Align box to normal
        z_axis = np.array([0, 0, 1])
        v = np.cross(z_axis, normal)
        c = np.dot(z_axis, normal)
        k = 1.0 / (1.0 + c) if c != -1 else 1.0
        
        if c != -1 and np.linalg.norm(v) > 1e-6:
            rot = np.array([
                [v[0]*v[0]*k + c,     v[0]*v[1]*k - v[2], v[0]*v[2]*k + v[1]],
                [v[1]*v[0]*k + v[2], v[1]*v[1]*k + c,     v[1]*v[2]*k - v[0]],
                [v[2]*v[0]*k - v[1], v[2]*v[1]*k + v[0], v[2]*v[2]*k + c]
            ])
            mesh_box.rotate(rot, center=(0,0,0))
            
        mesh_box.translate(center)
        geometries.append(mesh_box)
        
    return geometries

def launch_viewer(geometries):
    print("Launching Digital Twin Viewer. Press 'Q' to exit.")
    o3d.visualization.draw_geometries(geometries, window_name="VisionForge Digital Twin")
