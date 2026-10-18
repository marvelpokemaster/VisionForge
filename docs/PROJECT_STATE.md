# VisionForge — Project State & Reality Check

## 1. Executive Summary
VisionForge is a **purely classical computer vision** monocular 3D room reconstruction and digital twin platform.

* **Repository State:** Branch `feature/phase4-furniture-scale`.
* **Testing Status:**
  * **Backend (Python):** 231 passed, 3 skipped, 0 failed (100% green in 23.60s).
  * **Frontend (Vitest):** 12 test files, 73 passed (100% green in 578ms).
  * **Build:** Frontend builds cleanly (`npm run build` in 2.42s).
  * **Mobile Sync:** Capacitor 8 synced (`npx cap sync android` in 0.05s).
  * **Android Build:** `BUILD SUCCESSFUL in 2s` (`assembleDebug`, APK at `frontend/android/app/build/outputs/apk/debug/app-debug.apk`, 4.9 MB).
  * **Physical Device:** Installed and verified on physical Redmi Note 13 5G (`rwkbgmhir4c6vch6`) with real-time UI interactions, 3D viewing, furniture placement, scale calibration, and live tracking navigation. Screenshot verified. Device currently detached from USB (`adb devices` empty).
  * **Cloud Deployment & Persistence (Supabase):**
    * **Supabase Project:** Dedicated project `btpxwlquhjwjqoypqskm` (Status: `ACTIVE_HEALTHY`, Region: `ap-northeast-1`).
    * **Database Migrations:** Applied `0001_init.sql` and `0002_user_ownership_and_artifacts.sql` covering 9 tables (`sessions`, `room_models`, `scene_graphs`, `twins`, `measurements`, `experiment_results`, `processing_status`, `furniture_layouts`, `artifacts`) with Row Level Security (RLS) enabled on all tables.
    * **Storage Bucket:** Private bucket `visionforge-artifacts` (500 MB limit, RLS enabled for authenticated and service-role access) for binary PLY point clouds, models, and scan artifacts.
    * **Backend Persistence:** `SupabaseBackend` verified against live database and storage (session upsert, room model/twin versioning, furniture layout, artifact upload/download). Silent fallback in production is strictly blocked with `RuntimeError`.
    * **Client-Side Auth & Session:** Real Supabase Auth client integrated in web & Android app (`@supabase/supabase-js`, [`frontend/src/lib/supabase.ts`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/frontend/src/lib/supabase.ts)), with user sign-in/sign-up/sign-out UI (`AuthPanel.tsx`), session persistence, and automatic token synchronization across REST requests and live WebSocket streaming.
    * **Server-Side Auth & Ownership:** Supabase JWT verification via `client.auth.get_user(token)` with strict server-side ownership enforcement (403 Forbidden on cross-user access, 4401 on unauthenticated WebSockets in production).
    * **Hosted Web Application:** Deployed to Firebase Hosting at `https://visionforge-spatial.web.app` (HTTP/2 200).
    * **Docker Backend Deployment:** `render.yaml` configured with `VISIONFORGE_PERSISTENCE=supabase`, `SUPABASE_URL=https://btpxwlquhjwjqoypqskm.supabase.co`, `VISIONFORGE_REQUIRE_AUTH=1`, `VISIONFORGE_ENV=production`, and `VISIONFORGE_CORS_ORIGINS`.
* **Milestone Reached:** 
  * Phase 1: Ingestion & Offline SfM (Complete & Verified).
  * Phase 2: Batch Geometry, Scene Graph, Digital Twin, Three.js Web Viewer (Complete & Verified).
  * Phase 3: Real-Time Live Monocular Tracking over WebSocket & Android Streaming (Complete & Verified on physical hardware; up-axis fusion prioritized camera gravity; seeded deterministic RANSAC).
  * Phase 4: Metric Scale Calibration, 2D Floor Clearance Engine, 3D Interactive Furniture Placement, "Can It Fit?" Auto-Pack Analyzer, and Production Cloud Release (Complete & Verified).
* **Render Cloud Deployment (Production Backend):**
  * **Service:** `visionforge-spatial-api` (`srv-dbacnnjbc2fs73ata05g`)
  * **Public HTTPS URL:** `https://visionforge-spatial-api.onrender.com`
  * **Public WSS URL:** `wss://visionforge-spatial-api.onrender.com`
  * **Health Endpoint:** `GET /health` returning `200 OK`, `backend: "SupabaseBackend"`.
  * **Render MCP:** Configured and operational via `mcp_config.json` with official binary.
  * **Live E2E Verification:** All 6 live release gates (health check, JWT auth rejection, cross-user isolation, artifact persistence via Supabase Storage, furniture validation/auto-pack API, live WebSocket streaming with token) verified and green against the live Render service.
  * **Hosted Web Application:** Deployed to Firebase Hosting at `https://visionforge-spatial.web.app` (HTTP/2 200).
  * **Physical Android App:** Built debug APK (5.1 MB) installed and launched on connected Redmi Note 13 5G (`rwkbgmhir4c6vch6`), configured directly to `https://visionforge-spatial-api.onrender.com`.

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
