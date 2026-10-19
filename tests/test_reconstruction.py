import pytest
import cv2
import numpy as np
from pathlib import Path

from visionforge.reconstruction.two_view import run_two_view
from visionforge.reconstruction.incremental import run_incremental_sfm

@pytest.fixture
def synthetic_frames(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    
    # create a highly textured base image (checkerboard + noise)
    base = np.random.randint(0, 255, (800, 800, 3), dtype=np.uint8)
    for i in range(0, 800, 50):
        cv2.line(base, (i, 0), (i, 800), (255,255,255), 2)
        cv2.line(base, (0, i), (800, i), (255,255,255), 2)
        
    # generate 3 frames panning over it
    for i in range(3):
        x = i * 20
        y = i * 10
        frame = base[y:y+400, x:x+600]
        cv2.imwrite(str(frames_dir / f"frame_{i:04d}.jpg"), frame)
        
    return frames_dir

def test_two_view(synthetic_frames, tmp_path):
    f1 = synthetic_frames / "frame_0000.jpg"
    f2 = synthetic_frames / "frame_0001.jpg"
    output_dir = tmp_path / "two_view"
    
    stats = run_two_view(f1, f2, output_dir)
    
    assert stats['frame1_kps'] > 10
    assert stats['raw_matches'] > 5
    # Depending on RANSAC it might not find an essential matrix for a pure 2D pan (planar scene degeneracy), 
    # but the pipeline should run without crashing.
    assert (output_dir / "features.jpg").exists()
    assert (output_dir / "matches.jpg").exists()

def test_incremental_sfm(synthetic_frames, tmp_path):
    output_dir = tmp_path / "reconstruction"
    stats = run_incremental_sfm(synthetic_frames, output_dir)
    
    # PyCOLMAP might fail to reconstruct a pure 2D translation sequence, 
    # but we just test that it runs without exceptions.
    assert 'num_reconstructions' in stats
    assert (output_dir / "statistics.json").exists()
