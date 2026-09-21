# VisionForge — Project State & AI Handoff

## 1. Project Overview
**VisionForge** is a purely classical computer vision pipeline (no neural networks) for converting monocular video (e.g., a room scan) into a sparse 3D point cloud, extracting semantic room geometry (floor, ceiling, walls), building a spatial scene graph, and persisting it as a Digital Twin. 

The ultimate goal is to process video offline or live, construct an exact metric 3D model of architectural spaces, and export it for downstream applications (such as AR/VR, Android clients, or Web interfaces). 

**Current Scope Constraint:** 
The project is strictly focused on classical CV logic and the Python backend. Any Android client work is currently PLANNED but NOT yet started.

## 2. Current Status Summary
* **Phase:** Backend & Pipeline Implementation (Offline)
* **Overall Status:** The offline reconstruction pipeline works end-to-end. We recently integrated advanced room plane classification logic that accurately distinguishes floors, ceilings, and walls based on architectural heuristics (even when missing data, such as a floor-only or wall-heavy point cloud).
* **Test Suite:** 119/119 passing (`pytest tests/`)
* **Live Mode:** Partially implemented (`tracker.py` exists but full real-time SLAM is pending).

## 3. Implemented & Verified Features

### Pipeline Stages
*   **P0: Video Ingestion (`src/visionforge/video/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** Extracts frames using `ffmpeg-python`, blur detection (variance of Laplacian). Tested on real video `data/input/room.mp4`.
*   **P1: Sparse Reconstruction (`src/visionforge/reconstruction/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** SIFT feature extraction, Lowe's ratio test matching, geometric verification, pose estimation, and sparse triangulation via PyCOLMAP. Outputs `sparse_cloud.ply`. Verified on real video.
*   **P2: Room Geometry (`src/visionforge/geometry/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** RANSAC plane fitting with DBSCAN clustering. 
    *   **IMPLEMENTED, TESTED/VERIFIED:** Advanced architectural plane classification (`plane_fitting.py`). Identifies up-vector using multiple sources (camera gravity, manhattan pairs, architectural heuristics) and successfully resolves dominant walls or missing floors. Tested and passing 119/119 tests.
*   **P3: Spatial Scene Graph (`src/visionforge/spatial/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** Constructs a graph of architectural elements, calculates spatial relationships (e.g., adjacency, parallel), handles hierarchical structures (Rooms -> Planes).
*   **P4: Digital Twin Export (`src/visionforge/twin/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** Generates JSON representations (`room_model.json`) containing camera poses, point clouds, and the scene graph.

### Infrastructure & Backend
*   **CLI (`src/visionforge/cli.py`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** CLI tools for running reconstruction offline (`visionforge.cli reconstruct`).
*   **API (`src/visionforge/api/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** FastAPI server for handling requests.
*   **Persistence (`src/visionforge/persistence/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** Supabase integration for saving configurations and digital twin states.
*   **Tests (`tests/`)**
    *   **IMPLEMENTED, TESTED/VERIFIED:** 119 unit tests running and passing, including robust mock integration for geometry.

## 4. Partially Implemented Features
*   **Live Tracking (`src/visionforge/live/tracker.py`)**
    *   **PARTIALLY IMPLEMENTED:** Basic structure exists, but true incremental SLAM / continuous tracking is not fully hooked up to a live camera feed.

## 5. Planned Features (Not Yet Started)
*   **Android Client:** The frontend mobile application for scanning and viewing the reconstruction.
*   **Dense Reconstruction:** Currently the pipeline is sparse-only. Dense point cloud generation is not implemented.
*   **Semantic Texturing:** Projecting video frames back onto the fitted planes to create textured 3D models.

## 6. Known Issues / Caveats
*   **Scale Ambiguity:** Because the pipeline uses a single monocular camera without IMU integration, the generated 3D model is up to scale (scale ambiguity typical of monocular SLAM). True metric scale relies on external priors or future IMU data.
*   **Dependencies:** `testclient` in FastAPI and `anyio` have deprecation warnings during testing. This does not affect current execution but should be upgraded.
*   **Network:** `npm/npx` (used for Supabase tools or skills) require `proxychains` on the current user's environment.

## 7. Next Steps for AI Agent
1.  Review this document and verify it matches the repository.
2.  Do NOT modify existing classical CV logic unless a specific bug is discovered.
3.  Await user instructions on the next major milestone (e.g., starting Android integration, extending the API, or addressing live tracking).

## 8. Handoff Instructions
*   **To run tests:** `source venv/bin/activate && PYTHONPATH=src pytest tests/`
*   **To run pipeline:** `source venv/bin/activate && PYTHONPATH=src python -m visionforge.cli reconstruct --input data/input/room.mp4 --output outputs/`
*   **Dependencies:** Controlled via `requirements.txt`.
