# VisionForge — Verification Matrix & Test Evidence

## 1. Test Execution Commands

### Backend Automated Tests
```bash
source venv/bin/activate
pytest -q
```

### Frontend Automated Tests
```bash
cd frontend
npm test
```

### Frontend Production Build
```bash
cd frontend
npm run build
```

---

## 2. Test Execution & Evidence Matrix

| Component / Subsystem | Test Command / Suite | Classification | Status | Evidence / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **P0 Ingestion** | `tests/test_extract_frames.py` | Automated Unit | **PASS** | 3/3 tests pass (frame count, FPS, blur filter). |
| **P0 Real Video** | `python -m visionforge.video ...` | Physical Video | **PASS** | Processed `data/input/room.mp4`, extracted 22 clean frames (`p0/metadata.json`). |
| **P1 Epipolar Geometry** | `tests/test_reconstruction.py` | Automated Unit | **PASS** | 2/2 tests pass (SIFT matching, Essential Matrix). |
| **P1 Offline SfM** | `outputs/final_demo/p1/` | Physical Video | **PASS** | Registered 24 real cameras, 1,705 3D points, generated `sparse_cloud.ply`. |
| **P2 Geometry Pipeline** | `tests/test_geometry.py` | Automated Synthetic | **PASS** | 6/6 tests pass (DBSCAN, RANSAC, coplanar merge). |
| **P2 Classification** | `tests/test_geometry_classification.py` | Automated Unit | **PASS** | 3/3 tests pass (floor/wall/ceiling heuristics). |
| **P2 In-Memory API** | `tests/test_geometry_api.py` | Automated Integration | **PASS** | 11/11 tests pass (fixtures stabilized in commit `8c418f3`). |
| **P2 Incremental Model** | `tests/test_geometry_incremental.py` | Automated Unit | **PASS** | 7/7 tests pass (time/growth gating, empty cloud handling). |
| **P3 Spatial Graph** | `tests/test_spatial.py` | Automated Unit | **PASS** | 43/43 tests pass (adjacency, angles, intersections, inside checks). |
| **P3 Query Engine** | `tests/test_spatial.py` | Automated Synthetic | **PASS** | Keyword and regex matching, dimension extraction, unsupported fallback. |
| **P4 Metric Scale Calibration** | `tests/test_scale_calibration.py` | Automated Unit | **PASS** | 7/7 tests pass (uniform scaling, 3D vertices, two-point, input validation). |
| **P4 Floor Clearance Engine** | `tests/test_furniture_clearance.py` | Automated Unit | **PASS** | 8/8 tests pass (SAT 2D collision, flush wall boundary contact, concave rooms, auto-pack). |
| **P4 Digital Twin** | `tests/test_twin.py`, `test_twin_from_parts.py` | Automated Unit | **PASS** | 10/10 tests pass (round-trip JSON serialization, provenance tracking). |
| **FastAPI REST API** | `tests/test_api.py` | Automated Integration | **PASS** | 32/32 tests pass (sessions, cloud, furniture catalog, placement validation, auto-pack, calibration, e2e scale calibration and boundary clearance). |
| **FastAPI Persistence** | `tests/test_persistence.py` | Automated Unit | **PASS** | 26/26 tests pass (LocalJsonBackend & Supabase mock). |
| **Phase 3 Live Tracker Core** | `tests/test_live_tracker.py` | Automated Synthetic | **PASS** | 10/10 tests pass (KLT tracking, PnP, keyframe decision gate). |
| **Phase 3 Live Timing** | `tests/test_live_timing.py` | Automated Unit | **PASS** | 3/3 tests pass (frame interval measurement, percentiles). |
| **Phase 3 Live WebSocket** | `tests/test_live_ws.py` | Automated Integration | **PASS** | 4/4 tests pass (frame pump, status delivery, finish & export). |
| **Phase 3 Replay Tooling** | `tests/test_live_recording.py` | Automated Unit | **PASS** | 2/2 tests pass (frame saving, offline replay via CLI). |
| **Trajectory Evaluation** | `tests/test_compare_trajectories.py` | Automated Synthetic | **PASS** | 7/7 tests pass (Umeyama sim(3) alignment, RMSE). |
| **Frontend Selectors** | `frontend/src/lib/selectors.test.ts` | Frontend Unit | **PASS** | 9/9 tests pass (session filtering, plane sorting). |
| **Frontend Frame Utils** | `frontend/src/lib/frames.test.ts` | Frontend Unit | **PASS** | 7/7 tests pass (3D room coordinate transformations). |
| **Frontend Session Load** | `frontend/src/lib/sessionLoad.test.ts` | Frontend Unit | **PASS** | 6/6 tests pass (handling undefined/null geometry). |
| **Frontend Furniture API** | `frontend/src/lib/furnitureApi.test.ts` | Frontend Unit | **PASS** | 6/6 tests pass (validation, auto-pack, scale calibration). |
| **Frontend Live Status** | `frontend/src/live/status.test.ts` | Frontend Unit | **PASS** | 6/6 tests pass (state transitions, banner messages). |
| **Frontend Live Pump** | `frontend/src/live/pump.test.ts` | Frontend Unit | **PASS** | 7/7 tests pass (frame dropping, canvas rendering). |
| **Frontend Back Button** | `frontend/src/lib/backButton.test.ts` | Frontend Unit | **PASS** | 3/3 tests pass (Capacitor Android back button navigation). |
| **Desktop Web Viewer** | Manual browser test | Headless Chrome | **PASS** | Headless Chrome verified: 3D point cloud, colored planes, orbit controls. |
| **Android Emulator** | Manual emulator test | Android Emulator | **PASS** | Virtual camera capture, WS connection, status banner, failed-session listing. |
| **Physical Phone Hardware** | Physical device test | Redmi Note 13 5G & iQOO Neo 7 | **PASS** | Verified end to end: APK install, sessions list, 3D Three.js viewer, furniture placement, boundary collision check, scale calibration, and live tracking navigation. Screenshots preserved in `docs/results/phase4_mobile_verification/`. |

---

## 3. Known Deficiencies & Caveats

1. **Zero Pytest Failures:** All 207 backend tests passing (1 skipped: optional PyCOLMAP end-to-end on synthetic data when running headless).
2. **Monocular Parallax Requirement:** Live tracking requires sideways translational motion to triangulate 3D points; pure rotational motion keeps tracker in `INITIALIZING`.
3. **Open3D Hash-Based Voxel Determinism:** Addressed via stabilized platform runtime fixtures.
