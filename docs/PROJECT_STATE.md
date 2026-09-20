# VisionForge — Project State & AI Handoff

## 1. Project Overview
**VisionForge** is an indoor digital twin system built entirely on classical computer vision. The ultimate project goal is an "Iron Man" style application where a user points an Android phone camera at a room, and the system performs real-time classical visual tracking, sparse 3D reconstruction, geometric plane extraction, spatial scene graph generation, and displays a live digital twin of the environment.

**CRITICAL CONSTRAINT:** The project is **CLASSICAL COMPUTER VISION ONLY**.

## 2. Hard Technical Constraints

**Allowed:**
- OpenCV, Open3D, COLMAP / PyCOLMAP
- SIFT, ORB, FAST, KLT optical flow
- BF/FLANN matching, Lowe ratio test
- RANSAC plane fitting and geometric verification
- Fundamental / Essential Matrix, PnP, triangulation, bundle adjustment
- Classical SfM / SLAM
- PCA, geometric filtering, graph-based spatial reasoning

**Forbidden:**
- YOLO, SAM, CLIP, DINO
- SuperPoint, SuperGlue, LightGlue, ALIKED, LoFTR
- Learned depth, neural reconstruction (NeRF, Gaussian Splatting)
- Pretrained vision models, neural SLAM, AI-based object detection
- Do not introduce ML merely because it makes the problem easier.

## 3. Current Architecture
The current architecture is a purely Python-based offline and live-tracking pipeline.
- **Directories:** 
  - `src/visionforge/video/`: Frame extraction (P0).
  - `src/visionforge/reconstruction/`: Feature matching, epipolar geometry, PyCOLMAP incremental SfM (P1).
  - `src/visionforge/geometry/`: Point cloud cleaning, RANSAC plane extraction, room modeling (P2).
  - `src/visionforge/spatial/`: Scene graph generation, spatial queries, and Open3D visualization (P3/P4).
  - `src/visionforge/live/`: OpenCV KLT + 5-point algorithm visual odometry (P4).
- **Data Flow:** Video -> Frames -> Features -> Sparse Cloud -> Planar Geometry -> JSON Scene Graph -> Digital Twin Viewer.
- **Dependencies:** `opencv-python`, `numpy`, `open3d`, `pycolmap`, `pytest`.
- **CLI Entry Point:** `src/visionforge/cli.py`
- **Android/Mobile Components:** None currently exist.
- **Supabase Integration:** MCP server configured in the developer environment, but **zero** integration exists in the actual source code.

## 4. Prototype History

### P0 — Video Ingestion
- **Implemented:** Frame extraction, keyframe selection via variance of Laplacian (sharpness), metadata extraction, contact sheet generation.
- **Verification:** Tested via automated tests on synthetic/dummy video frames. No real indoor video has been run through it.

### P1 — Vision Core / Reconstruction
- **Implemented:** SIFT feature extraction, FLANN matching, ratio test, epipolar filtering (Fundamental matrix), and incremental SfM via PyCOLMAP.
- **Verification:** Unit tested via synthetic translating 2D images. No real-world video has been reconstructed.

### P2 — Spatial Reconstruction / Room Understanding
- **Implemented:** Open3D voxel downsampling, statistical outlier removal, iterative RANSAC plane segmentation, geometric classification (floor/wall/ceiling), and scaled room dimension calculation.
- **Verification:** Tested on a synthetic 3D point cloud of a box room. Successfully generated planes and room measurements.

### P3 — Spatial Intelligence
- **Implemented:** Scene graph generation from P2 JSON (`contains`, `adjacent_to`, `parallel_to`, `perpendicular_to`), and a spatial query engine (area, dimensions, fit checking).
- **Verification:** Manually verified via Python script on synthetic P2 outputs. No automated `pytest` suite exists for this module.

### P4 — Real-Time / Android Digital Twin
- **Implemented:** A lightweight live camera tracker (`tracker.py`) using KLT optical flow + Essential Matrix pose recovery + linear triangulation, and an Open3D standalone viewer.
- **Verification:** The script runs and opens a window, but has not been verified on a physical webcam by a human, nor has it been tested on Android. 

## 5. Current Source Tree
```text
src/visionforge/
├── cli.py                 # Main unified CLI (reconstruct, live). DO NOT refactor unnecessarily.
├── video/
│   └── extract_frames.py  # P0: Video frame extraction using cv2.VideoCapture.
├── reconstruction/
│   ├── pipeline.py        # P1: Orchestrates feature extraction -> matching -> SfM.
│   ├── two_view.py        # P1: SIFT matching and geometric verification.
│   └── incremental.py     # P1: Wrapper around pycolmap.
├── geometry/
│   ├── pipeline.py        # P2: CLI for geometry phase.
│   ├── point_cloud.py     # P2: Open3D cleaning (voxel, outlier removal).
│   ├── plane_fitting.py   # P2: RANSAC segment_plane and normal classification.
│   └── room_model.py      # P2: Coordinate bounding and room measurement.
├── spatial/
│   ├── scene_graph.py     # P3: Builds semantic JSON graph from P2 room model.
│   ├── queries.py         # P3: Deterministic geometry query engine.
│   └── viewer.py          # P4: Open3D visualization (bounding boxes for planes).
└── live/
    └── tracker.py         # P4: Classical visual odometry (KLT + 5-point EM).
```

