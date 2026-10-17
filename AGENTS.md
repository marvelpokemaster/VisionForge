# VisionForge — Agent Operating Protocol & Instructions

## 1. Product Vision & Roadmap
VisionForge is a **purely classical computer vision** system designed to turn smartphone video into a live, interactive 3D digital twin of an indoor space.

The ultimate user goal is an application where a user can scan a room with their smartphone, obtain an accurate 3D model with real metric measurements, identify usable floor space, and test whether real-world furniture fits.

### Four-Phase Roadmap
1. **Phase 1 — Ingestion & Classical Offline SfM (P0/P1):** Video frame extraction, SIFT/ORB feature matching, geometric verification (RANSAC, Essential matrix), and sparse reconstruction via PyCOLMAP. *(Complete & Verified)*
2. **Phase 2 — Room Geometry, Spatial Graph & Digital Twin (P2/P3/P4):** Planar RANSAC surface extraction, architectural plane classification, boundary polygon extraction, plane-plane intersections, spatial scene graph queries, FastAPI backend, Three.js viewer, and dual persistence. *(Complete & Verified)*
3. **Phase 3 — Real-Time Live Monocular Tracking & Streaming:** Phone camera streaming over WebSocket, KLT/PnP real-time tracker, incremental room geometry refitting, phone client UI via Capacitor, and offline replay tooling. *(Core Merged; Stabilization & Real Data Tuning Active)*
4. **Phase 4 — Mobile Room Measurement & Furniture Fitting:** Real metric scale calibration (user reference / IMU integration), clean floor clearance and usable free-space polygon calculation, 3D furniture bounding box placement, wall/obstacle collision detection, and standalone mobile UX. *(Planned / Active)*

---

## 2. Hard Technical Constraint: Classical CV Only
VisionForge is strictly **CLASSICAL COMPUTER VISION ONLY**.

* **Allowed:** OpenCV, NumPy, Open3D, PyCOLMAP, SIFT, ORB, FAST, KLT optical flow, FLANN/BF matching, Lowe's ratio test, RANSAC/USAC, Essential/Fundamental matrix estimation, PnP, triangulation, bundle adjustment, PCA, geometric plane fitting, and graph algorithms.
* **FORBIDDEN:** Neural networks, deep learning models, pretrained weights, and learned estimators. Specifically: **NO YOLO, SAM, CLIP, DINO, SuperPoint, SuperGlue, LightGlue, ALIKED, LoFTR, learned depth estimation, neural SLAM, or AI object detection.**
* Do not introduce machine learning or AI models simply because they make a computer vision problem easier.

---

## 3. Technology Stack & Architectural Boundaries
* **Backend:** Python 3.12+ (tested up to 3.14), OpenCV (`opencv-python`), Open3D (`open3d`), PyCOLMAP (`pycolmap`), NumPy, FastAPI, Uvicorn, HTTPX.
* **Frontend:** React 19, TypeScript 5.9, Vite 7, Three.js 0.186, Vitest.
* **Mobile:** Capacitor 8 (`@capacitor/core`, `@capacitor/android`, `@capacitor/app`) wrapping the Vite/React frontend.
* **Persistence:** `LocalJsonBackend` (default zero-config in `outputs/`) and `SupabaseBackend` (opt-in via `SUPABASE_URL` and `SUPABASE_KEY`).

### Key Architectural Boundaries
* **Client vs Backend:** The mobile app acts as a capture/rendering client communicating over HTTP and WebSockets (`/live/{id}`) with the Python backend. Heavy vision algorithms run on the server.
* **Data Flow:** Video/Stream → Classical Tracker / SfM → Point Cloud → Geometry Pipeline (`build_room_model`) → Spatial Scene Graph → Digital Twin (`twin.json`) → API (`/sessions`) → Frontend / Mobile Viewer.
* **Point Cloud Storage:** `twin.json` references the sparse point cloud (`sparse_cloud.ply`) by relative filesystem path; raw 3D point coordinates are NEVER embedded directly into JSON or database payloads.

---

## 4. Development & Testing Commands

### Backend (Python)
Always activate the virtual environment:
```bash
source venv/bin/activate
```
* **Run all backend tests:** `pytest` (configuration in `pytest.ini`)
* **Run reconstruction (offline):**
  ```bash
  python -m visionforge.cli reconstruct --video data/input/room.mp4 --output outputs/my_run --input-type real
  ```
* **Run live tracker on video/webcam:**
  ```bash
  python -m visionforge.cli live --video data/input/room.mp4 --output outputs/live_run
  ```
* **Run live backend server:**
  ```bash
  uvicorn visionforge.api.app:app --host 0.0.0.0 --port 8000
  ```
* **Replay recorded live frames:**
  ```bash
  python scripts/replay_live.py --frames-dir outputs/<session_id>/frames/ --ws-url ws://localhost:8000/live/replay
  ```
* **Calibrate camera intrinsics:**
  ```bash
  python -m visionforge.cli calibrate --video <clip.mp4> --output outputs/calibration.json
  ```

### Frontend & Mobile
* **Install dependencies:** Always use `proxychains` if in the user's restricted network environment:
  ```bash
  cd frontend && proxychains npm install
  ```
* **Run frontend tests:** `cd frontend && npm test`
* **Build frontend:** `cd frontend && npm run build`
* **Sync Capacitor Android assets:** `cd frontend && npx cap sync android`

---

## 5. Git & Supabase Safety Rules
* **Never commit secrets:** Never commit `.env`, service-role keys, or credentials.
* **Clean status:** Always check `git status` before and after modifying files. Do not discard user changes or force-push.
* **Database safety:** Supabase persistence is opt-in. Migrations live in `supabase/migrations/`. Do not perform destructive schema drops or alter remote databases without explicit instructions. Never place Supabase secret/service-role keys in client-side mobile/frontend code.

---

## 6. Mandatory Agent Workflow
Every AI agent working on VisionForge MUST follow these steps:
1. **Context Initialization:** Read `AGENTS.md`, `docs/PROJECT_STATE.md`, and `docs/SESSION_HANDOFF.md` before doing anything else.
2. **Execute Single Coherent Tasks:** Implement one modular task at a time. Do not make sweeping refactors without verification.
3. **Verify Honestly:** Run automated tests (`pytest`, `npm test`) and record whether evidence is **synthetic**, **offline real-video**, or **physical mobile hardware**. Never claim something is verified without proof.
4. **Update Authoritative Docs:** At the conclusion of any task, update `docs/PROJECT_STATE.md`, `docs/PHASE_PLAN.md`, `docs/TEST_MATRIX.md`, and refresh `docs/SESSION_HANDOFF.md`.

---

## 7. Authoritative Documentation Index
* **[`docs/PROJECT_STATE.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/PROJECT_STATE.md):** Current implementation reality, passing tests, and known issues.
* **[`docs/ARCHITECTURE.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/ARCHITECTURE.md):** System architecture, data flow, coordinate systems, and API protocols.
* **[`docs/DECISIONS.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/DECISIONS.md):** Architecture Decision Records (ADRs).
* **[`docs/PHASE_PLAN.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/PHASE_PLAN.md):** Roadmap delivery checklist and acceptance criteria.
* **[`docs/TEST_MATRIX.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/TEST_MATRIX.md):** Test execution matrix and verification evidence.
* **[`docs/SESSION_HANDOFF.md`](file:///home/marvelpokemaster/Documents/codes/projects/VisionForge/docs/SESSION_HANDOFF.md):** Immediate task continuation point for incoming agents.
