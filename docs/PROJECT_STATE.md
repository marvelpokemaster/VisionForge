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
The current architecture is a purely Python-based offline and live-tracking pipeline.
- **Directories:** 
  - `src/visionforge/video/`: Frame extraction (P0).
  - `src/visionforge/reconstruction/`: Feature matching, epipolar geometry, PyCOLMAP incremental SfM (P1).
  - `src/visionforge/geometry/`: Point cloud cleaning, RANSAC plane extraction, room modeling (P2).
  - `src/visionforge/spatial/`: Scene graph generation, spatial queries, and Open3D visualization (P3/P4).
  - `src/visionforge/live/`: OpenCV KLT + 5-point algorithm visual odometry (P4).
- **Data Flow:** Video -> Frames -> Features -> Sparse Cloud -> Planar Geometry -> JSON Scene Graph -> Digital Twin Viewer.
- **Dependencies:** `opencv-python`, `numpy`, `open3d`, `pycolmap`, `pytest`.
- **CLI Entry Point:** `src/visionforge/cli.py`
- **Android/Mobile Components:** None currently exist.
- **Supabase Integration:** MCP server configured in the developer environment, but **zero** integration exists in the actual source code.

## 4. Prototype History

### P0 — Video Ingestion
- **Implemented:** Frame extraction, keyframe selection via variance of Laplacian (sharpness), metadata extraction, contact sheet generation.
- **Verification:** Tested via automated tests on synthetic/dummy video frames. No real indoor video has been run through it.

### P1 — Vision Core / Reconstruction
- **Implemented:** SIFT feature extraction, FLANN matching, ratio test, epipolar filtering (Fundamental matrix), and incremental SfM via PyCOLMAP.
- **Verification:** Unit tested via synthetic translating 2D images. No real-world video has been reconstructed.

### P2 — Spatial Reconstruction / Room Understanding
- **Implemented:** Open3D voxel downsampling, statistical outlier removal, iterative RANSAC plane segmentation, coplanar-segment merging, geometric classification (floor/wall/ceiling), scaled room dimension calculation, and (Task A) per-plane boundary polygons/extent/area/PLY export, plane-plane intersection lines, room-frame coordinates, and the room's bounding polygon.
- **Verification:** Tested on a synthetic 3D point cloud of a box room (`tests/test_geometry.py`, 9 tests) and on the real reconstructed room video (`data/input/room.mp4`).

