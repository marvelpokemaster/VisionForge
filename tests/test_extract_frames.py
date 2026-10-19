import cv2
import json
import numpy as np
import pytest
from pathlib import Path

from visionforge.video.extract_frames import process_video, create_contact_sheet

@pytest.fixture
def synthetic_video(tmp_path):
    video_path = tmp_path / "test_video.mp4"
    width, height = 320, 240
    fps = 30
    duration = 2 # 2 seconds
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))
    
    # 60 frames total
    for i in range(fps * duration):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Add frame number to frame for visual testing if needed
        cv2.putText(frame, str(i), (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        out.write(frame)
        
    out.release()
    return video_path

def test_process_video_metadata(synthetic_video, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    metadata, frames = process_video(str(synthetic_video), str(output_dir), target_fps=2.0)
    
    assert metadata["duration_seconds"] == 2.0
    assert metadata["original_fps"] == 30.0
    assert metadata["frame_count"] == 60
    assert metadata["width"] == 320
    assert metadata["height"] == 240
    assert metadata["extracted_frames"] == 4 # 30 / 15 step = 2 per sec * 2 sec = 4 frames
    assert len(frames) == 4

def test_process_video_outputs(synthetic_video, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    process_video(str(synthetic_video), str(output_dir), target_fps=1.0)
    
    # Check frames
    frames_dir = output_dir / "frames"
    assert frames_dir.exists()
    assert (frames_dir / "frame_000001.jpg").exists()
    assert (frames_dir / "frame_000002.jpg").exists()
    
    # Check metadata.json
    metadata_json = output_dir / "metadata.json"
    assert metadata_json.exists()
    with open(metadata_json) as f:
        data = json.load(f)
        assert "input" in data
        assert data["extracted_frames"] == 2

def test_create_contact_sheet(synthetic_video, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    _, frames = process_video(str(synthetic_video), str(output_dir), target_fps=2.0)
    create_contact_sheet(frames, str(output_dir))
    
    assert (output_dir / "contact_sheet.jpg").exists()
