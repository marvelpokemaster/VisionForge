# VisionForge — Four-Phase Delivery Plan & Checklist

## Phase 1: Video Ingestion & Offline Classical Reconstruction
**Goal:** Process recorded monocular video into an accurate, sparse 3D point cloud and camera trajectory using classical SfM.

* [x] **P1.1 Video Frame Ingestion (`src/visionforge/video/extract_frames.py`)**
  * *Acceptance Criteria:* Ingest video, extract frames at specified FPS, reject blurry frames via Laplacian variance.
  * *Evidence:* Verified on synthetic clip and physical room video `data/input/room.mp4` (22 frames extracted).
* [x] **P1.2 Two-View Epipolar Geometry (`src/visionforge/reconstruction/two_view.py`)**
  * *Acceptance Criteria:* SIFT extraction, Lowe's ratio test matching (ratio < 0.75), Essential Matrix estimation via RANSAC, inlier ratio calculation.
  * *Evidence:* `outputs/final_demo/p1/two_view/` generated; 617 matches, 72.8% inliers.
* [x] **P1.3 Multi-View Incremental Reconstruction (`src/visionforge/reconstruction/incremental.py`)**
  * *Acceptance Criteria:* PyCOLMAP integration, full camera registration, 3D point triangulation, export `sparse_cloud.ply` and `cameras.json`.
  * *Evidence:* Verified on real video (24 cameras registered, 1,705 points triangulated).

---

## Phase 2: Room Geometry, Spatial Graph & Digital Twin
**Goal:** Extract semantic architectural planes from sparse points, build a spatial scene graph, create `twin.json`, and expose via REST API and 3D web viewer.

* [x] **P2.1 Point Cloud Preprocessing & Dominant Plane Fitting (`src/visionforge/geometry/`)**
  * *Acceptance Criteria:* Voxel downsampling, DBSCAN outlier removal, planar RANSAC extraction, coplanar segment merging.
  * *Evidence:* Merges split planes, produces clean bounding polygons and plane equations in `outputs/final_demo/p2/room_model.json`.
* [x] **P2.2 Architectural Surface Classification (`src/visionforge/geometry/plane_fitting.py`)**
  * *Acceptance Criteria:* Classify planes as `floor`, `wall`, or `ceiling` using normal vectors, camera gravity, and architectural support.
  * *Evidence:* 119 unit tests passing (`tests/test_geometry_classification.py`).
* [x] **P2.3 Spatial Scene Graph & Deterministic Query Engine (`src/visionforge/spatial/`)**
  * *Acceptance Criteria:* Generate hierarchical scene graph with typed edges (`parallel_to`, `perpendicular_to`, `adjacent_to`, `intersects`, `inside`) and answer architectural queries.
  * *Evidence:* 43 passing tests in `tests/test_spatial.py`; 107 edges generated for physical room.
* [x] **P2.4 Digital Twin Data Layer & Provenance (`src/visionforge/twin/digital_twin.py`)**
  * *Acceptance Criteria:* Generate `twin.json` bundling geometry, cameras, scene graph, and explicit scale/measurement provenance.
  * *Evidence:* `tests/test_twin.py` (9 passing tests).
* [x] **P2.5 FastAPI Backend (`src/visionforge/api/app.py`)**
  * *Acceptance Criteria:* Read-only REST server exposing sessions, PLY clouds, twins, and query execution with method allowlist.
  * *Evidence:* 27 passing tests in `tests/test_api.py`.
* [x] **P2.6 3D Web Viewer Frontend (`frontend/src/`)**
  * *Acceptance Criteria:* React 19 + Three.js viewer with orbit controls, plane rendering, camera frustums, and query panel.
  * *Evidence:* 16 passing tests in `frontend/src/lib/`.
* [x] **P2.7 Persistence Layer (`src/visionforge/persistence/`)**
  * *Acceptance Criteria:* Zero-config `LocalJsonBackend` and opt-in `SupabaseBackend`.
  * *Evidence:* 26 passing tests in `tests/test_persistence.py`.

---

## Phase 3: Real-Time Live Monocular Tracking & Streaming
**Goal:** Live smartphone camera streaming over WebSocket, online KLT/PnP tracking, incremental room geometry refitting, and real-time 3D twin visualization on the phone.

