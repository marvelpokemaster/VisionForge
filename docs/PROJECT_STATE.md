# VisionForge — Project State & AI Handoff

## 1. Project Overview
**VisionForge** is an indoor digital twin system built entirely on classical computer vision. The ultimate project goal is an "Iron Man" style application where a user points an Android phone camera at a room, and the system performs real-time classical visual tracking, sparse 3D reconstruction, geometric plane extraction, spatial scene graph generation, and displays a live digital twin of the environment.

**CRITICAL CONSTRAINT:** The project is **CLASSICAL COMPUTER VISION ONLY**.

## 2. Hard Technical Constraints

**Allowed:**
- OpenCV, Open3D, COLMAP / PyCOLMAP
- SIFT, ORB, FAST, KLT optical flow
- BF/FLANN matching, Lowe ratio test
- RANSAC plane fitting and geometric verification
- Fundamental / Essential Matrix, PnP, triangulation, bundle adjustment
- Classical SfM / SLAM
- PCA, geometric filtering, graph-based spatial reasoning

**Forbidden:**
- YOLO, SAM, CLIP, DINO
- SuperPoint, SuperGlue, LightGlue, ALIKED, LoFTR
- Learned depth, neural reconstruction (NeRF, Gaussian Splatting)
- Pretrained vision models, neural SLAM, AI-based object detection
- Do not introduce ML merely because it makes the problem easier.

## 3. Current Architecture
The backend is a purely Python-based offline and live-tracking pipeline; a React/TypeScript frontend (`frontend/`) consumes it entirely through the API.
- **Directories:** 
  - `src/visionforge/video/`: Frame extraction (P0).
  - `src/visionforge/reconstruction/`: Feature matching, epipolar geometry, PyCOLMAP incremental SfM (P1).
  - `src/visionforge/geometry/`: Point cloud cleaning, RANSAC plane extraction, room modeling (P2).
  - `src/visionforge/spatial/`: Scene graph generation, shared geometry utilities, spatial queries, and Open3D visualization (P3/P4).
  - `src/visionforge/twin/`: `DigitalTwin` data layer — bundles room_model/cameras/scene_graph + provenance into `twin.json` (see §22).
  - `src/visionforge/api/`: Read-only + persist FastAPI backend over `outputs/<run>/` and the configured `PersistenceBackend` (see §23, §25).
  - `src/visionforge/persistence/`: `PersistenceBackend` interface, `LocalJsonBackend` (default, zero-config, writes under `outputs/`) and `SupabaseBackend` (opt-in via `SUPABASE_URL`/`SUPABASE_KEY`). See §25 and `docs/supabase.md`.
  - `src/visionforge/live/`: OpenCV KLT + 5-point algorithm visual odometry (P4).
  - `frontend/`: Vite + React + TypeScript + three.js digital twin viewer, talking only to the API (see §24). Pinned `package.json` versions; `src/lib/frames.ts` holds the one client-side room-frame transform (for the point cloud PLY — everything else is served pre-transformed).
- **Data Flow:** Video -> Frames -> Features -> Sparse Cloud -> Planar Geometry -> JSON Scene Graph -> `twin.json` -> API (+ optional persist to Supabase/local JSON) -> `frontend/` viewer (and the standalone Open3D viewer, still available via `cli.py reconstruct`).
- **Dependencies:** `opencv-python`, `numpy`, `open3d`, `pycolmap`, `pytest`, `fastapi`, `uvicorn`, `httpx` (test client), `supabase` (only imported when `SupabaseBackend` is actually selected); `frontend/`: `react`, `three`, `vite`, `typescript`, `vitest` (see `frontend/package.json` for pinned versions).
- **CLI Entry Point:** `src/visionforge/cli.py`
- **Android/Mobile Components:** None currently exist.
- **Supabase Integration:** MCP server configured in the developer environment, but **zero** integration exists in the actual source code.

## 4. Prototype History

### P0 — Video Ingestion
- **Implemented:** Frame extraction, keyframe selection via variance of Laplacian (sharpness), metadata extraction, contact sheet generation.
- **Verification:** Tested via automated tests on synthetic/dummy video frames, and on a synthetic rendered room video (`data/input/synthetic_box_room.mp4`). No physical-camera video has been run through it yet.

### P1 — Vision Core / Reconstruction
- **Implemented:** SIFT feature extraction, FLANN matching, ratio test, epipolar filtering (Fundamental matrix), and incremental SfM via PyCOLMAP.
- **Verification:** Unit tested via synthetic translating 2D images, and end-to-end on the synthetic rendered room video (`data/input/synthetic_box_room.mp4`, 24 cameras registered, 1700+ points triangulated). No physical-camera video has been reconstructed yet.

### P2 — Spatial Reconstruction / Room Understanding
- **Implemented:** Open3D voxel downsampling, statistical outlier removal, iterative RANSAC plane segmentation, coplanar-segment merging, geometric classification (floor/wall/ceiling), scaled room dimension calculation, and (Task A) per-plane boundary polygons/extent/area/PLY export, plane-plane intersection lines, room-frame coordinates, and the room's bounding polygon.
- **Verification:** Tested on a synthetic 3D point cloud of a box room (`tests/test_geometry.py`, 9 tests) and on a synthetic rendered box-room video (`data/input/synthetic_box_room.mp4`).

