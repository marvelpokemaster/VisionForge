import argparse
import cv2
import json
import math
import os
import sys
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple

def process_video(input_path: str, output_dir: str, target_fps: float, max_frames: int = None) -> Tuple[Dict[str, Any], List[str]]:
    input_file = Path(input_path)
    output_path = Path(output_dir)

    if not input_file.exists():
        raise FileNotFoundError(f"Input video file not found: {input_path}")

    # Create output directories
    frames_dir = output_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(input_file))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open the video file: {input_path}")

    original_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    if original_fps <= 0:
        original_fps = 30.0 # fallback
    if frame_count <= 0:
        raise ValueError("Video contains 0 frames or could not be read properly.")
        
    duration = frame_count / original_fps

    # Calculate frame sampling step
    frame_step = max(1, round(original_fps / target_fps))
    actual_sampling_fps = original_fps / frame_step
    
    extracted_count = 0
    saved_frames = []
    
    current_frame = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if current_frame % frame_step == 0:
            extracted_count += 1
            frame_filename = f"frame_{extracted_count:06d}.jpg"
            frame_filepath = frames_dir / frame_filename
            cv2.imwrite(str(frame_filepath), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            saved_frames.append(str(frame_filepath))
            
            if max_frames and extracted_count >= max_frames:
                break
                
        current_frame += 1

    cap.release()

    metadata = {
        "input": str(input_file.resolve()),
        "duration_seconds": duration,
        "original_fps": original_fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "sampling_fps": actual_sampling_fps,
        "extracted_frames": extracted_count
    }

    # Write metadata
    metadata_path = output_path / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    return metadata, saved_frames

def create_contact_sheet(frames: List[str], output_path: str):
    if not frames:
        return
        
    # use a sensible grid
    n_frames = len(frames)
    cols = math.ceil(math.sqrt(n_frames * 1.5))  # aspect ratio tweak for contact sheet
    rows = math.ceil(n_frames / cols)
    
    # read first image to get aspect ratio and resize to something reasonable for a thumbnail
    first_img = cv2.imread(frames[0])
    thumb_w = 200
    thumb_h = int(first_img.shape[0] * (thumb_w / first_img.shape[1]))
    
    sheet_w = cols * thumb_w
    sheet_h = rows * thumb_h
    
    # create black background canvas
    contact_sheet = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)
    
    for i, frame_path in enumerate(frames):
        row = i // cols
        col = i % cols
        
        img = cv2.imread(frame_path)
        img_resized = cv2.resize(img, (thumb_w, thumb_h))
        
        # Draw frame number
        text = f"{i+1}"
        cv2.putText(img_resized, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        
        y_start = row * thumb_h
        y_end = y_start + thumb_h
        x_start = col * thumb_w
        x_end = x_start + thumb_w
        
        contact_sheet[y_start:y_end, x_start:x_end] = img_resized
        
    cv2.imwrite(str(Path(output_path) / "contact_sheet.jpg"), contact_sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

def main():
    parser = argparse.ArgumentParser(description="Extract frames from a video for VisionForge Prototype 0")
    parser.add_argument("--input", required=True, help="Input video file path")
    parser.add_argument("--output", required=True, help="Output directory path")
    parser.add_argument("--fps", type=float, default=2.0, help="Target frames per second to sample (default: 2.0)")
    parser.add_argument("--max-frames", type=int, default=None, help="Maximum number of frames to extract")
    
    args = parser.parse_args()
    
    try:
        print(f"Processing video: {args.input}")
        metadata, frames = process_video(args.input, args.output, args.fps, args.max_frames)
        print(f"Extracted {metadata['extracted_frames']} frames to {args.output}/frames")
        
        print(f"Generating contact sheet...")
        create_contact_sheet(frames, args.output)
        print(f"Done. Output saved to {args.output}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