* [x] **P3.1 Classical Live Tracker Engine (`src/visionforge/live/runner.py`, `features.py`)**
  * *Acceptance Criteria:* Fast feature detection, KLT optical flow, parallax-gated two-keyframe initialization, PnP pose estimation against map, explicit `INITIALIZING | TRACKING | LOST` states.
  * *Evidence:* Verified on 30 fps synthetic clip and iQOO Neo 7 device session (`docs/results/live-1792149775026/`).
* [x] **P3.2 In-Memory Incremental Geometry (`src/visionforge/geometry/incremental.py`)**
  * *Acceptance Criteria:* `IncrementalRoomModel` refits planes on growing point clouds with time ($\ge 1.0$ s) and point growth ($\ge 100$ pts) throttling.
  * *Evidence:* 7 passing tests in `tests/test_geometry_incremental.py`.
* [x] **P3.3 Live WebSocket Session Protocol (`src/visionforge/api/live.py`)**
  * *Acceptance Criteria:* Bi-directional WebSocket (`/live/{id}`), frame ingestion, per-frame status delivery, twin updates.
  * *Evidence:* Verified in `tests/test_live_ws.py`.
* [x] **P3.4 Android Client via Capacitor (`frontend/android/`)**
  * *Acceptance Criteria:* Native Android container, CAMERA permissions, hardware back button navigation, live camera streaming.
  * *Evidence:* Successfully installed and streamed live frames from an iQOO Neo 7 Android phone.
* [x] **P3.5 Frame Recording & Offline Replay Tooling (`src/visionforge/live/recording.py`)**
  * *Acceptance Criteria:* Opt-in recording of received frames to disk for deterministic offline replay (`scripts/replay_live.py`).
  * *Evidence:* `tests/test_live_recording.py` passing.
* [ ] **P3.6 Stabilization & Geometry Arbitration (In Progress)**
  * *Task 1:* Prioritize camera gravity (confidence 0.999) over planar heuristics (confidence 0.56) in up-axis fusion.
  * *Task 2:* Resolve far-wall misclassification on low-floor-count clouds.
  * *Task 3:* Replace Open3D unseeded RANSAC with seeded NumPy RANSAC for deterministic reproducibility.
  * *Task 4:* Fix PINHOLE parameter reading order in `frontend/src/lib/frustum.ts`.

---

## Phase 4: Mobile Room Measurement, Usable Space & Furniture Fitting
**Goal:** Deliver the end-user product vision: scan a room with a smartphone, establish real metric scale, calculate usable floor space, and place/test 3D furniture.

* [x] **P4.1 Metric Scale Calibration Engine (`src/visionforge/spatial/calibration.py`)**
  * *Acceptance Criteria:* Intuitive calibration flow: interactive room width, length, or two-point reference measurement. Scale factor is applied to all measurements and digital twin coordinates.
  * *Evidence:* 7 unit tests pass in `tests/test_scale_calibration.py`; verified live on Redmi Note 13 5G (`✓ Metric (1 unit = 1.11m)`).
* [x] **P4.2 Floor Clearance & Usable Free-Space Polygon (`src/visionforge/spatial/clearance.py`)**
  * *Acceptance Criteria:* Project floor boundary polygon; validate furniture boundaries, boundary wall contacts, and greedy auto-packing.
  * *Evidence:* 8 tests pass in `tests/test_furniture_clearance.py` (SAT 2D, ray casting, flush wall contact, concave rooms).
* [x] **P4.3 Interactive Furniture Placement in Frontend (`FurniturePanel.tsx`, `Viewer3D.tsx`)**
  * *Acceptance Criteria:* UI catalog of common furniture (Queen Bed, Single Bed, Work Desk, Dining Table, Wardrobe, 3-Seat Sofa), step placement, angle rotation, and 3D Three.js boxes.
  * *Evidence:* 6 tests in `furnitureApi.test.ts`; verified on physical device.
* [x] **P4.4 Collision & Clearance Detection Engine (`src/visionforge/spatial/clearance.py`)**
  * *Acceptance Criteria:* Detect 2D intersections between furniture bounding boxes and room boundary walls or other furniture; render valid in green, collisions in red with explanatory reasons.
  * *Evidence:* Full coverage in `test_furniture_clearance.py` and device runtime screenshot.
* [x] **P4.5 Standalone Mobile Experience (`frontend/android/`)**
  * *Acceptance Criteria:* Fully operable on physical smartphone touchscreen with real-time feedback, responsive controls, and live WebSocket streaming.
  * *Evidence:* Successfully installed and executed on physical Redmi Note 13 5G (`rwkbgmhir4c6vch6`).
