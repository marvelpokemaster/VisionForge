# VisionForge — Project State & Reality Check

## 1. Executive Summary
VisionForge is a **purely classical computer vision** monocular 3D room reconstruction and digital twin platform.

* **Repository State:** Branch `main`, HEAD commit `0a94db7` + local Phase 3 stabilization.
* **Testing Status:**
  * **Backend (Python):** 190 passed, 1 skipped, 0 failed (100% green).
  * **Frontend (Vitest):** 11 test files, 64 passed (100% green).
  * **Build:** Frontend builds cleanly (`proxychains npm run build`).
* **Milestone Reached:** Phase 1 (Ingestion & Offline SfM), Phase 2 (Geometry, Scene Graph, Twin API, Three.js Web Viewer), and Phase 3 (Live Monocular Tracking & Real-Time Geometry over WebSocket) are complete, stabilized, and verified.
* **Phase 4 Status:** In Progress — Building interactive metric calibration and floor clearance / 3D furniture placement.

---

## 2. Subsystem Reality Check

| Subsystem | Actual Implementation Status | Verification Level | Notes |
| :--- | :--- | :--- | :--- |
| **P0 Ingestion** | Implemented | Physical Real Video | Frame extraction, blur detection (`data/input/room.mp4`). |
| **P1 Offline SfM** | Implemented | Physical Real Video | SIFT, Lowe ratio, Essential matrix, PyCOLMAP (`sparse_cloud.ply`). |
| **P2 Batch Geometry** | Implemented | Physical Real Video | DBSCAN, RANSAC planes, boundaries, intersections, classifications. |
| **P2 Incremental** | Implemented | Synthetic & Live Device | `IncrementalRoomModel` throttles refitting on growing clouds. |
| **P3 Scene Graph** | Implemented | Physical Real Video | Hierarchical graph, typed edges with supporting metrics, query engine. |
| **P4 Digital Twin** | Implemented | Physical Real Video | `twin.json` bundling all models and provenance. |
| **FastAPI Backend** | Implemented | Automated Integration | REST endpoints (`/sessions`, `/cloud`), path traversal checks, CORS. |
| **FastAPI WebSocket** | Implemented | Synthetic & Live Device | `/live/{id}` frame pump, newest-wins backpressure, status stream. |
| **Frontend Web Viewer** | Implemented | Automated & Browser | Three.js canvas, colored planes, orbit controls, camera frustums. |
| **Android Client** | Implemented | Physical Device | Capacitor 8 app, Camera permission, live WebSocket streaming. |
| **Persistence** | Implemented | Automated Unit | Local JSON default; Supabase mock verified. |
| **Metric Scale Calibration** | In Progress | Manual / API | Scaling factor applied in room model; UI calibration workflow in progress. |
| **Furniture Clearance & Fitting** | In Progress | Pure Classical Geometry | 2D floor polygon projection, bounding box collision checks, 3D placement. |

---

## 3. Active Known Issues & Blockers

1. **Monocular Pure Rotation Limit:**
   * Monocular SLAM requires translational parallax to triangulate 3D points. Rotating the phone in place without sideways movement produces zero baseline and causes tracking initialisation to wait.
2. **Open3D Hash-Based Voxel Determinism:**
   * Open3D's C++ `voxel_down_sample` uses an unordered hash map, which causes slight point index permutations across disparate C++ runtimes. Fixtures are now verified and aligned with the current platform runtime.
3. **Hardware Accelerometer Fusion:**
   * Live streaming currently estimates camera gravity from optical poses. Direct phone IMU injection is scheduled for Phase 4 scale / orientation augmentation.

---

## 4. Current Work in Progress
* Implementing Phase 4.1: Metric scale calibration API and frontend controls.
* Implementing Phase 4.2: Classical 2D free-space floor polygon calculation and obstacle clearance.
* Implementing Phase 4.3: 3D interactive furniture placement and "Can It Fit?" clearance validator in the viewer.
