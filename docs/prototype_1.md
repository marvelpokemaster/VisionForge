# VisionForge Prototype 1: Classical 3D Reconstruction

## Purpose
Prototype 1 takes the sequential video frames extracted by Prototype 0 and runs a classical computer vision pipeline to estimate camera motion and generate a sparse 3D point cloud of the indoor environment. This provides the fundamental offline 3D geometry engine that VisionForge will later build upon for room understanding.

## Pipeline
1. **Frame Loading:** Reads extracted frames (e.g., from `outputs/prototype_0/frames/`).
2. **Two-View Checkout (Stages 1-5):**
   - **Feature Extraction (SIFT):** Detects keypoints and extracts SIFT descriptors for a representative frame pair.
   - **Feature Matching:** Matches descriptors sequentially (consecutive frames) using OpenCV's BFMatcher with a Lowe ratio test.
   - **Geometric Verification:** Uses RANSAC and the Essential Matrix to filter out geometrically inconsistent matches.
   - **Camera Geometry & Triangulation:** Recovers the relative camera pose (Rotation and Translation) and triangulates 3D points, producing a `points.ply` cloud and `cameras.json`. Visualizations of the detected SIFT features and matched inliers are also saved.
3. **Multi-Frame Incremental SfM (Stage 6):**
   - We utilize `pycolmap` for robust multi-frame incremental Structure-from-Motion (SfM).
   - This explicitly uses classical SIFT feature extraction and sequential classical matching to produce a robust global sparse reconstruction.
   - The final output is exported as `sparse_cloud.ply` alongside the camera poses.

## Algorithms Used
- SIFT (Scale-Invariant Feature Transform) for features.
- K-Nearest Neighbors (KNN=2) with Lowe's ratio test for putative matching.
- RANSAC (Random Sample Consensus) with Essential Matrix estimation for robust geometric verification.
- Triangulation (Direct Linear Transform).
- Bundle Adjustment (via PyCOLMAP's Incremental Mapper).

## Dependencies
- `opencv-python`
- `numpy`
- `pycolmap`

## How to Run
Ensure you have activated your environment and installed all dependencies. Then run:
```bash
python -m visionforge.reconstruction.pipeline --frames-dir outputs/prototype_0/frames --output outputs/prototype_1
```

## Outputs
```
outputs/prototype_1/
├── two_view/
│   ├── cameras.json
│   ├── points.ply
│   └── statistics.json
├── visualizations/
│   ├── features.jpg
│   └── matches.jpg
├── reconstruction/
│   ├── cameras.json
│   └── sparse_cloud.ply
└── statistics.json
```

## Camera & Intrinsic Assumptions
In this offline prototype, we do not have perfect smartphone camera intrinsics. The two-view pipeline makes a simple guess (focal length = max(width, height), principal point = center) to compute the Essential matrix. 
The PyCOLMAP multi-frame pipeline automatically attempts to auto-calibrate the intrinsics during the incremental mapping phase. Do not treat the initial scale or metric dimensions as perfectly accurate yet.

## Reconstruction Limitations
- Highly textureless walls or repetitive patterns (like identical tiles) will cause matching failure or "hallucinated" geometry.
- The scale of the reconstruction is arbitrary (up to a scale factor) because it relies purely on monocular cues.
- Planar scenes (like a flat textured floor viewed from perfectly above) can cause Essential Matrix degeneracy.

## Connection to Future "Live Mode" (P4)
This pipeline is explicitly **offline** and relies on extracted frames. In future milestones, the frame ingestion layer will be abstracted into a `LiveCameraSource`, allowing frame-by-frame visual odometry (SLAM). For now, `pycolmap` SfM gives us the most reliable and highest quality offline baseline.