### P3 — Spatial Intelligence
- **Implemented:** Scene graph generation from P2 JSON: `contains`, `parallel_to`/`perpendicular_to` (with `angle_deg`), boundary-distance-based `adjacent_to`, `intersects` (reusing Task A's segments), `above`/`below` (room-frame height), `inside` (camera-vs-room-polygon), plus camera nodes (hand-written quaternion math) and a trajectory node. `SpatialQueryEngine` (Task C): indexed lookups, unit-aware measurements (`{value, metric, units}` or `None`), wall area from Task A's hull area, surface/camera distance queries with boundary-containment flags, and a regex question dispatcher.
- **Verification:** `tests/test_spatial.py` (51 tests) — hand-built box room with known answers for every relation and every query method, hand-built-pose tests for the quaternion conversion, and dispatcher tests (4 questions × 3 phrasings + 1 unsupported). Also verified on the reconstruction of a synthetic rendered box-room video (`data/input/synthetic_box_room.mp4`, see §19-20).

### P4 — Real-Time / Android Digital Twin
- **Implemented:** A lightweight live camera tracker (`tracker.py`) using KLT optical flow + Essential Matrix pose recovery + linear triangulation, and an Open3D standalone viewer.
- **Verification:** The script runs and opens a window, but has not been verified on a physical webcam by a human, nor has it been tested on Android. 

## 5. Current Source Tree
```text
src/visionforge/
├── cli.py                 # Main unified CLI (reconstruct, live). DO NOT refactor unnecessarily.
├── video/
│   └── extract_frames.py  # P0: Video frame extraction using cv2.VideoCapture.
├── reconstruction/
│   ├── pipeline.py        # P1: Orchestrates feature extraction -> matching -> SfM.
│   ├── two_view.py        # P1: SIFT matching and geometric verification.
│   └── incremental.py     # P1: Wrapper around pycolmap.
├── geometry/
│   ├── pipeline.py        # P2: CLI for geometry phase.
│   ├── point_cloud.py     # P2: Open3D cleaning (voxel, outlier removal).
│   ├── plane_fitting.py   # P2: RANSAC segment_plane and normal classification.
│   └── room_model.py      # P2: Coordinate bounding and room measurement.
├── spatial/
│   ├── scene_graph.py     # P3: Builds semantic JSON graph from P2 room model.
│   ├── queries.py         # P3: Deterministic geometry query engine.
│   └── viewer.py          # P4: Open3D visualization (bounding boxes for planes).
└── live/
    └── tracker.py         # P4: Classical visual odometry (KLT + 5-point EM).
```

## 6. Current CLI / Commands
Based on the repository, these commands currently function:
- **Run automated tests:** `source venv/bin/activate && PYTHONPATH=src pytest tests/`
- **Run offline reconstruction pipeline:** `python -m visionforge.cli reconstruct --video <path_to_mp4> [--output <dir>] [--no-viewer] [--input-type synthetic|real] [--persist]` — writes `run_status.json` and, as its last step, `twin.json` into `<dir>`; `--persist` also saves through the configured `PersistenceBackend` (see §25).
- **(Re)build a digital twin from an existing run:** `python -m visionforge.cli twin build --run-dir <dir>`
- **Persist an existing run directory:** `python -m visionforge.cli persist --run-dir <dir> [--session-id <id>]`. See §25 / `docs/supabase.md`.
- **Run live webcam tracking demo:** `python -m visionforge.cli live`
- **Run the read-only API server:** `uvicorn visionforge.api.app:app --reload` (reads `outputs/` by default; set `VISIONFORGE_OUTPUTS_ROOT` to point elsewhere). See §23.
- **Run the frontend dev server:** `cd frontend && npm install && npm run dev` (proxies `/api/*` to `http://localhost:8000` by default; set `VISIONFORGE_API_URL` to point elsewhere). Requires the API server running separately. See §24.
- **Build the frontend / run its tests:** `cd frontend && npm run build` (TypeScript + Vite production build) / `npm run test` (vitest).

## 7. Tests & Verification

| Component | Test | Result | Evidence | Status |
|-----------|------|--------|----------|--------|
| P0 Video Ingestion | Automated (`test_extract_frames.py`) | Pass | Pytest output | Verified (Synthetic) |
| P1 Reconstruction | Automated (`test_reconstruction.py`) | Pass | Pytest output | Verified (Synthetic) |
| P2 Room Geometry | Automated (`test_geometry.py`) | Pass | Pytest output | Verified (Synthetic) |
| P3 Scene Graph | Manual Script | Pass | Terminal output logs | Verified (Synthetic) |
| P4 Offline Viewer | CLI dry run | Pass | Open3D window generation | Partially Verified |
| P4 Live Tracker | None | Untested | No physical webcam test | UNVERIFIED |
| End-to-End Synthetic Video | Full pipeline run | Pass | `data/input/synthetic_box_room.mp4` (rendered, not physical-camera footage) — see §16-20 | Verified (Synthetic) |
| End-to-End Physical-Camera Video | None | Untested | No physical-camera video has been provided yet | UNVERIFIED |
| Android Integration | None | Untested | No Android code exists | PLANNED |

## 8. Generated Outputs / Artifacts
- `sparse_cloud.ply` / `cameras.json`: Genuine (non-fabricated) P1 outputs, produced from a synthetic rendered textured video (not physical-camera footage) with genuine camera translation — see §16.
- `room_model.json`: Per plane: `equation`, `normal`, `centroid` (reconstruction frame) + `centroid_room` (room frame), `support`, `in_plane_axes`, `extent` (width/height), `area` (convex-hull polygon area), `boundary`/`boundary_room` (convex-hull polygon vertices in each frame), `ply_path` (that plane's own inlier cloud). Top-level `intersections`: perpendicular plane pairs whose extents overlap, as a clipped 3D segment in both frames. `room.bounding_polygon_room`: the room's footprint outline. See §17-18 for the merge fix and Task A.
- `p2/planes/<plane_id>.ply`: Each plane's own inlier point cloud, exported individually.
- `scene_graph.json`: Nodes and edges representing semantic relationships (e.g., floor is perpendicular to wall).
- `statistics.json`: Contains retention ratios, plane counts, resolved scale-relative thresholds, and processing times.
- `run_status.json`: `{input_type, video, stages: {<stage>: "success"|"failed"}}`, written incrementally by `cli.py` after every stage.
- `twin.json`: A single self-contained bundle (room_model + cameras + scene_graph + provenance, with the sparse cloud referenced by path, never embedded) a frontend can load without touching the other files. See §22.

## 9. Known Problems / Limitations
- **No Physical-Camera Video Verification:** The pipeline has strictly been tested on synthetic data — a hand-built synthetic point cloud, and a synthetic rendered video (`data/input/synthetic_box_room.mp4`). No physical-camera video has been run through it yet. Real-world motion blur, textureless walls, and sensor noise are untested.
- **Scale Ambiguity & Drift:** Monocular reconstruction (P1) lacks absolute scale. The live VO tracker (P4) will experience severe scale drift over time without global bundle adjustment.
- **Manhattan-World Assumption:** P2 geometry classification strictly assumes orthogonal vertical walls and flat horizontal floors.
- **No Android Support:** The "Iron Man" vision relies on Android, but the current codebase only supports desktop webcam access via `cv2.VideoCapture(0)`.

## 10. Git / Development State
- **Branch:** `main`
- **Recent Commits:** P0 through P4 are fully committed up to `feat: finalize integrated prototype with scene graph, queries, and live mode`.
- **Uncommitted Changes:** `.agents/` directory containing newly installed Supabase agent skills.
- **Working Tree:** Clean (excluding untracked agent skills).

## 11. Supabase Role
- **Current State (updated, Task G / §25):** Supabase integration now exists in `src/visionforge/persistence/` as an opt-in `PersistenceBackend`, selected only via `SUPABASE_URL`/`SUPABASE_KEY` env vars (`LocalJsonBackend` is the zero-config default). No Supabase MCP was configured in the environment this was built in, so no real database round-trip has been run against an actual Supabase project yet — `SupabaseBackend` is tested against an in-memory fake client only. See `docs/supabase.md` for setup and §25 for what was and wasn't verified.
- **Intended Boundary:** Supabase SHOULD be used for persisting project state, saving JSON scene graphs, storing room measurements, and handling asynchronous sync. It MUST NOT be used for streaming raw camera frames, high-frequency CV processing, or frame-by-frame Android tracking round-trips. (This boundary is now enforced by the schema itself, not just documentation — see `supabase/migrations/0001_init.sql` and `docs/supabase.md`'s "What is never stored".)

## 12. Immediate Next Objective
The immediate next objective is **PHYSICAL-CAMERA VERIFICATION**.
The pipeline has now been validated end-to-end on a synthetic rendered clip (`data/input/synthetic_box_room.mp4`, see §16-20) — but that is a rendered video, not physical-camera footage. Before building the Android mobile app, the existing P0-P4 Python pipeline MUST also be successfully executed against a real, physical indoor smartphone video to validate the classical CV pipeline's robustness against real-world sensor noise and motion.

## 13. Android / Real-Time Requirements
The next major architectural phase is the Android client:
- Must run on a physical Android phone using the rear camera.
- Must capture real camera frames and perform low-latency local processing.
- Must STRICTLY use classical CV only.
- The tracking state must update a sparse map from actual observations.
- Tracking loss must be handled honestly; no faking poses or point clouds.
- **Current Readiness:** The Python codebase is completely detached from Android. We will need a way to bridge Android camera frames to the CV pipeline (either via JNI/C++ OpenCV on-device, or streaming frames to a local Python server via WebSocket/UDP for the prototype).

## 14. Handoff Instructions for the Next AI Agent
1. **Read this file first.**
2. **Inspect the repository before changing code.** Do not assume anything works unless you see the test evidence.
3. **Do not rebuild completed components unnecessarily.**
4. **Preserve the classical-CV constraint.** Absolutely no neural networks.
5. **Run existing tests before making changes:** `pytest tests/`.
6. **CODE → RUN → SEE RESULT → SAVE RESULT → COMMIT → NEXT.**
7. Never claim verification without actually running the relevant test.
8. If an issue is clearly straightforward, fix it. If it is obscure/environment-specific, document it and move on.
9. Keep the offline pipeline reproducible.

## 15. Recommended Next Task
**DONE (see §16):** Execute the unified offline pipeline (`visionforge reconstruct`) end-to-end and fix any immediate classical CV pipeline crashes — completed against a synthetic rendered clip (`data/input/synthetic_box_room.mp4`), not physical-camera footage.

**STILL OUTSTANDING (the actual next task):** run the same pipeline against a **real, physical-camera indoor smartphone video** at `data/input/room.mp4` (a distinct file from the synthetic clip above) before beginning Android integration (see §12). **No physical-camera video has been processed yet; all verification to date is on synthetic input.**

## 16. Session Log — 2026-09-21: CLI pipeline fix + synthetic end-to-end verification

**Scope:** Pre-Task-A preparation for the Spatial Intelligence + Digital Twin chain (Geometry → Room Model → Scene Graph → Spatial Queries → Digital Twin → API → Viewer → Supabase).

**Bugs found and fixed in `visionforge reconstruct` (`src/visionforge/cli.py`):**
- P0 (`extract_frames`) was invoked with positional args; the module requires `--input`/`--output`. Fixed.
- P1 (`reconstruction.pipeline`) was invoked with positional args; the module requires `--frames-dir`/`--output`. Fixed.
- CLI looked for the sparse cloud at `p1/sparse_cloud.ply`; P1 actually writes it to `p1/reconstruction/sparse_cloud.ply`. Fixed.
- No subprocess return-code checks — a failed P0/P1/P2 stage was silently ignored. Fixed: every stage now aborts with a clear error on non-zero exit.
- A dummy 1000-point random point cloud was silently substituted whenever P1 failed, and the CLI still reported success. **Removed entirely** — a missing cloud is now a hard, honest failure with a message pointing at the real cause (insufficient camera parallax).
- Added `--output <dir>` (was hardcoded to `outputs/final_demo`) and `--no-viewer` (skip the blocking Open3D window) flags to the `reconstruct` subcommand.

**Bug found and fixed in `src/visionforge/reconstruction/incremental.py`:** on `pycolmap` >= 3 (installed: 4.2.0), `Image.cam_from_world` is an instance method, not a property. `image.cam_from_world.rotation.quat` crashed with an `AttributeError` the first time a reconstruction actually succeeded. This was never caught by `tests/test_reconstruction.py` because that test's synthetic fixture is a pure 2D translation (planar-scene degeneracy for `pycolmap.incremental_mapping`), which yields 0 reconstructions and never exercises this code path. Fixed by calling `image.cam_from_world()`.

**Synthetic test artifact:** No physical-camera phone video existed in the repo, and none was available in this environment. Generated `data/input/synthetic_box_room.mp4` (gitignored, not committed) via a from-scratch pure-OpenCV perspective-warp rasterizer (`gen_room_video2.py`, kept in the session scratchpad, not the repo) — a textured 6-face box room rendered from 24 camera poses that dolly sideways while smoothly tilting from floor-level to ceiling-level, giving genuine translation and parallax (no ML, no Open3D scene renderer — Open3D's `OffscreenRenderer` was tried first and produced all-black frames in this environment even for a canonical sphere test; documented and abandoned rather than debugged further, per guidance to not chase obscure environment-specific issues). **This is a rendered synthetic video, not physical-camera footage** — it exercises the pipeline honestly (real feature matching, real triangulation, real RANSAC), but says nothing about robustness to real sensor noise, motion blur, or rolling shutter.

**Ran the fixed pipeline end-to-end** (`visionforge reconstruct --video data/input/synthetic_box_room.mp4 --output outputs/final_demo --no-viewer`), with genuine (non-fabricated) results on synthetic input at every stage:
- P0: 24 frames extracted.
- P1: two-view stage found 646/664 keypoints, 298 Lowe matches, 258 geometric inliers, 134 triangulated points. Incremental SfM registered all 24 cameras and triangulated 1692 3D points (`p1/reconstruction/sparse_cloud.ply`, `cameras.json` — genuine quaternions/translations/SIMPLE_RADIAL params, confirming the `cam_from_world()` fix works).
- P2: cleaned to 1457 points, found 4 genuine RANSAC planes — classified `{floor: 2, wall: 1, unknown: 1, ceiling: 0}`. Note: two of the four planes were both classified `floor` (near-identical centroids) — the floor was likely split into two RANSAC segments by the existing classification thresholds; this is pre-existing P2 classification behavior, not a bug introduced here, and per the hard rules P2's RANSAC/classification logic was not touched.
- `scale.metric_available: false` (correctly honest — no reference distance was supplied, so `room.length/width/height/floor_area` are in arbitrary reconstruction units, not meters).
- Scene graph: 5 nodes, 10 edges (`contains`, `perpendicular_to`, `adjacent_to`, `parallel_to`) generated correctly from the room model.
- `pytest tests/` remained green (6/6) throughout.

**Not yet done (deferred to Task A onward):** room_model.json plane entries still only carry `id/type/equation/normal/support/centroid` — no boundary polygon, extent, area, or per-plane PLY path yet. `scene_graph.py`'s `adjacent_to` is still the pre-existing centroid-distance-<10.0 heuristic. No `tests/test_spatial.py` yet. No frontend exists anywhere in the repo (confirmed via search — no `package.json`/Vite anywhere); it will be created under `frontend/` only when Task F is reached.

## 17. Session Log — 2026-09-21 (cont.): split-floor fix before Task A

**Split-plane merge (`src/visionforge/geometry/plane_fitting.py`):** Added `merge_coplanar_planes(planes, distance_threshold, normal_dot_threshold=0.98, offset_factor=2.0)`. Runs after `extract_dominant_planes` and before `classify_planes` (wired into `geometry/pipeline.py`). Merges any two RANSAC segments whose normals agree (`|dot| > 0.98`, sign-corrected so anti-parallel-but-coincident planes still compare correctly) and whose plane offsets `d` differ by less than `2 * distance_threshold`: sums `inliers`/`inlier_ratio`, concatenates the Open3D inlier clouds (`cloud_a + cloud_b`), and recomputes the centroid from the merged cloud. The surviving `equation`/`normal`/`id` are kept from the larger (base) segment — no refit, as requested. `extract_dominant_planes`'s own `segment_plane` call was not touched.

**Scale-relative P2 defaults (`geometry/pipeline.py`):** `--voxel-size` and `--plane-distance-threshold` now default to `None` and, when not explicitly passed, resolve to 0.5% and 1% of the *raw* (pre-cleaning) cloud's bounding-box diagonal, computed by reading the input PLY once at the top of `main()`. Explicit CLI overrides still work exactly as before. Resolved values are logged to stdout and written to `statistics.json` under `resolved_thresholds` (`bbox_diagonal`, `voxel_size`, `plane_distance_threshold`) for reproducibility.

**Tests added (`tests/test_geometry.py`):** `test_merge_coplanar_planes_merges_split_wall` (two same-normal segments 0.001 apart merge into one with summed support and correctly recomputed centroid; a genuinely perpendicular third plane is left untouched) and `test_merge_coplanar_planes_keeps_distinct_parallel_planes_separate` (floor vs. ceiling — same normal, offset 2.5 apart — must NOT merge). `pytest tests/`: 8/8 green.

**Before/after on the synthetic clip's data**, isolating the merge fix from the threshold-default fix by re-running P2 on the *same* cloud from the earlier session with the *same* explicit `--plane-distance-threshold 0.05` (the old absolute default) that had originally produced the bug:
- Before (no merge logic existed): 4 planes — `plane_000 floor support=976`, `plane_001 wall support=96`, `plane_002 floor support=75` (the spurious floor split), `plane_003 unknown support=80`.
- After (merge active, same cloud, same threshold): 3 planes — `plane_000 floor support=1049` (merged; not exactly 976+75 because Open3D's `segment_plane` RANSAC is itself randomized and reran from scratch, but confirms the merge collapses the split), `plane_001 wall support=93`, `plane_002 unknown support=80`.

Separately, re-running the full `visionforge reconstruct` end-to-end on `data/input/synthetic_box_room.mp4` with the new scale-relative defaults (bbox diagonal 32.78 → voxel_size≈0.164, plane_distance_threshold≈0.328, vs. the old fixed 0.05) avoids the fragmentation at the RANSAC stage itself: `{floor: 1, wall: 2, ceiling: 0, unknown: 0}`, 3 planes total, no duplicates. `pytest tests/` remained green throughout.

## 18. Session Log — 2026-09-21 (cont.): Task A — room geometry model

**`src/visionforge/geometry/room_model.py`** (extended, per the task's chosen location; `plane_fitting.py`'s RANSAC/classification logic untouched):
- `_in_plane_axes(normal, up_axis, x_axis)`: orthonormal in-plane basis `(axis_u, axis_v)` per plane. `axis_v` is `up_axis` projected onto the plane (a wall's true vertical direction); for near-horizontal planes where that degenerates (floor/ceiling, `up_axis` ~parallel to `normal`), falls back to projecting the room's `x_axis` instead. `axis_u = normal × axis_v`.
- `_convex_hull_2d` / `_polygon_area_2d`: Andrew's monotone-chain hull and shoelace area, written from scratch — `requirements.txt` has no scipy, and this is plain classical geometry.
- `_plane_boundary`: projects a plane's inlier cloud onto `(axis_u, axis_v)`, takes the 2D convex hull, lifts it back to 3D — the plane's oriented boundary polygon.
- Per plane, new fields: `in_plane_axes`, `extent` (`{width, height}` = the hull's axis-aligned bbox in the plane's own 2D frame), `area` (true hull polygon area, not the bbox product), `boundary` (reconstruction frame) / `boundary_room` (room frame), `centroid_room`, `ply_path`.
- `_plane_intersection`: for pairs whose normals are near-perpendicular (`|dot| < 0.25`, matching the existing convention elsewhere in the codebase), solves for the 3D line of intersection, then clips it to the overlap of both planes' boundary extents projected onto the line direction. Returns `None` (no fabricated intersection) if the planes aren't perpendicular, are degenerate, or the extents don't actually overlap. Exposed at the top level as `room_model["intersections"]`, each with `point`/`direction`/`segment` (reconstruction frame) and `point_room`/`segment_room` (room frame).
- `_room_origin`: the largest detected floor's centroid, or the mean of all plane centroids if no floor was found — just a reference point for the room-frame transform, not a measurement.
- `room["bounding_polygon_room"]`: convex hull of every plane's inliers projected onto the room's horizontal `(x_axis, z_axis)` plane — the room's footprint outline, scaled by `scale_factor` like its sibling `room` fields.
- `export_plane_plys(planes, output_dir)`: writes each (post-merge) plane's inlier cloud to `planes/<plane_id>.ply` and returns the id→path map, which `align_and_measure_room` embeds as each plane's `ply_path`. Wired into `geometry/pipeline.py` between plane extraction/merge and `align_and_measure_room`.
- **Units:** per-plane geometry (`boundary`, `extent`, `area`, `centroid`, `intersections`) stays in raw, unscaled reconstruction-frame units, consistent with the pre-existing (also unscaled) `equation`/`normal`/`centroid` fields. Only the top-level `room` summary (`length`/`width`/`height`/`floor_area`/`bounding_polygon_room`) applies `scale_factor`, exactly as it already did — `scale.metric_available` stays honest either way.

**Tests added (`tests/test_geometry.py`):** `test_room_model_geometry_extension`, on the existing synthetic 5×5×2.5 box-room fixture — asserts the floor's extent is ~5×5 and its hull area ~20-25 (the true convex-hull area is slightly smaller than the bbox product), a wall's extent is ~5×2.5, every plane's `ply_path` points at a real file on disk, at least one genuine floor↔wall intersection exists as a proper 3D segment in both frames, and the room's bounding polygon spans ~5×5. `pytest tests/`: 9/9 green.

**Synthetic-clip run** (`data/input/synthetic_box_room.mp4` → `visionforge reconstruct`): 3 planes (`floor:1, wall:2`). Floor `extent = {width: 8.54, height: 20.59}` — matches `room.length`/`room.width` from the pre-existing measurement method exactly, a useful cross-check; hull `area = 171.2` vs. bbox product `175.86` (the true hull is honestly smaller, as expected for a non-rectangular boundary). Both floor↔wall pairs produced genuine intersection segments, each with `segment_room` y-coordinate ≈ 0 at both endpoints — correct, since the intersection of a wall with the floor must lie on the floor, and the room-frame origin is the floor's own centroid. Each plane's PLY was verified to exist on disk with the exact point count matching `support`.

## 19. Session Log — 2026-09-21 (cont.): Task B — plane relationships, cameras, spatial graph

**Small Task-A follow-up (`geometry/room_model.py`):** exposed `coordinate_system["origin"]` (the same reference point `_room_origin` already computed internally) so `scene_graph.py` can place cameras in the room frame consistently with the already-computed `bounding_polygon_room`, without recomputing or guessing an origin.

**`src/visionforge/spatial/scene_graph.py`** (rewritten; `build_scene_graph` signature is now `build_scene_graph(room_model, cameras=None)`):
- `_quat_to_rotation_matrix(qx, qy, qz, qw)`: hand-written quaternion→matrix conversion (no scipy). `_camera_world_position(rotation_quat, translation)`: `C = -R^T @ t`, matching pycolmap's `cam_from_world` convention (`rotation_quat` is `[x, y, z, w]` of `cam_from_world`).
- Camera nodes are built from `p1/reconstruction/cameras.json` (now loaded and passed in by `cli.py`), ordered by frame **name** (not pycolmap's internal image id, which is registration order, not temporal order — ids we saw were e.g. 19, 4, 8, 6, 18...). A `trajectory_001` node holds the ordered positions (both frames) and the genuine piecewise path length.
- `adjacent_to` no longer uses centroid distance. It now uses `_polygon_min_distance` (edge-to-edge distance between the two planes' Task-A boundary polygons, via a hand-written robust 3D segment-segment distance routine) against a scale-relative threshold (`ADJACENCY_DISTANCE_FRACTION = 0.05` of the room's own boundary-derived bounding-box diagonal, i.e. the same style of scale-relative threshold as P2's RANSAC/voxel sizing, just derived from `room_model.json`'s own plane boundaries since `scene_graph.py` doesn't have the raw cloud). The old `centroid < 10.0` heuristic is fully removed.
- `intersects` edges are a direct pass-through of `room_model["intersections"]` (Task A) — not recomputed.
- `above`/`below`: compared along `up_axis` via each entity's `centroid_room`/`position_room` y-component, both between horizontal surfaces (floor/ceiling pairs) and between every camera and every floor/ceiling plane, gated by a scale-relative `ABOVE_BELOW_EPSILON_FRACTION = 0.02` to avoid noise-level differences producing spurious edges. Both directions (`above` and `below`) are added explicitly so either can be queried directly.
- `inside`: hand-written ray-casting point-in-polygon test (`_point_in_polygon_2d`, PNPOLY) of each camera's room-frame `(x, z)` against `room.bounding_polygon_room`. **Always emits an edge, even when `inside: false`** — an out-of-polygon camera is reported with its `distance_to_boundary`, never silently dropped.
- Every relation edge now carries its supporting number: `angle_deg` (parallel/perpendicular), `distance` (adjacent_to), `height_difference` (above/below), `segment`/`point`/`direction` (intersects, both frames), `inside`/`distance_to_boundary` (inside) — not just the relation label.
- Plane node properties were also expanded to carry the full Task A geometry (`extent`, `area`, `boundary`/`boundary_room`, `centroid_room`, `ply_path`), for the query engine and UI to use directly without re-deriving it.

**`tests/test_spatial.py`** (new, 14 tests): hand-built-pose quaternion tests independent of the scene graph (a known 90°-about-Z rotation checked against its hand-derived matrix and against a camera-center round-trip; a second rotated-pose round-trip; a known point-in-polygon case) + a hand-built 4×3×2.5 box room (identity room frame, so every expected number is computable by hand) covering every relation type: `contains`, `parallel_to`/`perpendicular_to` with exact `angle_deg` (0°/90°), `adjacent_to` with exact `distance` (0.0, since the hand-built walls genuinely share an edge with the floor), `intersects` (asserts the exact hand-supplied segment is passed through unchanged), `above`/`below` (exact `height_difference` of 2.5 and 1.25), `inside` for both an interior and a **deliberately outside** camera (asserting the outside case is still reported, with the correct `distance_to_boundary` of 6.0), and the trajectory node's path length. `pytest tests/`: 23/23 green.

**Synthetic-clip run** (`data/input/synthetic_box_room.mp4`), edge counts by relation type:

| Relation | Before (old centroid heuristic, no cameras) | After (Task B) |
|---|---|---|
| contains | 3 | 28 |
| parallel_to | 1 | 1 |
| perpendicular_to | 2 | 2 |
| adjacent_to | 0 | 2 |
| intersects | 0 | 2 |
| above | 0 | 24 |
| below | 0 | 24 |
| inside | 0 | 24 |
| **total** | **6** | **107** |

Notable honest details from the synthetic-clip run: `adjacent_to` distances are `0.34` and `0.05` (reconstruction units, well inside the ~1.7-unit scale-relative threshold for this cloud); `perpendicular_to` angles are `89.55°`/`87.43°` and `parallel_to` is `3.33°` — close to but not exactly 90°/0°, correctly reflecting genuine reconstruction noise rather than fabricated perfection. **All 24 camera positions land inside `room.bounding_polygon_room`** (0 outside) — the specifically requested check on this clip. Trajectory path length: `15.67` (reconstruction units) over 24 cameras.

## 20. Session Log — 2026-09-21 (cont.): Task C — spatial query engine

**Extracted `src/visionforge/spatial/geometry_utils.py`** (new shared module): moved `segment_segment_distance_3d`, `polygon_min_distance`, `point_in_polygon_2d`, `point_segment_distance_2d`, `point_polygon_distance_2d`, and the `PARALLEL_DOT_THRESHOLD`/`PERPENDICULAR_DOT_THRESHOLD` constants out of `scene_graph.py` (made public, no more leading underscore) so `queries.py` reuses the exact same routines instead of a second implementation. `scene_graph.py` now imports from it; behavior is unchanged (verified by the full existing `test_spatial.py` suite before writing anything new).

**Small follow-up in `scene_graph.py`:** the room node's properties now also carry `scale` (`{metric_available, scale_factor}`, copied from `room_model["scale"]`) and each plane node's properties now also carry `in_plane_axes` — both were already computed/available but not previously exposed on the graph, and `queries.py` needs them (`scale` for unit-aware measurements, `in_plane_axes` for the within-boundary check below).

**`src/visionforge/spatial/queries.py`** (rewritten):
- `__init__` builds `nodes_by_id`, `nodes_by_type` (`defaultdict(list)`), `edges_by_source_relation` and `edges_by_target_relation` (both keyed `(node_id, relation)`) — every query below is an O(1)/O(edges-for-this-node) lookup, never a scan of the full edge list.
- `_measurement(raw_value, power=1)`: wraps a value as `{"value", "metric", "units"}`, applying `scale_factor ** power` (power=1 for lengths/distances/positions, power=2 for areas) since Task A's per-plane geometry is stored unscaled; returns `None` outright when `raw_value is None`. `_measurement_prescaled` skips the extra scaling for the top-level `room` fields, which already had `scale_factor` applied in `room_model.py`.
- Room dimensions (`get_room_length/width/height/floor_area`) check `nodes_by_type` for `floor`/`ceiling`/`wall` presence before reading the room node's properties, translating the pre-existing P2 "leaves it at 0.0 when not computed" behavior into an honest `None` — without changing P2 itself. `get_room_height` specifically returns `None` only when there's no floor, or there's a floor but neither a ceiling nor any wall (mirroring exactly when `align_and_measure_room` actually computes it).
- `get_wall_area` reads Task A's hull `area` field directly (never `height * width`). `get_largest_wall`/`get_smallest_wall` now rank by that same `area` (previously ranked by `support`).
- `distance_between_surfaces`: parallel pair (`|dot(n1,n2)| > 0.85`) → plane-offset distance (`|d1 - d2|`, sign-corrected for anti-parallel normals, same convention as the Task-A merge fix); otherwise → `polygon_min_distance` on the two Task-A boundary polygons, imported from `geometry_utils`, not reimplemented.
- `get_surface_intersection(id_a, id_b)`: looks up the `intersects` edge already built in Task B (checking both edge directions) and returns its `segment`/`point`/`direction`, or `None` if the pair never intersected — no recomputation.
- Camera queries read `nodes_by_type["camera"]` and `nodes_by_type["trajectory"]` directly. `get_camera_position(index=None)` defaults to the last camera (chronologically last, since `scene_graph.py` already orders cameras by frame name); an out-of-range index returns `None`, not an exception.
- `distance_from_camera_to_surface`/`distance_from_camera_to_all_surfaces`/`get_nearest_wall_to_camera`: point-to-plane distance, plus a `within_boundary` flag computed by projecting the foot of the perpendicular into the plane's own `(axis_u, axis_v)` frame and running `point_in_polygon_2d` against the boundary projected the same way — flags (rather than silently reports) a mathematically valid point-to-plane distance whose foot actually falls outside that surface's genuine, finite extent.
- Question dispatcher: `QUESTION_PATTERNS`, a list of `(compiled regex, handler method name, canonical phrasing)`. `answer_question` returns `{"supported": False, "answer": None, "supported_question_types": [...]}` — listing the canonical phrasings — for anything that matches no pattern, rather than guessing.

**Tests added (`tests/test_spatial.py`, +28, total 51):** every `SpatialQueryEngine` method exercised on the same hand-built box room from Task B (plus a `floor_only_room_model` fixture for the no-ceiling-no-walls `None` case, and an empty-room fixture for the no-floor `None` case), each with a hand-computed expected number — e.g. `distance_between_surfaces("wall_south", "wall_north") == 3.0` (exact plane separation), `get_wall_area` distinguishing 7.5/10.0/8.0 by design so `get_largest_wall`/`get_smallest_wall` have an unambiguous answer, a camera positioned so its perpendicular foot on `wall_west` lands outside that wall's `z ∈ [0,3]` boundary (`within_boundary: False`) versus one that lands inside. Dispatcher: parametrized over all 4 example questions × 3 phrasings each (12 cases) plus one unsupported question asserting `supported_question_types` lists exactly the 4 canonical phrasings. `pytest tests/`: 51/51 green.

**Synthetic-clip run** (`data/input/synthetic_box_room.mp4`), every query exercised against the actual scene graph:
- Room dimensions: `length=20.65`, `width=8.60`, `height=6.85`, `floor_area=177.61` (reconstruction units, `metric=False`).
- **Correction to the original expectation** that room height would come back `None` on this clip since no ceiling was detected: it does NOT come back `None` here, because the pre-existing (untouched) `align_and_measure_room` logic estimates height from wall-point projections whenever a floor **and at least one wall** exist, and this reconstruction has 2 walls. This is exactly the pre-existing P2 fallback path, not something Task C changed. (See §21: `room["height"]` now carries a `method` field — `"wall_extent_estimate"` on this clip, honestly flagging it as the weaker estimate rather than a measured `"floor_to_ceiling"` height.)
- Genuine `None` results found instead: `get_wall_area("plane_000")` → `None` (that id is the floor, not a wall); `get_surface_intersection("plane_001", "plane_002")` → `None` (the two walls are parallel, never intersect — no fabricated segment); `get_camera_position(index=999)` → `None` (out of range).
- `distance_between_surfaces`: `plane_000↔plane_001 = 0.008`, `plane_000↔plane_002 = 0.39` (both perpendicular/boundary-based, honestly near-zero since they're adjacent), `plane_001↔plane_002 = 19.98` (parallel/plane-offset-based).
- Camera/trajectory: 24 cameras, `path_length = 19.30`; nearest wall to the last camera is `plane_002` at distance `4.79`, with `within_boundary: False` (the perpendicular foot falls outside that wall's genuine detected extent — an honest, informative flag, not hidden).
- All 4 example dispatcher questions answered correctly against the graph; the unsupported question correctly listed all 4 supported phrasings.

## 21. Session Log — 2026-09-21 (cont.): room-height measurement provenance

**`geometry/room_model.py`:** `align_and_measure_room` now tracks *how* each room measurement was derived and adds it to `room_model["room"]` as a sibling `*_method` field: `height_method` is `"floor_to_ceiling"` when a ceiling was actually measured against the floor, `"wall_extent_estimate"` when it was only estimated from the highest wall point (the pre-existing fallback — a real but weaker method), or `None` when height couldn't be computed at all (no floor, or floor with neither ceiling nor walls). `length_method`/`width_method`/`floor_area_method` are `"floor_extent"` whenever the floor's own boundary was used (which is always, when a floor exists), else `None`. No change to how any value is actually computed — this only labels the existing computation paths.

**`spatial/queries.py`:** `_measurement_prescaled` takes an optional `method` and includes it in the returned `{value, metric, units, method}` dict when set. `get_room_height/length/width` and `get_floor_area` now read the corresponding `*_method` field off the room node and pass it through.

**Tests:** `tests/test_geometry.py` — two new tests calling `align_and_measure_room` directly (bypassing RANSAC randomness via hand-built plane dicts, like the existing merge tests): a floor+wall-no-ceiling case asserting `height_method == "wall_extent_estimate"`, and a floor+ceiling case asserting `height_method == "floor_to_ceiling"`. `tests/test_spatial.py` — a new `floor_and_walls_no_ceiling_room_model` fixture and `test_room_height_method_wall_extent_estimate_without_ceiling`, confirming the method survives the full `build_scene_graph` → `SpatialQueryEngine` path; the existing `box_room_model` fixture (floor+ceiling+walls) and its exact-equality dimension test were updated to include the new method fields (`"floor_to_ceiling"` for height, `"floor_extent"` for length/width/area). `pytest tests/`: 54/54 green.

**Verified on the synthetic clip:** re-ran `visionforge reconstruct` on `data/input/synthetic_box_room.mp4` — `room["height"]` now reports `{"value": 6.72, "metric": false, "units": "reconstruction_units", "method": "wall_extent_estimate"}`, correctly flagging it as the weaker estimate (this clip has no detected ceiling, only 2 walls). `length`/`width`/`floor_area` all report `"method": "floor_extent"`.

## 22. Session Log — 2026-09-21 (cont.): Task D — digital twin data layer

**New module `src/visionforge/twin/digital_twin.py`:** `DigitalTwin.build_from_run_dir(run_dir)` loads `p2/room_model.json`, `p1/reconstruction/cameras.json`, `scene_graph.json`, and (as a path reference only, never embedded) `p1/reconstruction/sparse_cloud.ply` from a run directory, plus `run_status.json` if present. Any missing source is `None` (or, for the sparse cloud path, `None`) — never fabricated. Builds a `provenance` dict with `run_dir`, `source_files` (each path relative to `run_dir`, POSIX-style for portability), `stage_status` (from `run_status.json["stages"]`, `{}` if the file doesn't exist), `input_type` (from `run_status.json["input_type"]`, defaulting to `"unknown"` — never guessed as synthetic or real), `scale` (copied from `room_model["scale"]`), and `measurement_methods` (the four `*_method` fields from §21, read off `room_model["room"]`). `to_dict()`/`from_dict()`/`save()`/`load()` round-trip the whole object to/from a single `twin.json`; `__eq__` compares by `to_dict()`.

**`cli.py`:**
- `reconstruct` gained `--input-type {synthetic,real}` (optional; written as `"unknown"` into `run_status.json` if omitted — the CLI itself writes the default, per the requirement, not just `DigitalTwin`).
- `cmd_reconstruct` now tracks stage status in a `status` dict, persisted via `_write_run_status` to `run_status.json` after every stage (including on failure, before `sys.exit(1)`) — this is "whatever the CLI records" that `DigitalTwin` later reads back; a run that crashed mid-pipeline leaves an accurate partial status, not a stale or missing one.
- `[6/6]` (new, was `[5/5]`): builds the twin via `DigitalTwin.build_from_run_dir(out_dir)` and saves `twin.json` as the last step, after the scene graph and query demo, before the (optional) viewer launch.
- New `twin build --run-dir <dir>` subcommand (`cmd_twin_build`): rebuilds `twin.json` from an existing run directory independently of `reconstruct`, printing the resulting provenance.

**Tests added (`tests/test_twin.py`, 8 new, total 62):** a `full_run_dir` fixture writes all four sources plus `run_status.json` into `tmp_path`; tests cover loading every source, exact `source_files`/`stage_status` provenance, `input_type`/`scale` provenance, the four `measurement_methods`, `input_type` defaulting to `"unknown"` when `run_status.json` is absent, every field coming back `None` (not fabricated) on a completely empty run directory, the **round-trip test** (`build_from_run_dir` → `save` → `load` → `== ` the original, by `__eq__` and by every field individually), and a dedicated check that `twin.json` embeds `room_model`/`cameras`/`scene_graph` in full while `sparse_cloud_path` stays a path string with no `"points"` key anywhere in the file. `pytest tests/`: 62/62 green.

**Verified on the synthetic clip:** ran `visionforge reconstruct --video data/input/synthetic_box_room.mp4 --output outputs/final_demo --no-viewer --input-type synthetic` end-to-end (`[6/6] Building Digital Twin (twin.json)... Digital twin saved to outputs\final_demo\twin.json`), and separately re-ran `visionforge twin build --run-dir outputs/final_demo` standalone to confirm it works independently of `reconstruct`. `twin.json` (87 KB — the room model, 24 cameras, and a 29-node scene graph, but not the multi-hundred-KB point cloud) provenance:
```json
{
  "run_dir": "...VisionForge\\outputs\\final_demo",
  "source_files": {
    "room_model": "p2/room_model.json",
    "cameras": "p1/reconstruction/cameras.json",
    "scene_graph": "scene_graph.json",
    "sparse_cloud": "p1/reconstruction/sparse_cloud.ply"
  },
  "stage_status": {
    "p0_frame_extraction": "success", "p1_reconstruction": "success",
    "p2_room_geometry": "success", "scene_graph": "success"
  },
  "input_type": "synthetic",
  "scale": { "metric_available": false, "scale_factor": 1.0 },
  "measurement_methods": {
    "length_method": "floor_extent", "width_method": "floor_extent",
    "height_method": "wall_extent_estimate", "floor_area_method": "floor_extent"
  }
}
```
Note: `stage_status` above doesn't include `"twin": "success"` — `twin.json` is built from `run_status.json` as it exists *at the moment of the build*, which is necessarily before that same build's own completion gets recorded a moment later. Not a bug: re-running `twin build` afterward (or reading `run_status.json` directly) shows `"twin": "success"` too, as confirmed by the standalone `twin build` run above.

## 23. Session Log — 2026-09-21 (cont.): Task E — read-only FastAPI backend

**New module `src/visionforge/api/`:**
- `store.py`: `SessionStore(outputs_root)` maps session ids to run directories. `list_sessions()` merges two sources — auto-discovered subdirectories of `outputs_root` that look like a real run dir (`p2/room_model.json` or `twin.json` present), and explicit registrations via `register(run_dir, session_id=None)`, which can point at any directory on disk (matching "list/create sessions **from a run directory**" — the caller supplies the directory, the same trust level as already running `visionforge reconstruct --output <any path>`). No persistence beyond an in-memory dict — Task G adds the Supabase-backed version.
- `app.py`: `create_app(outputs_root=None)` (factory, so tests can point it at `tmp_path`; defaults to `$VISIONFORGE_OUTPUTS_ROOT` or `"outputs"`). Endpoints, all read-only against `outputs/<run>/`:
  - `GET /sessions`, `POST /sessions` (`{run_dir, id?}` → 201 or 400 if the directory doesn't exist), `GET /sessions/{id}` — each returns `{id, run_dir, provenance}` via `DigitalTwin.build_from_run_dir`.
  - `GET /sessions/{id}/room_model`, `/scene_graph`, `/cameras`, `/twin` — raw JSON, 404 if the underlying file doesn't exist for that session.
  - `GET /sessions/{id}/measurements` → `SpatialQueryEngine(scene_graph).get_room_dimensions()`.
  - `POST /sessions/{id}/query` with `{method, params}` **or** `{question}`. Method dispatch goes through an explicit `ALLOWED_QUERY_METHODS` allowlist (not a bare `getattr` on the request string) so a request can never reach a private method or unrelated attribute of `SpatialQueryEngine` — an OWASP-relevant guard, not just a style choice. Bad params surface as 400 (a `TypeError` from the call is caught), not a 500.
  - `GET /sessions/{id}/cloud` → `sparse_cloud.ply` as `FileResponse`; `GET /sessions/{id}/planes/{plane_id}` → that plane's PLY. `plane_id` is validated (`_validate_id_component`: rejects `/`, `\`, `..`) before being joined onto a filesystem path, so a crafted plane id can't escape `p2/planes/` — checked directly with a URL-encoded `../../../etc/passwd` id in tests.
- Added `fastapi`, `uvicorn`, `httpx` (needed by Starlette's `TestClient`) to `requirements.txt`, installed in this environment.

**Tests added (`tests/test_api.py`, 21 new, total 83):** a `run_dir` fixture builds a full synthetic run directory in `tmp_path` (room_model with 4 planes, a real camera via `build_scene_graph`, a stub PLY, `run_status.json`) and a `client` fixture wraps it in `TestClient(create_app(outputs_root=tmp_path))`. Covers: auto-discovery, explicit registration of a directory outside the outputs root, 404 on an unknown session, 400 on registering a directory that doesn't exist, every GET endpoint's content, query-by-method (with and without params), query-by-question (including the unsupported case coming back as a normal 200 with `supported: false`, not an error), the method allowlist rejecting both a dunder (`__class__`) and a nonexistent method name, invalid kwargs producing 400 not 500, file-serving for both the cloud and a per-plane PLY (byte-for-byte against the source file), 404 for a missing plane, and the path-traversal id rejected. `pytest tests/`: 83/83 green.

**Verified against the real synthetic-clip run** (`outputs/final_demo`, via `create_app(outputs_root="outputs")` + `TestClient`, not just the test fixture): `GET /sessions` found `final_demo`; `GET /sessions/final_demo` returned the same provenance as `twin.json` (including `"twin": "success"` in `stage_status`, since this run had already completed); `GET /measurements` returned all four fields with their `method`; `POST /query` with `{"question": "How far is the camera from the nearest wall?"}` and with `{"method": "get_camera_trajectory"}` both returned real, non-fabricated answers (`camera_024`, distance `3.67`; 24 cameras, `path_length 14.28`); `GET /cloud` served the real 25,883-byte `sparse_cloud.ply`; `GET /twin` returned the same five top-level keys as the file on disk.

## 24. Session Log — 2026-09-21 (cont.): two backend fixes + Task F frontend

**Fix 1 — honest twin stage-status ordering (`cli.py`):** extracted a `_build_and_save_twin(out_dir, status)` helper that marks `run_status.json`'s `"twin"` stage `"running"` *before* building `twin.json`, and `"success"` only after. Previously `twin.json`'s own embedded provenance snapshot simply omitted the `"twin"` key (it's necessarily built before its own completion is recorded) — now it truthfully shows `"running"`. Test: `test_build_and_save_twin_marks_running_before_success` (`tests/test_twin.py`) asserts the saved `twin.json` shows `"running"` and `run_status.json` on disk shows `"success"` after. Verified on the real clip: `twin.json` now shows `stage_status.twin == "running"`, `run_status.json` shows `"success"`.

**Fix 2 — CORS (`api/app.py`):** `CORSMiddleware`, origins from `VISIONFORGE_CORS_ORIGINS` (comma-separated), defaulting to Vite's dev origins (`http://localhost:5173`, `http://127.0.0.1:5173`). Two tests: default origin allowed; env var override *replaces* rather than extends the default. `pytest tests/`: 86/86 green after both fixes.

**Task F — `frontend/`** (Vite + React 19.2.8 + TypeScript 5.9.3 + three.js 0.186.0, all pinned in `package.json`; raw three.js via refs in a single `Viewer3D` component, not react-three-fiber, to keep full manual control over raycasting/frustum geometry and avoid an extra dependency's own peer-version constraints):

- **Types (`src/types/twin.ts`):** written from the actual JSON `outputs/final_demo/twin.json` and `GET /sessions` returned (`python -c "json.load(...)"` inspected field-by-field first), not from memory — `Measurement`, `Plane` (with `boundary`/`boundary_room`, `in_plane_axes`, etc.), `PlaneIntersection`, `SceneGraphNode`/`Edge` unions for all 8 relation types, `Provenance`, `Twin`.
- **`src/lib/frames.ts`:** the *only* client-side room-frame transform, used *only* for the point cloud PLY (everything else — plane boundaries, camera positions, intersections, the room bounding polygon — is already served pre-transformed via each API object's `*_room` fields, mirroring `room_model.py`'s own `_room_frame_point`). `toRoomFrame`/`transformPointsToRoomFrame` mirror the Python function exactly (`rel = p - origin; [dot(rel,x_axis), dot(rel,up_axis), dot(rel,z_axis)]`, so room-frame Y = `up_axis`, matching three.js's Y-up convention). Also `quaternionToRotationMatrix` and `cameraAxesRoomFrame` (hand-written, mirroring `scene_graph.py`'s `_quat_to_rotation_matrix`), used to give camera frusta a real, non-approximated orientation from `cameras.json`'s `rotation_quat`.
- **`src/lib/selectors.ts`:** `getRelationsForNode` (every non-`contains` edge touching a node, either direction) and `formatRelationValue` (the right scalar field per relation type) — what the inspect panel uses to show a selected plane's relations with their supporting number.
- **`Viewer3D.tsx`:** point cloud (PLYLoader, room-frame-transformed, toggle), planes as filled translucent `DoubleSide` polygons from `boundary_room` (fan-triangulated, floor green / wall red / ceiling blue / unknown grey) with a wireframe outline and a canvas-texture label sprite, intersection segments from `segment_room`, the room bounding polygon placed at the floor's own height, camera frusta (real intrinsics-sized, real orientation) + trajectory polyline (toggle), `OrbitControls`, and raycast click-to-select against the plane meshes with gold highlight.
- **Panels:** `SessionList` (badge + per-stage status symbols), `MeasurementsPanel` (value/units/method per field, "not measurable" — never `0` — when the API returns `null`), `QueryBox` (posts `{question}`, renders the answer or the unsupported message + supported-question list), `InspectPanel` (type/support/extent/area/normal + relations with their number), `ProvenanceFooter` (source files, `metric_available`, `input_type`), and a synthetic-input banner when `provenance.input_type === "synthetic"`.
- **Dev proxy:** `vite.config.ts` proxies `/api/*` to `VISIONFORGE_API_URL` (default `http://localhost:8000`) — the frontend code itself never hardcodes a host, only ever fetches `/api/...`.

**Tests (`frontend/src/lib/*.test.ts`, vitest, 16 total):** `frames.test.ts` — an axis-aligned translation case, a **hand-built non-identity permuted-axis case** (`up_axis=[1,0,0]`, `horizontal_axes=[[0,1,0],[0,0,1]]`, asserting `[2,3,4] -> [3,2,4]`, so each output component is checked against the *right* source axis, not just a trivial identity round-trip), a check against a real floor centroid from `twin.json` mapping to `(0,0,0)`, `transformPointsToRoomFrame` on a flat array, `quaternionToRotationMatrix` against the same independently-known 90°-about-Z matrix as the backend's own test, and `cameraAxesRoomFrame` for identity rotation matching COLMAP's Y-down convention directly. `selectors.test.ts` — `getRelationsForNode` excludes `contains`, tags outgoing/incoming correctly, returns everything touching a node; `formatRelationValue` for each relation's scalar field and `null` for `intersects` (no single scalar).

**`npm run build`** (TypeScript project build + Vite production build) — **0 TypeScript errors**:
```
> visionforge-frontend@0.1.0 build
> tsc -b && vite build

vite v7.3.6 building client environment for production...
transforming...
✓ 45 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.41 kB │ gzip:   0.28 kB
dist/assets/index-DUZ04Nvd.css     2.77 kB │ gzip:   1.03 kB
dist/assets/index-DSzKxFwa.js    778.86 kB │ gzip: 208.88 kB
(!) Some chunks are larger than 500 kB after minification. [...]
✓ built in 3.00s
```
(The size warning is the normal cost of bundling three.js; not a type or build error.) `npm run test`: 16/16 green.

**Actual visual verification — ran the real stack and looked at it, via the `claude-in-chrome` browser tool (not a description of an unseen render):** started the API (`uvicorn visionforge.api.app:app --port 8000`) against real `outputs/`, started the Vite dev server (`npm run dev -- --port 5173`), confirmed the dev proxy forwards `/api/sessions` correctly, then drove an actual Chrome tab:
- Session `final_demo` listed with a **SYNTHETIC** badge and 4 green stage checkmarks; the synthetic-input banner was visible on the viewer.
- Measurements panel showed length/width/height/floor area with real values, `reconstruction_units`, and each field's real `method` (`floor_extent` / `wall_extent_estimate`).
- **The floor (`plane_000`) rendered flat and the two walls (`plane_001`, `plane_002`) rose vertically from its edges** — confirmed by rotating to a near-edge-on view where the floor appeared as a thin flat sliver with the walls rising perpendicular to it on both sides. This is the room-frame transform working correctly (COLMAP's frame is arbitrary/often Y-down; three.js is Y-up).
- The point cloud rendered as real scattered points lying on/near the floor polygon, not randomly distributed in space.
- Plane ID/type labels rendered as billboard sprites at each plane's centroid.
- **Click-to-select worked**: clicking the floor highlighted it gold and populated the inspect panel with real data — `Type: floor, Support: 1022 points, Extent: 8.544 × 20.565, Area: 170.804, Normal: [-0.342,-0.086,0.936]` — and a real relations list (`perpendicular_to → plane_001 (89.63°)`, `adjacent_to → plane_001 (0.030)`, `perpendicular_to → plane_002 (88.55°)`, more below the fold).
- **The query box worked end-to-end**: typed "Which wall is largest?", got back `{"wall_id": "plane_001", "area": {"value": 38.32..., "metric": false, "units": "reconstruction_units"}}`. Typed the unsupported "What color is the floor?" and got the correct `Unsupported question.` message with the list of 4 supported phrasings rendered as bullets — not an error, not a guess.
- **Camera frusta and the trajectory rendered correctly**, though not in the default view: cameras in this reconstruction sit ~18 (arbitrary reconstruction-scale) units above the floor along `up_axis` — well above the wall-extent-estimated room "height" of ~6.56, an honest property of this particular run's own scale (the wall-extent heuristic only sees a partial vertical slice of the wall points; it is not a bug introduced here). Standard mouse-wheel zoom via the browser automation tool didn't register with `OrbitControls`, so genuine `WheelEvent`s were dispatched directly to the canvas via `javascript_tool` to zoom out/in (a legitimate way to drive the real page, not a fabricated shortcut) — this located a chain of **~15+ distinct cyan wireframe frusta strung along an orange trajectory line**, each with a visibly different orientation consistent with a moving/panning camera sweep, isolated by toggling off Point cloud and Geometry.
- No console errors were found (checked both mid-session and after a full page reload, to catch load-time errors).
- Closed the tab and stopped both background servers (`taskkill`) when done.

**Not verified:** performance/frame-rate under load, behavior with more than one session, mobile/narrow-viewport layout, and the frusta's absolute visual scale relative to the room (sized from `camera_params`, not independently cross-checked). The existing Open3D viewer (`cli.py reconstruct`'s `--no-viewer`-gated `launch_viewer`) was not touched.

## 25. Session Log — 2026-09-21 (cont.): Task G — Supabase persistence

**New module `src/visionforge/persistence/`:**
- `backend.py`: `PersistenceBackend` ABC — `save_session`, `save_room_model`/`save_scene_graph`/`save_twin` (each returns the new version number), `save_measurements`, `save_experiment_result`, `save_processing_status`, `list_sessions`, `get_twin`.
- `local_backend.py`: `LocalJsonBackend(outputs_root=Path("outputs"))` — zero-config default. Writes each session under `outputs/<session_id>/persistence/`: `session.json` (created_at preserved across updates), `room_models/vN.json` / `scene_graphs/vN.json` / `twins/vN.json` (append-only, versioned by scanning existing `vN.json` filenames), `measurements.json`, `experiment_results/<key>.json`, `processing_status.json`.
- `supabase_backend.py`: `SupabaseBackend(url, key, client=None)` — `from supabase import create_client` at the top of *this module only*, so it's only ever imported (and only ever triggers the `supabase` import) when this specific module is loaded. `client` can be injected (e.g. a fake, for tests), bypassing `create_client` entirely. Versioning for `room_models`/`scene_graphs`/`twins` queries `select("version").eq("session_id", ...).order("version", desc=True).limit(1)` and inserts at `max + 1` (or `1`), independently per session.
- `__init__.py`: `get_backend(outputs_root=None)` reads `SUPABASE_URL`/`SUPABASE_KEY` — both set → lazily `from visionforge.persistence.supabase_backend import SupabaseBackend` (the only place `supabase-py` gets imported) and prints one line; otherwise returns `LocalJsonBackend(outputs_root=...)` and prints one line. `outputs_root` lets the API point `LocalJsonBackend` at the same root as its `SessionStore`, instead of always the real `outputs/`. `persist_run(backend, session_id, run_dir)`: the single shared function both the API's `POST /sessions/{id}/persist` and the `visionforge persist` CLI command call — builds a `DigitalTwin` from `run_dir`, derives `video_name`/`input_type`/`overall_status` from its provenance and `run_status.json`, and saves session/room_model/scene_graph/measurements (via `SpatialQueryEngine.get_room_dimensions()`, skipping any field that's `None` — never a fabricated `0`)/twin/processing_status, returning `{session_id, saved: [...]}`.

**`supabase/migrations/0001_init.sql`:** `sessions`, `room_models`/`scene_graphs`/`twins` (`session_id` FK, `version`, `payload jsonb`, `created_at`, `unique(session_id, version)`), `measurements` (one row per measurement name, not a jsonb blob — directly queryable), `experiment_results` (`session_id`, `key`, `json jsonb` — reserved, not yet written by the pipeline), `processing_status` (`session_id`, `stage`, `status`, `updated_at`). Every statement is `if not exists`, safe to re-run. No table stores frames, PLY point data, or per-frame poses as their own rows — only JSON artefacts (which themselves reference the PLY by path) and the derived `measurements` rows.

**API (`api/app.py`):** `create_app` now also builds `backend = get_backend(outputs_root=root)`, stored on `app.state.backend`.
- `POST /sessions/{session_id}/persist` → `persist_run(backend, session_id, run_dir)`.
- `GET /sessions` merges local `SessionStore` discovery with `backend.list_sessions()`; a session known only to the backend (no local run directory — the case a real Supabase project would surface) gets a reduced summary (`run_dir: null`, minimal provenance built from the `sessions` row).
- `GET /sessions/{session_id}/twin` now checks whether the local run directory still exists first; if not, falls back to `backend.get_twin(session_id)`; 404 only if neither exists.

**CLI (`cli.py`):** `reconstruct` gained `--persist` (persists as an extra step after building `twin.json`, using `get_backend()` with no `outputs_root` override — the plain zero-config default). New `persist --run-dir <dir> [--session-id <id>]` subcommand calls `persist_run` directly.

**Tests (`tests/test_persistence.py`, 26 new; `tests/test_api.py`, +4; total 116):**
- `LocalJsonBackend`: every method, version incrementing, `created_at` preserved across a session update, `get_twin` returning `None` then the latest payload, `list_sessions` ignoring run directories that were never persisted.
- `SupabaseBackend` against `FakeSupabaseClient` — a minimal in-memory stand-in for the exact `.table().select/insert/upsert/eq/order/limit().execute()` chain `SupabaseBackend` uses, with **no network access anywhere in the test suite**: upsert-not-insert on repeated `save_session`, version incrementing (and correctly *independent per session*), bulk-insert for measurements/processing_status, empty-list no-op, `list_sessions`, `get_twin`.
- `get_backend()`: defaults to `LocalJsonBackend` with no env vars; **directly asserts `"visionforge.persistence.supabase_backend" not in sys.modules`** after such a call, proving `supabase-py` is genuinely never imported when not selected (not just "the code path isn't hit" — the actual module table is checked); selects `SupabaseBackend` when both env vars are set (with `create_client` monkeypatched to avoid any real network call); falls back to local when only one of the two is set.
- `persist_run()`: end-to-end against both a real `LocalJsonBackend` (writing to `tmp_path`) and a fake-client `SupabaseBackend`, on a hand-built run directory — confirms a `None` height (no ceiling/walls in the fixture) is correctly *excluded* from persisted measurements rather than saved as a fabricated `0`.
- `test_api.py` additions: `POST /persist` end-to-end; `GET /twin` falling back to the persisted copy once the local run directory's discovery marker is removed; 404 when neither exists; `GET /sessions` surfacing a persisted-only entry (`run_dir: null`) once the local copy is gone.
- `pytest tests/`: 116/116 green.

**New `docs/supabase.md`:** env var setup, migration command (`supabase db push`, or paste into the SQL editor), the full "what is stored" table, an explicit "what is never stored" list (frames, PLY point data, per-plane PLYs, per-frame poses as their own table), and how the API/CLI entry points are used.

**Real-data verification:** ran `visionforge persist --run-dir outputs/final_demo` against the real synthetic-clip run (no env vars set, so `LocalJsonBackend`) — produced real files: `session.json` (`input_type: synthetic`, `video_name: data\input\synthetic_box_room.mp4`, `status: success`), `room_models/v1.json`, `scene_graphs/v1.json`, `twins/v1.json`, `measurements.json` (4 real rows — `length: 20.57`, `width: 8.54`, `height: 6.56` with `method: wall_extent_estimate`, `floor_area: 175.70`), `processing_status.json` (all 5 stages `success`). Also called `POST /sessions/final_demo/persist` through `TestClient(create_app(outputs_root="outputs"))` against the same real session and got the same result via the API path.

**Supabase MCP / real round-trip: not available.** `ToolSearch("supabase")` found no Supabase MCP tools configured in this environment, so the migration was never applied to a real Supabase project and no real network round-trip was performed — `SupabaseBackend` is verified only against `FakeSupabaseClient` (see above) and by code review against the actual `supabase-py` 2.31.0 API (`create_client` signature and the postgrest query-builder chain were checked directly against the installed package, not assumed). This is stated explicitly per instructions, rather than claiming a round-trip that didn't happen. If a Supabase project becomes available later: `supabase db push` (or paste `0001_init.sql`), set `SUPABASE_URL`/`SUPABASE_KEY`, then `visionforge persist --run-dir outputs/final_demo` should be the first real round-trip to try.
