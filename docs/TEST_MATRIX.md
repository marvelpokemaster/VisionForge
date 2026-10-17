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
| **P2 In-Memory API** | `tests/test_geometry_api.py` | Automated Integration | **PARTIAL** | 7 passed, 4 failed. (4 failures are fixture JSON comparisons where up-axis sign flipped). |
| **P2 Incremental Model** | `tests/test_geometry_incremental.py` | Automated Unit | **PASS** | 7/7 tests pass (time/growth gating, empty cloud handling). |
| **P3 Spatial Graph** | `tests/test_spatial.py` | Automated Unit | **PASS** | 43/43 tests pass (adjacency, angles, intersections, inside checks). |
| **P3 Query Engine** | `tests/test_spatial.py` | Automated Synthetic | **PASS** | Keyword and regex matching, dimension extraction, unsupported fallback. |
| **P4 Digital Twin** | `tests/test_twin.py`, `test_twin_from_parts.py` | Automated Unit | **PASS** | 10/10 tests pass (round-trip JSON serialization, provenance tracking). |
| **FastAPI REST API** | `tests/test_api.py` | Automated Integration | **PASS** | 27/27 tests pass (sessions, path traversal protection, query dispatch, CORS). |
| **FastAPI Persistence** | `tests/test_persistence.py` | Automated Unit | **PASS** | 26/26 tests pass (LocalJsonBackend & Supabase mock). |
| **Phase 3 Live Tracker Core** | `tests/test_live_tracker.py` | Automated Synthetic | **PASS** | 10/10 tests pass (KLT tracking, PnP, keyframe decision gate). |
| **Phase 3 Live Timing** | `tests/test_live_timing.py` | Automated Unit | **PASS** | 3/3 tests pass (frame interval measurement, percentiles). |
| **Phase 3 Live WebSocket** | `tests/test_live_ws.py` | Automated Integration | **PASS** | 4/4 tests pass (frame pump, status delivery, finish & export). |
| **Phase 3 Replay Tooling** | `tests/test_live_recording.py` | Automated Unit | **PASS** | 2/2 tests pass (frame saving, offline replay via CLI). |
| **Trajectory Evaluation** | `tests/test_compare_trajectories.py` | Automated Synthetic | **PASS** | 7/7 tests pass (Umeyama sim(3) alignment, RMSE). |
| **Frontend Selectors** | `frontend/src/lib/selectors.test.ts` | Frontend Unit | **PASS** | 9/9 tests pass (session filtering, plane sorting). |
| **Frontend Frame Utils** | `frontend/src/lib/frames.test.ts` | Frontend Unit | **PASS** | 7/7 tests pass (3D room coordinate transformations). |
| **Frontend Live Status** | `frontend/src/live/status.test.ts` | Frontend Unit | **PASS** | 6/6 tests pass (state transitions, banner messages). |
| **Frontend Live Pump** | `frontend/src/live/pump.test.ts` | Frontend Unit | **PASS** | 7/7 tests pass (frame dropping, canvas rendering). |
| **Frontend Back Button** | `frontend/src/lib/backButton.test.ts` | Frontend Unit | **PASS** | 3/3 tests pass (Capacitor Android back button navigation). |
| **Desktop Web Viewer** | Manual browser test | Headless Chrome | **PASS** | Headless Chrome verified: 3D point cloud, colored planes, orbit controls. |
| **Android Emulator** | Manual emulator test | Android Emulator | **PASS** | Virtual camera capture, WS connection, status banner, failed-session listing. |
| **Physical Phone Hardware** | Physical device test | iQOO Neo 7 Device | **PASS** | Session `live-1792149775026`: 219 frames streamed over Wi-Fi, 986 map points, 7 planes fitted live. |

---

## 3. Known Deficiencies & Caveats

1. **4 Pytest Fixture Failures (`tests/test_geometry_api.py`):**
   * Pre-refactor fixture JSON files (`tests/fixtures/p2/*/room_model_reference.json`) recorded an older up-axis normal before architectural heuristics were tuned. `build_room_model` and `pipeline.main()` agree to tolerance, but fail exact string equality with the old fixture files.
2. **Pure Rotation Failure:**
   * Monocular vision cannot triangulate depth without translational motion (parallax). Rotating the phone in place produces zero parallax, causing `INITIALIZING` or `LOST` states. Users must translate (walk sideways).
3. **Scale Ambiguity:**
   * All distances are in unscaled reconstruction units unless calibrated via `--reference-distance` or intrinsics calibration.
4. **Up-Axis Arbitration Bug:**
   * On live mobile scans, plane heuristics with confidence 0.56 can override camera gravity at confidence 0.999. Gravity must be given precedence.