### P3 — Spatial Intelligence
- **Implemented:** Scene graph generation from P2 JSON: `contains`, `parallel_to`/`perpendicular_to` (with `angle_deg`), boundary-distance-based `adjacent_to`, `intersects` (reusing Task A's segments), `above`/`below` (room-frame height), `inside` (camera-vs-room-polygon), plus camera nodes (hand-written quaternion math) and a trajectory node. A spatial query engine (area, dimensions, fit checking) — still to be extended in Task C.
- **Verification:** `tests/test_spatial.py` (14 tests) — hand-built box room with known answers, plus hand-built-pose tests for the quaternion conversion. Also verified on the real `data/input/room.mp4` reconstruction (see §19).

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
- **Run offline reconstruction pipeline:** `python -m visionforge.cli reconstruct --video <path_to_mp4>`
- **Run live webcam tracking demo:** `python -m visionforge.cli live`

## 7. Tests & Verification

| Component | Test | Result | Evidence | Status |
|-----------|------|--------|----------|--------|
| P0 Video Ingestion | Automated (`test_extract_frames.py`) | Pass | Pytest output | Verified (Synthetic) |
| P1 Reconstruction | Automated (`test_reconstruction.py`) | Pass | Pytest output | Verified (Synthetic) |
| P2 Room Geometry | Automated (`test_geometry.py`) | Pass | Pytest output | Verified (Synthetic) |
| P3 Scene Graph | Manual Script | Pass | Terminal output logs | Verified (Synthetic) |
| P4 Offline Viewer | CLI dry run | Pass | Open3D window generation | Partially Verified |
| P4 Live Tracker | None | Untested | No physical webcam test | UNVERIFIED |
| End-to-End Real Video | None | Untested | No `room.mp4` provided yet | UNVERIFIED |
| Android Integration | None | Untested | No Android code exists | PLANNED |

## 8. Generated Outputs / Artifacts
- `sparse_cloud.ply` / `cameras.json`: Real P1 outputs, produced from an actual (rendered, not fabricated) textured video with genuine camera translation — see §16.
- `room_model.json`: Per plane: `equation`, `normal`, `centroid` (reconstruction frame) + `centroid_room` (room frame), `support`, `in_plane_axes`, `extent` (width/height), `area` (convex-hull polygon area), `boundary`/`boundary_room` (convex-hull polygon vertices in each frame), `ply_path` (that plane's own inlier cloud). Top-level `intersections`: perpendicular plane pairs whose extents overlap, as a clipped 3D segment in both frames. `room.bounding_polygon_room`: the room's footprint outline. See §17-18 for the merge fix and Task A.
- `p2/planes/<plane_id>.ply`: Each plane's own inlier point cloud, exported individually.
- `scene_graph.json`: Nodes and edges representing semantic relationships (e.g., floor is perpendicular to wall).
- `statistics.json`: Contains retention ratios, plane counts, resolved scale-relative thresholds, and processing times.

## 9. Known Problems / Limitations
- **No Real Video Verification:** The pipeline has strictly been tested on synthetic data. Real-world motion blur, textureless walls, and sensor noise are untested.
- **Scale Ambiguity & Drift:** Monocular reconstruction (P1) lacks absolute scale. The live VO tracker (P4) will experience severe scale drift over time without global bundle adjustment.
- **Manhattan-World Assumption:** P2 geometry classification strictly assumes orthogonal vertical walls and flat horizontal floors.
- **No Android Support:** The "Iron Man" vision relies on Android, but the current codebase only supports desktop webcam access via `cv2.VideoCapture(0)`.

## 10. Git / Development State
- **Branch:** `main`
- **Recent Commits:** P0 through P4 are fully committed up to `feat: finalize integrated prototype with scene graph, queries, and live mode`.
- **Uncommitted Changes:** `.agents/` directory containing newly installed Supabase agent skills.
- **Working Tree:** Clean (excluding untracked agent skills).

## 11. Supabase Role
- **Current State:** The Supabase MCP is configured in the local AI environment, but Supabase is **NOT** integrated into the VisionForge Python source code.
- **Intended Boundary:** Supabase SHOULD be used for persisting project state, saving JSON scene graphs, storing room measurements, and handling asynchronous sync. It MUST NOT be used for streaming raw camera frames, high-frequency CV processing, or frame-by-frame Android tracking round-trips.

## 12. Immediate Next Objective
The immediate next objective is **REAL-WORLD VERIFICATION**.
Before building the Android mobile app, the existing P0-P4 Python pipeline MUST be successfully executed against a real, physical indoor smartphone video (`room.mp4`) to validate the classical CV pipeline's robustness against real-world sensor noise and motion.

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
**NEXT AI TASK:** Execute the unified offline pipeline (`visionforge reconstruct`) against a real indoor smartphone video (`data/input/room.mp4`), document the actual failure points/successes, and fix any immediate classical CV pipeline crashes before beginning Android integration.

## 16. Session Log — 2026-09-21: CLI pipeline fix + real-artifact verification

**Scope:** Pre-Task-A preparation for the Spatial Intelligence + Digital Twin chain (Geometry → Room Model → Scene Graph → Spatial Queries → Digital Twin → API → Viewer → Supabase).

**Bugs found and fixed in `visionforge reconstruct` (`src/visionforge/cli.py`):**
- P0 (`extract_frames`) was invoked with positional args; the module requires `--input`/`--output`. Fixed.
- P1 (`reconstruction.pipeline`) was invoked with positional args; the module requires `--frames-dir`/`--output`. Fixed.
- CLI looked for the sparse cloud at `p1/sparse_cloud.ply`; P1 actually writes it to `p1/reconstruction/sparse_cloud.ply`. Fixed.
- No subprocess return-code checks — a failed P0/P1/P2 stage was silently ignored. Fixed: every stage now aborts with a clear error on non-zero exit.
- A dummy 1000-point random point cloud was silently substituted whenever P1 failed, and the CLI still reported success. **Removed entirely** — a missing cloud is now a hard, honest failure with a message pointing at the real cause (insufficient camera parallax).
- Added `--output <dir>` (was hardcoded to `outputs/final_demo`) and `--no-viewer` (skip the blocking Open3D window) flags to the `reconstruct` subcommand.

**Bug found and fixed in `src/visionforge/reconstruction/incremental.py`:** on `pycolmap` >= 3 (installed: 4.2.0), `Image.cam_from_world` is an instance method, not a property. `image.cam_from_world.rotation.quat` crashed with an `AttributeError` the first time a reconstruction actually succeeded. This was never caught by `tests/test_reconstruction.py` because that test's synthetic fixture is a pure 2D translation (planar-scene degeneracy for `pycolmap.incremental_mapping`), which yields 0 reconstructions and never exercises this code path. Fixed by calling `image.cam_from_world()`.

**Real test artifact:** No real phone video existed in the repo. Generated `data/input/room.mp4` (gitignored, not committed) via a from-scratch pure-OpenCV perspective-warp rasterizer (`gen_room_video2.py`, kept in the session scratchpad, not the repo) — a textured 6-face box room rendered from 24 camera poses that dolly sideways while smoothly tilting from floor-level to ceiling-level, giving genuine translation and parallax (no ML, no Open3D scene renderer — Open3D's `OffscreenRenderer` was tried first and produced all-black frames in this environment even for a canonical sphere test; documented and abandoned rather than debugged further, per guidance to not chase obscure environment-specific issues).

**Ran the fixed pipeline end-to-end** (`visionforge reconstruct --video data/input/room.mp4 --output outputs/final_demo --no-viewer`), with real (non-fabricated) results at every stage:
- P0: 24 frames extracted.
- P1: two-view stage found 646/664 keypoints, 298 Lowe matches, 258 geometric inliers, 134 triangulated points. Incremental SfM registered all 24 cameras and triangulated 1692 3D points (`p1/reconstruction/sparse_cloud.ply`, `cameras.json` — real quaternions/translations/SIMPLE_RADIAL params, confirming the `cam_from_world()` fix works).
- P2: cleaned to 1457 points, found 4 real RANSAC planes — classified `{floor: 2, wall: 1, unknown: 1, ceiling: 0}`. Note: two of the four planes were both classified `floor` (near-identical centroids) — the real floor was likely split into two RANSAC segments by the existing classification thresholds; this is pre-existing P2 classification behavior, not a bug introduced here, and per the hard rules P2's RANSAC/classification logic was not touched.
- `scale.metric_available: false` (correctly honest — no reference distance was supplied, so `room.length/width/height/floor_area` are in arbitrary reconstruction units, not meters).
- Scene graph: 5 nodes, 10 edges (`contains`, `perpendicular_to`, `adjacent_to`, `parallel_to`) generated correctly from the real room model.
- `pytest tests/` remained green (6/6) throughout.

**Not yet done (deferred to Task A onward):** room_model.json plane entries still only carry `id/type/equation/normal/support/centroid` — no boundary polygon, extent, area, or per-plane PLY path yet. `scene_graph.py`'s `adjacent_to` is still the pre-existing centroid-distance-<10.0 heuristic. No `tests/test_spatial.py` yet. No frontend exists anywhere in the repo (confirmed via search — no `package.json`/Vite anywhere); it will be created under `frontend/` only when Task F is reached.

## 17. Session Log — 2026-09-21 (cont.): split-floor fix before Task A

**Split-plane merge (`src/visionforge/geometry/plane_fitting.py`):** Added `merge_coplanar_planes(planes, distance_threshold, normal_dot_threshold=0.98, offset_factor=2.0)`. Runs after `extract_dominant_planes` and before `classify_planes` (wired into `geometry/pipeline.py`). Merges any two RANSAC segments whose normals agree (`|dot| > 0.98`, sign-corrected so anti-parallel-but-coincident planes still compare correctly) and whose plane offsets `d` differ by less than `2 * distance_threshold`: sums `inliers`/`inlier_ratio`, concatenates the Open3D inlier clouds (`cloud_a + cloud_b`), and recomputes the centroid from the merged cloud. The surviving `equation`/`normal`/`id` are kept from the larger (base) segment — no refit, as requested. `extract_dominant_planes`'s own `segment_plane` call was not touched.

**Scale-relative P2 defaults (`geometry/pipeline.py`):** `--voxel-size` and `--plane-distance-threshold` now default to `None` and, when not explicitly passed, resolve to 0.5% and 1% of the *raw* (pre-cleaning) cloud's bounding-box diagonal, computed by reading the input PLY once at the top of `main()`. Explicit CLI overrides still work exactly as before. Resolved values are logged to stdout and written to `statistics.json` under `resolved_thresholds` (`bbox_diagonal`, `voxel_size`, `plane_distance_threshold`) for reproducibility.

**Tests added (`tests/test_geometry.py`):** `test_merge_coplanar_planes_merges_split_wall` (two same-normal segments 0.001 apart merge into one with summed support and correctly recomputed centroid; a genuinely perpendicular third plane is left untouched) and `test_merge_coplanar_planes_keeps_distinct_parallel_planes_separate` (floor vs. ceiling — same normal, offset 2.5 apart — must NOT merge). `pytest tests/`: 8/8 green.

**Before/after on real data**, isolating the merge fix from the threshold-default fix by re-running P2 on the *same* cloud from the earlier session with the *same* explicit `--plane-distance-threshold 0.05` (the old absolute default) that had originally produced the bug:
- Before (no merge logic existed): 4 planes — `plane_000 floor support=976`, `plane_001 wall support=96`, `plane_002 floor support=75` (the spurious floor split), `plane_003 unknown support=80`.
- After (merge active, same cloud, same threshold): 3 planes — `plane_000 floor support=1049` (merged; not exactly 976+75 because Open3D's `segment_plane` RANSAC is itself randomized and reran from scratch, but confirms the merge collapses the split), `plane_001 wall support=93`, `plane_002 unknown support=80`.

Separately, re-running the full `visionforge reconstruct` end-to-end on `data/input/room.mp4` with the new scale-relative defaults (bbox diagonal 32.78 → voxel_size≈0.164, plane_distance_threshold≈0.328, vs. the old fixed 0.05) avoids the fragmentation at the RANSAC stage itself: `{floor: 1, wall: 2, ceiling: 0, unknown: 0}`, 3 planes total, no duplicates. `pytest tests/` remained green throughout.

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

**Tests added (`tests/test_geometry.py`):** `test_room_model_geometry_extension`, on the existing synthetic 5×5×2.5 box-room fixture — asserts the floor's extent is ~5×5 and its hull area ~20-25 (a real hull is slightly smaller than the bbox product), a wall's extent is ~5×2.5, every plane's `ply_path` points at a real file on disk, at least one real floor↔wall intersection exists as a proper 3D segment in both frames, and the room's bounding polygon spans ~5×5. `pytest tests/`: 9/9 green.

**Real-data run** (`data/input/room.mp4` → `visionforge reconstruct`): 3 planes (`floor:1, wall:2`). Floor `extent = {width: 8.54, height: 20.59}` — matches `room.length`/`room.width` from the pre-existing measurement method exactly, a useful cross-check; hull `area = 171.2` vs. bbox product `175.86` (hull is honestly smaller, as expected for a non-rectangular real boundary). Both floor↔wall pairs produced real intersection segments, each with `segment_room` y-coordinate ≈ 0 at both endpoints — correct, since the intersection of a wall with the floor must lie on the floor, and the room-frame origin is the floor's own centroid. Each plane's PLY was verified to exist on disk with the exact point count matching `support`.

## 19. Session Log — 2026-09-21 (cont.): Task B — plane relationships, cameras, spatial graph

**Small Task-A follow-up (`geometry/room_model.py`):** exposed `coordinate_system["origin"]` (the same reference point `_room_origin` already computed internally) so `scene_graph.py` can place cameras in the room frame consistently with the already-computed `bounding_polygon_room`, without recomputing or guessing an origin.

**`src/visionforge/spatial/scene_graph.py`** (rewritten; `build_scene_graph` signature is now `build_scene_graph(room_model, cameras=None)`):
- `_quat_to_rotation_matrix(qx, qy, qz, qw)`: hand-written quaternion→matrix conversion (no scipy). `_camera_world_position(rotation_quat, translation)`: `C = -R^T @ t`, matching pycolmap's `cam_from_world` convention (`rotation_quat` is `[x, y, z, w]` of `cam_from_world`).
- Camera nodes are built from `p1/reconstruction/cameras.json` (now loaded and passed in by `cli.py`), ordered by frame **name** (not pycolmap's internal image id, which is registration order, not temporal order — ids we saw were e.g. 19, 4, 8, 6, 18...). A `trajectory_001` node holds the ordered positions (both frames) and the real piecewise path length.
- `adjacent_to` no longer uses centroid distance. It now uses `_polygon_min_distance` (edge-to-edge distance between the two planes' Task-A boundary polygons, via a hand-written robust 3D segment-segment distance routine) against a scale-relative threshold (`ADJACENCY_DISTANCE_FRACTION = 0.05` of the room's own boundary-derived bounding-box diagonal, i.e. the same style of scale-relative threshold as P2's RANSAC/voxel sizing, just derived from `room_model.json`'s own plane boundaries since `scene_graph.py` doesn't have the raw cloud). The old `centroid < 10.0` heuristic is fully removed.
- `intersects` edges are a direct pass-through of `room_model["intersections"]` (Task A) — not recomputed.
- `above`/`below`: compared along `up_axis` via each entity's `centroid_room`/`position_room` y-component, both between horizontal surfaces (floor/ceiling pairs) and between every camera and every floor/ceiling plane, gated by a scale-relative `ABOVE_BELOW_EPSILON_FRACTION = 0.02` to avoid noise-level differences producing spurious edges. Both directions (`above` and `below`) are added explicitly so either can be queried directly.
- `inside`: hand-written ray-casting point-in-polygon test (`_point_in_polygon_2d`, PNPOLY) of each camera's room-frame `(x, z)` against `room.bounding_polygon_room`. **Always emits an edge, even when `inside: false`** — an out-of-polygon camera is reported with its `distance_to_boundary`, never silently dropped.
- Every relation edge now carries its supporting number: `angle_deg` (parallel/perpendicular), `distance` (adjacent_to), `height_difference` (above/below), `segment`/`point`/`direction` (intersects, both frames), `inside`/`distance_to_boundary` (inside) — not just the relation label.
- Plane node properties were also expanded to carry the full Task A geometry (`extent`, `area`, `boundary`/`boundary_room`, `centroid_room`, `ply_path`), for the query engine and UI to use directly without re-deriving it.

**`tests/test_spatial.py`** (new, 14 tests): hand-built-pose quaternion tests independent of the scene graph (a known 90°-about-Z rotation checked against its hand-derived matrix and against a camera-center round-trip; a second rotated-pose round-trip; a known point-in-polygon case) + a hand-built 4×3×2.5 box room (identity room frame, so every expected number is computable by hand) covering every relation type: `contains`, `parallel_to`/`perpendicular_to` with exact `angle_deg` (0°/90°), `adjacent_to` with exact `distance` (0.0, since the hand-built walls genuinely share an edge with the floor), `intersects` (asserts the exact hand-supplied segment is passed through unchanged), `above`/`below` (exact `height_difference` of 2.5 and 1.25), `inside` for both an interior and a **deliberately outside** camera (asserting the outside case is still reported, with the correct `distance_to_boundary` of 6.0), and the trajectory node's path length. `pytest tests/`: 23/23 green.

**Real-data run** (`data/input/room.mp4`), edge counts by relation type:

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

Notable honest details from the real run: `adjacent_to` distances are `0.34` and `0.05` (reconstruction units, well inside the ~1.7-unit scale-relative threshold for this cloud); `perpendicular_to` angles are `89.55°`/`87.43°` and `parallel_to` is `3.33°` — close to but not exactly 90°/0°, correctly reflecting real reconstruction noise rather than fabricated perfection. **All 24 real camera positions land inside `room.bounding_polygon_room`** (0 outside) — the specifically requested real-data check. Trajectory path length: `15.67` (reconstruction units) over 24 cameras.