## 6. Current CLI / Commands
Based on the repository, these commands currently function:
- **Run automated tests:** `source venv/bin/activate && PYTHONPATH=src pytest tests/`
- **Run offline reconstruction pipeline:** `python -m visionforge.cli reconstruct --video <path_to_mp4>`
- **Run live webcam tracking demo:** `python -m visionforge.cli live`

## 7. Tests & Verification

| Component | Test | Result | Evidence | Status |
|-----------|------|--------|----------|--------|
| P0 Video Ingestion | Automated (`test_extract_frames.py`) | Pass | Pytest output | Verified (Synthetic) |
| P1 Reconstruction | Automated (`test_reconstruction.py`) | Pass | Pytest output | Verified (Synthetic) |
| P2 Room Geometry | Automated (`test_geometry.py`) | Pass | Pytest output | Verified (Synthetic) |
| P3 Scene Graph | Manual Script | Pass | Terminal output logs | Verified (Synthetic) |
| P4 Offline Viewer | CLI dry run | Pass | Open3D window generation | Partially Verified |
| P4 Live Tracker | None | Untested | No physical webcam test | UNVERIFIED |
| End-to-End Real Video | None | Untested | No `room.mp4` provided yet | UNVERIFIED |
| Android Integration | None | Untested | No Android code exists | PLANNED |

## 8. Generated Outputs / Artifacts
- `sparse_cloud.ply`: The 3D point cloud output from P1. Currently, the artifacts in `outputs/` were generated synthetically because no real video was processed.
- `room_model.json`: Contains the equation, normal, centroid, and bounding dimensions of detected geometric planes.
- `scene_graph.json`: Nodes and edges representing semantic relationships (e.g., floor is perpendicular to wall).
- `statistics.json`: Contains retention ratios, plane counts, and processing times.

## 9. Known Problems / Limitations
- **No Real Video Verification:** The pipeline has strictly been tested on synthetic data. Real-world motion blur, textureless walls, and sensor noise are untested.
- **Scale Ambiguity & Drift:** Monocular reconstruction (P1) lacks absolute scale. The live VO tracker (P4) will experience severe scale drift over time without global bundle adjustment.
- **Manhattan-World Assumption:** P2 geometry classification strictly assumes orthogonal vertical walls and flat horizontal floors.
- **No Android Support:** The "Iron Man" vision relies on Android, but the current codebase only supports desktop webcam access via `cv2.VideoCapture(0)`.

## 10. Git / Development State
- **Branch:** `main`
- **Recent Commits:** P0 through P4 are fully committed up to `feat: finalize integrated prototype with scene graph, queries, and live mode`.
- **Uncommitted Changes:** `.agents/` directory containing newly installed Supabase agent skills.
- **Working Tree:** Clean (excluding untracked agent skills).

## 11. Supabase Role
- **Current State:** The Supabase MCP is configured in the local AI environment, but Supabase is **NOT** integrated into the VisionForge Python source code.
- **Intended Boundary:** Supabase SHOULD be used for persisting project state, saving JSON scene graphs, storing room measurements, and handling asynchronous sync. It MUST NOT be used for streaming raw camera frames, high-frequency CV processing, or frame-by-frame Android tracking round-trips.

## 12. Immediate Next Objective
The immediate next objective is **REAL-WORLD VERIFICATION**.
Before building the Android mobile app, the existing P0-P4 Python pipeline MUST be successfully executed against a real, physical indoor smartphone video (`room.mp4`) to validate the classical CV pipeline's robustness against real-world sensor noise and motion.

## 13. Android / Real-Time Requirements
The next major architectural phase is the Android client:
- Must run on a physical Android phone using the rear camera.
- Must capture real camera frames and perform low-latency local processing.
- Must STRICTLY use classical CV only.
- The tracking state must update a sparse map from actual observations.
- Tracking loss must be handled honestly; no faking poses or point clouds.
- **Current Readiness:** The Python codebase is completely detached from Android. We will need a way to bridge Android camera frames to the CV pipeline (either via JNI/C++ OpenCV on-device, or streaming frames to a local Python server via WebSocket/UDP for the prototype).

## 14. Handoff Instructions for the Next AI Agent
1. **Read this file first.**
2. **Inspect the repository before changing code.** Do not assume anything works unless you see the test evidence.
3. **Do not rebuild completed components unnecessarily.**
4. **Preserve the classical-CV constraint.** Absolutely no neural networks.
5. **Run existing tests before making changes:** `pytest tests/`.
6. **CODE → RUN → SEE RESULT → SAVE RESULT → COMMIT → NEXT.**
7. Never claim verification without actually running the relevant test.
8. If an issue is clearly straightforward, fix it. If it is obscure/environment-specific, document it and move on.
9. Keep the offline pipeline reproducible.

## 15. Recommended Next Task
**NEXT AI TASK:** Execute the unified offline pipeline (`visionforge reconstruct`) against a real indoor smartphone video (`data/input/room.mp4`), document the actual failure points/successes, and fix any immediate classical CV pipeline crashes before beginning Android integration.
