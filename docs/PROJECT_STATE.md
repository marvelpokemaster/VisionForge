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

## 9. Update — 2026-10-16: Phase 3 step 1, live classical tracking on a video file (branch `live-tracking`)

Supersedes §2 "Live Mode" and §4 above. Details and all measured numbers: `docs/live_tracking.md`; session log: `docs/PROJECT_HISTORY.md` §27.

*   **Live Tracking (`src/visionforge/live/`)** — **IMPLEMENTED, TESTED/VERIFIED on the synthetic clip only.** Keyframe-based monocular tracker: parallax-gated two-keyframe initialisation (essential matrix, `USAC_ACCURATE`), per-frame `solvePnPRansac` against the map (scale anchored to the first keyframe pair, not guessed per frame), new points only at keyframes with cheirality / reprojection / angle checks and widest-baseline re-triangulation, explicit `INITIALIZING | TRACKING | LOST` state with `None` poses while LOST and re-initialisation into a new unstitched segment. Intrinsics from a COLMAP `cameras.json` or a documented guess (focal = max(w, h)). Classical CV only.
*   **Export contract unchanged:** `p1/reconstruction/{sparse_cloud.ply, cameras.json}` in the exact `incremental.py` format (PINHOLE, one camera per keyframe) + `tracking_report.json`; P2 → scene graph → twin → API → frontend run on it unchanged via the shared `cli._run_geometry_scene_graph_twin()`.
*   **CLI:** `python -m visionforge.cli live --video <mp4> --output <dir> [--intrinsics-from <cameras.json>] [--no-gui] [--max-frames N]`; no args = webcam demo. `scripts/compare_trajectories.py` gives the sim(3)-aligned trajectory RMSE between two `cameras.json`; `scripts/synthetic_clip_gt_cameras.py` writes the synthetic clip's true camera path.
*   **Tests:** 145 backend (`pytest tests -q`, `pytest.ini` sets `pythonpath = src` so `PYTHONPATH=src` is no longer needed) + 16 frontend.
*   **Measured (synthetic clip):** 24 frames → 22 keyframes, 87.5 % TRACKING, 0 LOST episodes, 842 map points, 0.36 px mean reprojection RMS; trajectory vs COLMAP 2.4 % of extent, vs ground truth 0.21 % (COLMAP itself: 2.41 %); P2 finds the same 3 planes (floor 1, wall 2) as the COLMAP run.
*   **Still true / not solved:** no physical-camera footage has ever been processed (`data/input/room.mp4` absent); no bundle adjustment, loop closure or relocalisation — drift accumulates; scale arbitrary; the frontend frustum reads `camera_params` in SIMPLE_RADIAL order (cosmetic for PINHOLE). Webcam/phone streaming is step 2+.
*   **30 fps follow-up (same path, 360 frames; `docs/live_tracking.md` §6, history §28):** 32 keyframes (8.9 %) — the parallax gate throttles; 94.7 % TRACKING, 0 LOST; 11.9 ms/frame mean, non-keyframes 10.1 ms, keyframes 31.4 ms (the only frames over the 33 ms budget); trajectory 1.82 % of extent vs truth (worse than 2 fps's 0.21 %; KLT drift suspected, unverified). **Known P2 problem exposed by ground truth:** on this clip the plane P2 labels `floor` is the far wall in every run (COLMAP's too) — only ~60–80 floor points exist in any cloud — so room dimensions for this clip measure the wrong surface. Not fixed; belongs to P2.
*   **Step 3 — P2 in memory (`docs/live_tracking.md` §8, history §29):** `geometry/api.py::build_room_model(points, cameras, options, seed)` returns the room_model dict / per-plane inlier indices / statistics without files; `geometry/incremental.py::IncrementalRoomModel.update(points, cameras, now)` re-fits a growing cloud with growth + time gating and an explicit empty result below `min_points`. `pipeline.main()` is a thin wrapper proven **exactly** equivalent to the pre-refactor output by replaying recorded RANSAC draws (fixtures in `tests/fixtures/p2/`). Known limit: Open3D 0.20's `segment_plane` ignores `o3d.utility.random.seed`, so `--seed` cannot make `room_model.json` byte-reproducible; a seeded numpy RANSAC in `extract_dominant_planes` is the fix, owned by P2. Timing: 0.014 s (900 pts) → 0.070 s (45 k pts). Backend tests 163.
*   **Step 2 — WebSocket live session (`docs/live_tracking.md` §9, history §30):** `WS /live/{id}` on the FastAPI app (`api/live.py` → `live/session.py::LiveSession`): JPEG frames in, a status per processed frame out (state, counts, pose or null, `twin_update` only when `IncrementalRoomModel` re-fitted the active segment), newest-frame-wins backpressure with `dropped` counted, `{"cmd":"finish"}` → export + P2/scene graph/twin into `<outputs>/<id>` registered as a normal session (never-initialised → `live_tracking: failed`, honest twin). `GET /live`, `DELETE /live/{id}`; `scripts/replay_live.py` streams a file. Verified for real against uvicorn with the 30 fps clip (360 frames, 0 dropped, 8 twin updates, all stages success). Backend tests 176, frontend 16. Phone client is the next step.
*   **Steps 4+5 — Live screen (`docs/live_tracking.md` §10, history §31, human test `docs/live_android_checklist.md`):** `#/live` in the frontend streams camera or a video file to `WS /live/{id}` (10 fps, ≤ 640 wide, JPEG 0.7, never queues; client skips and server drops both shown), big INITIALIZING / TRACKING / LOST banner, status strip, `Viewer3D` redrawn on every `twin_update` with live points from `GET /live/{id}/cloud`, hand-off to the session view on finish. Verified for real in headless Chrome via DevTools (file source: TRACKING at 2 s, 8 twin updates, planes drawn, finish → session view; fake camera: getUserMedia works, stays INITIALIZING). Android manifest has CAMERA; `cap sync` done; **emulator/phone untested**. vitest 35, backend 176.
