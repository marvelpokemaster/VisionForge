import os
import json
from pathlib import Path
from typing import Dict, Any
import pycolmap

def run_incremental_sfm(image_dir: Path, output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "database.db"
    
    # Remove existing db if any
    if database_path.exists():
        database_path.unlink()
        
    stats = {}
    
    # SIFT feature extraction
    pycolmap.extract_features(database_path, image_dir)
    
    # Sequential matching (suitable for video frames)
    pycolmap.match_sequential(database_path)
    
    # Incremental SfM mapping
    reconstructions = pycolmap.incremental_mapping(database_path, image_dir, output_dir)
    
    stats['num_reconstructions'] = len(reconstructions)
    
    if len(reconstructions) > 0:
        # Use the largest reconstruction
        rec = reconstructions[0] 
        stats['reconstructed_cameras'] = len(rec.images)
        stats['reconstructed_points'] = len(rec.points3D)
        
        # Export PLY
        rec.export_PLY(str(output_dir / "sparse_cloud.ply"))
        
        # Export cameras
        cameras = []
        for image_id, image in rec.images.items():
            cam = rec.cameras[image.camera_id]
            cam_from_world = image.cam_from_world()

            cameras.append({
                "id": image_id,
                "name": image.name,
                "rotation_quat": cam_from_world.rotation.quat.tolist(),
                "translation": cam_from_world.translation.tolist(),
                "camera_model": cam.model.name,
                "camera_params": cam.params.tolist()
            })
            
        with open(output_dir / "cameras.json", "w") as f:
            json.dump(cameras, f, indent=2)
            
    with open(output_dir / "statistics.json", "w") as f:
        json.dump(stats, f, indent=2)
        
    return stats
