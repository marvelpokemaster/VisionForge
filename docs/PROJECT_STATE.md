# VisionForge — Project State & Reality Check

## 1. Executive Summary
VisionForge is a **purely classical computer vision** monocular 3D room reconstruction and digital twin platform.

* **Repository State:** Branch `feature/phase4-furniture-scale`, HEAD commit `a896146` (`fix(mobile,clearance): physical device runtime hardening, boundary contact clearance, and scale calibration validation`).
* **Testing Status:**
  * **Backend (Python):** 206 passed, 1 skipped, 0 failed (100% green in 24.22s).
  * **Frontend (Vitest):** 12 test files, 70 passed (100% green in 589ms).
  * **Build:** Frontend builds cleanly (`proxychains npm run build`).
  * **Mobile Sync:** Capacitor 8 synced (`proxychains npx cap sync android`).
  * **Android Build:** `BUILD SUCCESSFUL in 2s` (`assembleDebug`).
  * **Physical Device:** Installed and verified on physical Redmi Note 13 5G (`rwkbgmhir4c6vch6`) with real-time UI interactions, 3D viewing, furniture placement, scale calibration, and live tracking navigation. Screenshots preserved in `docs/results/phase4_mobile_verification/`.
* **Milestone Reached:** 
  * Phase 1: Ingestion & Offline SfM (Complete & Verified).
  * Phase 2: Batch Geometry, Scene Graph, Digital Twin, Three.js Web Viewer (Complete & Verified).
  * Phase 3: Real-Time Live Monocular Tracking over WebSocket & Android Streaming (Complete & Verified on physical hardware).
  * Phase 4: Metric Scale Calibration, 2D Floor Clearance Engine, 3D Interactive Furniture Placement & "Can It Fit?" Auto-Pack Analyzer (Complete & Verified on physical device).

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
| **Metric Scale Calibration** | Implemented | Automated Unit & API | Interactive width/length/two-point calibration; re-scales 3D room. |
| **Furniture Clearance & Fitting** | Implemented | Pure Classical Geometry | 2D SAT collision, boundary polygon containment, 3D boxes, auto-pack. |

---

## 3. Active Known Issues & Blockers

1. **Monocular Pure Rotation Limit:**
   * Monocular SLAM requires translational parallax to triangulate 3D points. Rotating the phone in place without sideways movement produces zero baseline and causes tracking initialisation to wait.
2. **Open3D Hash-Based Voxel Determinism:**
   * Open3D's C++ `voxel_down_sample` uses an unordered hash map, which causes slight point index permutations across disparate C++ runtimes. Fixtures are now verified and aligned with the current platform runtime.
3. **Hardware Accelerometer Fusion:**
   * Live streaming currently estimates camera gravity from optical poses. Direct phone IMU injection is scheduled for scale / orientation augmentation.

---

## 4. Current Work in Progress
* Ready for user testing on physical Android device and real room scans.
