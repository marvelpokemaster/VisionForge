# VisionForge — Session Handoff & Immediate Continuation Point

## 1. Current Phase & Task
* **Current Phase:** Phase 3 Stabilization ➔ Phase 4 Implementation.
* **Current Task:** 
  1. Fix Python 3.14 compatibility in `src/visionforge/geometry/pipeline.py` (completed: escaped `%` to `%%`).
  2. Establish authoritative persistent project memory (`AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PHASE_PLAN.md`, `docs/TEST_MATRIX.md`, `docs/PROJECT_STATE.md`, `docs/SESSION_HANDOFF.md`).
  3. Prepare for Phase 4 (Metric Scale Calibration, Free-Space Floor Polygon, Furniture Placement).

---

## 2. Git & Repository Context
* **Current Branch:** `main` (synchronized with `origin/main`).
* **Latest Upstream Commit:** `0a94db7` (*docs(live): §11 first real-phone run + results record; protocol/report fields; checklist; history §33; state §9*).
* **Working Tree State:** Clean aside from documentation and the Python 3.14 argparse `%` fix.

---

## 3. Files Changed in this Session
* `src/visionforge/geometry/pipeline.py`: Escaped `%` as `%%` in argparse help strings to eliminate `TypeError: %o format: an integer is required, not dict` under Python 3.14.
* `src/visionforge/geometry/plane_fitting.py`: Separated plane-derived sources to avoid outvoting physical camera gravity prior, and relaxed agreement clustering angle to 22.5°.
* `frontend/src/lib/frustum.ts` & `Viewer3D.tsx`: Fixed parameter parsing for `PINHOLE` (`[fx, fy, cx, cy]`) vs `SIMPLE_RADIAL` (`[f, cx, cy, k]`). Added `frontend/src/lib/frustum.test.ts`.
* `tests/test_geometry_classification.py`: Added `test_architectural_classifier_camera_gravity_overrides_deviating_planes`.
* `tests/fixtures/p2/`: Re-recorded RANSAC draws and reference JSON files matching the current platform hash table ordering.
* Root persistent documentation created and updated: `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PHASE_PLAN.md`, `docs/TEST_MATRIX.md`, `docs/PROJECT_STATE.md`, `docs/SESSION_HANDOFF.md`.

---

## 4. Commands Executed & Actual Results
1. `proxychains npm test` (in `frontend/`): **11 test files, 64 passed tests (100% green)**.
2. `proxychains npm run build` (in `frontend/`): **Clean production build (0 errors)**.
3. `source venv/bin/activate && PYTHONPATH=src pytest`: **190 passed, 1 skipped, 0 failed (100% green)**.

---

## 5. Outstanding Failures & Investigations
* **Zero test failures.** All 190 Python tests and 64 frontend tests are green.
* Up-axis gravity arbitration confirmed via dedicated unit test.
* Camera frustums in Three.js correctly render PINHOLE camera aspect ratios.

---

## 6. Next Concrete Actions (Phase 4 Implementation)

1. **Phase 4.1: Metric Scale Calibration Engine:**
   * Build backend endpoint `POST /sessions/{id}/calibrate_scale` allowing the client to provide a known real-world dimension (e.g. room width, length, or door width) to apply an exact scale factor $s$ to all reconstructed 3D vertices, planes, and room dimensions.
2. **Phase 4.2: Classical Floor Clearance Engine:**
   * Calculate the 2D floor boundary polygon in room coordinates ($Y=0$).
   * Project all non-floor planes/obstacles onto the 2D floor polygon to derive the unobstructed free-space polygon using classical 2D computational geometry (no ML).
   * Define standard furniture bounding boxes (Queen Bed, Single Bed, Desk, 3-Seater Sofa, Dining Table) and implement 2D polygon collision testing.
3. **Phase 4.3: Interactive 3D Furniture Placement in Frontend:**
   * Add a furniture catalog drawer in the viewer UI with real-world dimensions.
   * Allow interactive placement, rotation, and snap-to-floor of furniture models.
   * Provide immediate visual validation: green box when placed inside unobstructed floor free space, red box when intersecting walls or obstacles, plus a "Can It Fit?" auto-placement analyzer.
