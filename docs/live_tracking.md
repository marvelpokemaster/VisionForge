# Live classical tracking — Phase 3, step 1 (video file)

Status: **implemented and measured on the synthetic clip only.** No physical-camera
footage has been run through it (`data/input/room.mp4` does not exist on the
development machine, see §6). Webcam/phone streaming is a later step; this step is
the tracker core, a file-based CLI, and the measurements.

Code: `src/visionforge/live/` — `intrinsics.py`, `features.py`, `tracker.py`,
`alignment.py`, `compare.py`, `runner.py`. Tests: `tests/test_live_tracker.py` (20),
`tests/test_compare_trajectories.py` (6). Scripts: `scripts/compare_trajectories.py`,
`scripts/synthetic_clip_gt_cameras.py`.

## 1. Design

### Why keyframes + PnP (and what was wrong before)

The previous `tracker.py` prototype chained a per-frame essential matrix with
`scale = 1.0`, so every frame's translation magnitude was invented; it used a
hardcoded K; it triangulated every frame regardless of parallax into an unbounded
list; and on failure it silently reset. None of it had ever been run.

The replacement is a keyframe-based monocular visual odometry:

* **Initialisation from two keyframes, gated on parallax.** Features are detected on
  a reference frame and tracked forward. Initialisation is *attempted* only when the
  median raw displacement exceeds `init_min_parallax_px` (10 px) **and** enough
  features (≥ 10 % and ≥ 30) are *not explained by the best RANSAC homography* with
  more than 3 px residual. A homography absorbs any pure rotation (and a single
  plane); what it cannot absorb is the depth-dependent motion a translation induces.
  Static input fails the first gate, pure rotation fails the second — neither ever
  initialises (tested). The fraction, not the median, is used because one dominant
  plane (a far wall) typically holds most features.
  The pair is then solved with `cv2.findEssentialMat(..., cv2.USAC_ACCURATE)` +
  `recoverPose`, and points are triangulated with cheirality in both views,
  reprojection ≤ 2 px in both, and triangulation angle ≥ 1°. At least 30 points and
  ≥ 50 % of the E-inliers must survive. Keyframe 0 is the identity, keyframe 1 has
  a **unit baseline** — this is the arbitrary scale of the whole map.
  (USAC_ACCURATE rather than plain RANSAC because RANSAC returns the best 5-point
  sample *unrefined*; on the test fixture that was 0.25° / 3.3° rotation /
  translation-direction error at 0.5 px noise versus 0.05° / 0.2° with USAC.)
* **Tracking = PnP against the map.** Every subsequent frame's pose comes from
  `cv2.solvePnPRansac` (+ `solvePnPRefineLM` on the inliers) using the map points
  still tracked by KLT. The scale is therefore anchored to the initial map and never
  re-guessed. No motion model, no previous-pose prior is passed in.
* **Keyframes** are created when PnP inliers drop below 60 % of what the last
  keyframe had, or the median parallax to the last keyframe exceeds 20 px. Only at a
  keyframe does the map change: every track observed at an earlier keyframe is
  (re)triangulated from its **first** keyframe observation to the new one (the widest
  baseline available) with the same cheirality / reprojection / angle checks; unmapped
  tracks that pass become new points, mapped tracks only get their position replaced
  when the new pair has a larger triangulation angle. This was the single largest
  accuracy lever found while testing: triangulating only between consecutive
  keyframes gave 3.5° rotation drift and 0.25-unit median map error on the fixture;
  widest-baseline re-triangulation gives 1.0° and 0.06. Features are re-detected on
  a 6×8 grid (Shi-Tomasi, strongest-first per cell, masked away from live tracks) to
  keep coverage.
* **LOST** is entered when KLT keeps < 20 points or PnP has < 15 inliers. The
  `FrameResult.pose` is `None`, nothing is added to any map, and the tracker goes back
  to looking for a reference frame. A successful re-initialisation opens a **new
  segment** with its own frame and scale — segments are never stitched because nothing
  observed relates them. `export()` writes the segment with the most keyframes
  (mirroring `incremental.py`, which exports COLMAP's largest reconstruction) and the
  report lists every segment. The last pose is never reused or interpolated.

### What is NOT solved

* **Drift.** No bundle adjustment, no loop closure, no relocalisation against the old
  map after a loss. Errors accumulate monotonically (fixture: 1.0° / 4.6 % of path
  length at the end of a 30-frame dolly with 0.5 px noise).
* **Scale is arbitrary** (unit baseline between the first two keyframes), exactly as
  with COLMAP. `metric_available` stays `false` downstream.
* **Intrinsics** are either taken from an existing COLMAP `cameras.json` or
  **guessed** as focal = max(w, h) at the image centre — the same guess
  `reconstruction/two_view.py` makes. The guess is recorded as `"guess"` in the report.
* **Planar scenes / a single dominant plane.** Initialisation deliberately refuses
  when too few features show translation-induced parallax; a camera staring at one
  wall and translating parallel to it will stay INITIALIZING. That is intended.
* **Every frame of a 2 fps clip is a keyframe.** The synthetic clip moves ~0.16 units
  per frame, far above the 20 px keyframe parallax, so 22 of 24 frames became
  keyframes. At 30 fps (same path, 360 frames) it is 32 of 360 — see §6.
* The frontend's frustum sizing (`frontend/src/lib/frustum.ts`) reads
  `camera_params` as `[f, cx, cy, ...]` (SIMPLE_RADIAL layout). The live export is
  `PINHOLE` `[fx, fy, cx, cy]`, so the drawn frustum's aspect is wrong (cosmetic;
  positions/orientations are unaffected). Not changed in this step.

### Feature-tracking test strategy

`LiveTracker` takes a `FeatureTracker` (`detect` / `track`, see `features.py`). The
unit tests inject an **oracle** that projects the known 3D box points with the known
poses (+0.5 px Gaussian noise) and tracks by identity, going blind on all-black
frames. Rationale: the tests verify the tracker's geometry and state machine, not
OpenCV's Lucas-Kanade; identity tracking gives ground-truth correspondence per
feature, so cheirality / trajectory / map assertions are tight and deterministic. The
real Shi-Tomasi + LK path is exercised by one rendered-white-dots smoke test
(`test_real_klt_tracker_on_rendered_dots`) and by the mp4 run below.

## 2. CLI

```
visionforge live                                   # webcam demo, as before (OpenCV overlay, prints the report)
visionforge live --video <mp4> --output <dir> [--intrinsics-from <cameras.json>] [--no-gui] [--max-frames N] [--input-type synthetic|real]
```

With `--output`, the run directory gets `p1/reconstruction/{sparse_cloud.ply,
cameras.json}` (one `PINHOLE` camera per keyframe, `rotation_quat` [x,y,z,w] of
cam_from_world, the format `reconstruction/incremental.py` writes) and
`tracking_report.json`; then the **same** code path as `reconstruct` runs P2 room
geometry, the scene graph, the query demo and `twin.json`
(`cli._run_geometry_scene_graph_twin`). `visionforge twin build --run-dir <dir>` works
on the result unchanged (verified). A run that never initialises exits 1 with
`live_tracking: "failed"` in `run_status.json` instead of producing geometry from
nothing. `--no-gui` is fully headless and prints one line per frame.

Trajectory comparison:

```
python scripts/compare_trajectories.py --live outputs/live_synth --ref outputs/final_demo [--ref-step N] [--live-offset 0] [--ref-offset 1] [--output cmp.json]
python scripts/synthetic_clip_gt_cameras.py        # ground-truth cameras.json for the synthetic clip
```

Cameras are matched by **video frame index** parsed from the names (live:
`frame_000012` = video frame 12; P0/COLMAP: `frame_000013.jpg` = video frame
(13 − 1) × step, step from `p0/metadata.json`), aligned with a hand-written Umeyama
sim(3) (`alignment.py`, numpy only), and the residual RMSE is reported in the
reference's units together with the reference trajectory's bounding-box extent.

## 3. `tracking_report.json` fields

| field | meaning |
|---|---|
| `frames` | frames processed |
| `keyframes` / `n_keyframes` | video frame indices of the exported segment's keyframes |
| `state_counts` | frames per state `INITIALIZING` / `TRACKING` / `LOST` |
| `tracking_fraction` | `TRACKING / frames` |
| `lost_episodes` | `[{start, end, n_frames}]` contiguous LOST runs |
| `map_size` | points in the exported segment (= vertices in `sparse_cloud.ply`) |
| `mean_reprojection_rms` | mean over TRACKING frames of the PnP-inlier RMS (px), or `null` |
| `intrinsics` / `intrinsics_source` | fx, fy, cx, cy, k1 and `"colmap"` or `"guess"` |
| `segments` | every segment: frame range, keyframes, map size, `exported` flag |
| `exported_segment` | index of the exported segment, `null` if nothing initialised |
| `config` | the `TrackerConfig` used |
| `video` | source path, `"webcam"`, `"live:<id>"`, or `null` |
| `timing` | CLI: wall time + `process_frame_ms_*` from the runner. Live sessions (§9): `frames`, `wall_time_s`, `delivered_fps`, `process_frame_ms_{mean,p50,p95,max}` (whole feed: decode + resize + track + geometry), `track_ms_{mean,p50,p95}` (tracker only), `interarrival_ms_{mean,p50,p95,max}` between processed frames, `frames_over_100ms`, `keyframe_ms_mean` / `non_keyframe_ms_mean`. Never `null` for a live session (also in `run_status.live.timing`) |
| `keyframe_reasons` | one entry per keyframe, in order: `frame_index`, `segment`, `condition` (`init` for the initialisation pair; else `fraction` / `parallax` / `both`), and the values seen — `tracked_fraction` vs `tracked_fraction_threshold`, `parallax_px` vs `parallax_threshold_px`, `gap` since the last keyframe, `n_inliers` |

## 4. Measured numbers — synthetic clip (`data/input/synthetic_box_room.mp4`, 800×600, 24 frames @ 2 fps)

Reference: `outputs/final_demo` (COLMAP incremental SfM via `visionforge reconstruct`,
24 cameras, 1705 points). Both live runs: `--no-gui`, 24 frames in 0.7 s (≈37 fps)
on the development machine.

### Tracking reports

| | run A: guessed intrinsics | run B: `--intrinsics-from outputs/final_demo/.../cameras.json` |
|---|---|---|
| intrinsics | fx=fy=800, cx=400, cy=300, k1=0 (`guess`) | fx=fy=794.97, cx=400, cy=300, k1=0.00455 (`colmap`, first COLMAP camera) |
| frames / keyframes | 24 / 22 (frames 0, 3, 4, …, 23) | 24 / 22 |
| states | INITIALIZING 3, TRACKING 21, LOST 0 → 87.5 % TRACKING | same |
| LOST episodes | 0 | 0 |
| map size | 842 | 843 |
| mean reprojection RMS | 0.365 px | 0.364 px |

`outputs/live_synth/tracking_report.json` (run A, `config` omitted):

```json
{"frames": 24, "keyframes": [0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
 "n_keyframes": 22, "state_counts": {"INITIALIZING": 3, "TRACKING": 21, "LOST": 0}, "tracking_fraction": 0.875,
 "lost_episodes": [], "map_size": 842, "mean_reprojection_rms": 0.36471710082621883,
 "intrinsics": {"fx": 800.0, "fy": 800.0, "cx": 400.0, "cy": 300.0, "k1": 0.0, "source": "guess"},
 "intrinsics_source": "guess",
 "segments": [{"index": 0, "start_frame": 0, "end_frame": 23, "n_keyframes": 22, "map_size": 842, "exported": true}],
 "video": "data\\input\\synthetic_box_room.mp4", "exported_segment": 0}
```

Run B differs only in `intrinsics` (`source: "colmap"`), `map_size: 843`,
`mean_reprojection_rms: 0.36364022230883347`.

### Trajectory RMSE (sim(3)-aligned, `scripts/compare_trajectories.py`)

| comparison | matched cameras | RMSE | % of reference extent | median / max residual |
|---|---|---|---|---|
| live A vs COLMAP | 22 of 24 | 0.2959 COLMAP units | 2.44 % (extent 12.150) | 0.118 / 0.646 |
| live B vs COLMAP | 22 of 24 | 0.2942 | 2.42 % | 0.128 / 0.638 |
| live A vs live B | 22 | 0.0213 | 0.35 % | 0.019 / 0.040 |
| **COLMAP vs ground truth** | 24 of 24 | 0.0867 GT units | **2.41 %** (extent 3.600) | 0.034 / 0.198 |
| **live A vs ground truth** | 22 of 24 | 0.0076 GT units | **0.21 %** | 0.0065 / 0.017 |
| **live B vs ground truth** | 22 of 24 | 0.0136 GT units | **0.38 %** | 0.013 / 0.023 |

Ground truth = the camera path `scripts/generate_synthetic_clip.py` renders
(`scripts/synthetic_clip_gt_cameras.py`). Readings:

* The 2.4 % live-vs-COLMAP difference is almost entirely **COLMAP's** error on this
  clip, not the live tracker's: against truth the live tracker is at 0.21 %. COLMAP
  fitted a separate SIMPLE_RADIAL camera to each of the 24 images (24 distinct
  `camera_params`, focal 775–832 for a true 800), which is where its 2.4 % comes from.
* **The intrinsics comparison here is not a fair test of "guess vs calibrated".**
  The clip is rendered with focal = max(w, h) = 800 at the exact centre — the guess is
  *exactly right by construction*. Run B uses COLMAP's first camera (794.97, k1 0.0045),
  i.e. slightly *wrong* intrinsics, and is correspondingly a little worse (0.38 % vs
  0.21 %). On real footage the direction is expected to reverse; untested.
* The two live runs agree with each other to 0.35 %.

### P2 room geometry + twin on the live output, next to the COLMAP-based result

| | COLMAP (`outputs/final_demo`) | live A (`outputs/live_synth`) | live B (`outputs/live_synth_colmap`) |
|---|---|---|---|
| raw → cleaned points | 1705 → 1339 | 842 → 812 | 843 → 804 |
| planes found | 3 | 3 | 3 |
| classifications | floor 1, wall 2, ceiling 0, unknown 0 | floor 1, wall 2, ceiling 0, unknown 0 | floor 1, wall 2, ceiling 0, unknown 0 |
| plane support (floor / wall / wall) | 1022 / 133 / 104 | 604 / 93 / 74 | 598 / 95 / 74 |
| plane area (floor / wall / wall) | 170.8 / 38.3 / 26.9 | 65.9 / 18.1 / 11.7 | 67.7 / 19.2 / 12.3 |
| room length / width / height | 20.57 / 8.54 / 6.56 | 12.48 / 5.09 / 4.13 | 12.65 / 5.17 / 4.21 |
| height method | wall_extent_estimate | wall_extent_estimate | wall_extent_estimate |
| length : width ratio | 2.41 | 2.45 | 2.45 |
| `twin build --run-dir` | works | works (stage_status: live_tracking, p2, scene_graph, twin all `success`) | works |

All units are each reconstruction's own arbitrary scale, so absolute numbers are not
comparable across columns; the ratios and the plane counts / classifications are.
The live map is sparser (842 vs 1705 points, each point observed by at most a few
keyframes with no BA) and yields the same three planes with the same labels as the
COLMAP-based result.

**But the labels are wrong in every column, COLMAP included** (found in the 30 fps
follow-up, §6, by mapping each plane into the ground-truth frame): the plane P2 calls
`floor` — 1022 points for COLMAP, 604 for live — has normal (0, 0, −1) at z ≈ −3 in
the generator's coordinates, i.e. it is the **far wall**; the two `wall` planes are the
real side walls x = ±3. No floor plane is detected in any run: only 59 (COLMAP) / 75
(live) of the cloud points lie within 0.15 units of the true floor, versus 1356 / 621 on
the far wall, because the clip sees the floor only at grazing angles. P2's
`classify_planes` then takes the largest plane as the floor
(`docs/real_video_checklist.md` §4 warned exactly this), so every downstream
`room.length/width/height` number for this clip is measured against the wrong
surface. This is pre-existing P2 behaviour on this clip, not introduced by the live
tracker, and it is not fixed in this step — but it is now proven rather than suspected.

### Unit-test fixture (box room, 30-frame dolly with small yaw/pitch, 0.5 px noise, oracle tracking)

* initialisation at frame 2; 10 keyframes; 276 map points
* keyframe centres vs ground truth, sim(3)-aligned: RMSE 0.011 units = **0.5 %** of the
  2.24-unit trajectory extent (test tolerance 2 %)
* rotation relative to keyframe 0: ≤ **1.0°** at the end of the path (tolerance 2°)
* map vs ground truth in the init-pair frame: median **0.06**, p90 0.19 units in a
  6 × 2.5 × 6 room (tolerances 0.15 / 0.40)
* static and pure-rotation (1°/frame, 30 frames) sequences: 30 × INITIALIZING, no segment
* 10 black frames mid-sequence: one LOST episode (frames 15–26, poses `None`), then
  re-initialisation into a second segment
* real KLT on rendered dots: TRACKING on 25 of 30 frames, sim(3) RMSE 0.1 % of extent

## 5. Reproducing

```
python scripts/generate_synthetic_clip.py                                   # if data/input/synthetic_box_room.mp4 is missing
python -m visionforge.cli reconstruct --video data/input/synthetic_box_room.mp4 --output outputs/final_demo --no-viewer --input-type synthetic
python -m visionforge.cli live --video data/input/synthetic_box_room.mp4 --output outputs/live_synth --no-gui --input-type synthetic
python -m visionforge.cli live --video data/input/synthetic_box_room.mp4 --output outputs/live_synth_colmap --no-gui --input-type synthetic \
    --intrinsics-from outputs/final_demo/p1/reconstruction/cameras.json
python scripts/compare_trajectories.py --live outputs/live_synth --ref outputs/final_demo
python scripts/synthetic_clip_gt_cameras.py
python scripts/compare_trajectories.py --live outputs/live_synth --ref outputs/synthetic_gt_cameras.json --ref-offset 0
python scripts/compare_trajectories.py --live outputs/final_demo --live-offset 1 --ref outputs/synthetic_gt_cameras.json --ref-offset 0
pytest tests -q            # pytest.ini sets pythonpath = src
```

## 6. 30 fps follow-up — same path, 360 frames (`data/input/synthetic_box_room_30fps.mp4`)

`python scripts/generate_synthetic_clip.py --output data/input/synthetic_box_room_30fps.mp4 --frames 360 --fps 30`
renders the **same camera path** (the generator's `linspace` over the frame count) at
30 fps; `scripts/synthetic_clip_gt_cameras.py --frames 360` gives its ground truth.
Run: `visionforge live --video data/input/synthetic_box_room_30fps.mp4 --output outputs/live_synth_30 --no-gui --input-type synthetic`.

| | 2 fps clip (24 frames) | **30 fps clip (360 frames)** |
|---|---|---|
| keyframes | 22 (91.7 % of frames) | **32 (8.9 % of frames)**: 0, 19, 34, 48, 61, 73, 85, 96, … 343, 357; gaps 10–15 frames |
| states | INIT 3 / TRACKING 21 / LOST 0 → 87.5 % | INIT 19 / **TRACKING 341** / LOST 0 → **94.7 %** |
| LOST episodes | 0 | 0 |
| map size | 842 | 897 |
| mean reprojection RMS | 0.365 px | 0.506 px |
| wall time | 0.7 s total | 4.9 s total, **13.6 ms/frame wall**; `process_frame` mean 11.9 ms, median 10.7, p95 30.7, max 40.3 |
| keyframe vs non-keyframe cost | – | **keyframes 31.4 ms, other frames 10.1 ms; 16 frames > 33 ms, all 16 keyframes** |
| sim(3) RMSE vs ground truth | 0.0076 (0.21 % of extent) | **0.0653 (1.82 % of extent 3.580)**, median 0.061, max 0.102 |
| P2 planes | 3 | 4 on the first P2 run, 3 on a re-run of P2 on the same cloud (RANSAC is randomised) |
| P2 labels | floor 1, wall 2 (see §4: "floor" = far wall) | run 1: floor 1, wall 3; run 2: floor 1, ceiling 1, wall 1 — the far wall (565 pts) labelled `wall`, the side walls labelled `floor` / `ceiling` |

Readings:

* **The keyframe parallax gate throttles.** 32 keyframes for 360 frames, spaced
  10–15 frames = the ~20 px median parallax at this speed; the gate is not firing per
  frame. Locked in by `test_30fps_resampled_path_keyframes_are_a_small_fraction_of_frames`:
  the unit fixture's path resampled to 360 frames (oracle tracking) gives 13 keyframes
  (3.6 %), 344/360 TRACKING, 0 LOST, 0.24 % RMSE; the real KLT on rendered dots gives
  13 keyframes, 343/360 TRACKING, 0.45 %. (The test asserts ≤ 10 % keyframes, ≥ 90 %
  TRACKING, no LOST, < 2 % RMSE.)
* **Per-frame budget.** Non-keyframes average 10.1 ms (LK forward+backward on ~500
  features + PnP) — inside the 33 ms live budget at 800×600 on this machine. Keyframes
  average 31.4 ms and are the only frames over 33 ms (16 of 32), because they add
  grid re-detection (`goodFeaturesToTrack` with a mask) and widest-baseline
  re-triangulation. Not optimised in this step; the obvious levers are a cheaper
  detector (FAST) and triangulating only the tracks whose angle grew.
* **Accuracy is worse at 30 fps on the textured clip (1.82 % vs 0.21 %) but not on
  the fixture (0.24 % oracle / 0.45 % dots at 360 frames vs 0.5 % / 0.1 % at 30).**
  So the keyframe rate itself is not the cause. The residual profile is bowed (0.10
  at the first keyframe, 0.04 in the middle, 0.08 at the end) and the map is much
  noisier in depth: only 110 of 897 points lie within 0.15 units of the far wall,
  versus 621 of 842 at 2 fps. Working hypothesis, not verified: KLT drift on the
  textured frames — a feature tracked for 100+ frames walks off its original point,
  and widest-baseline re-triangulation pairs that drifted position with its exact
  first-keyframe position. The oracle (identity tracking) and the crisp rendered dots
  have no such drift. Candidate fixes for a later step: cap track age / verify long
  tracks against their keyframe patch, or re-detect on every keyframe and retire
  old tracks.
* **P2 labelling is unstable on this cloud**: two P2 runs on the identical
  `sparse_cloud.ply` gave {floor 1, wall 3} and {floor 1, ceiling 1, wall 1}. Together
  with §4's finding (the "floor" is the far wall in every run), the plane *counts* are
  reliable here but the *classes* are not — that is P2's up-vector inference, outside
  this step.

## 8. Incremental geometry (Phase 3 step 3)

Step 2's live session needs P2 on a *growing* cloud, in memory, every few
seconds. `src/visionforge/geometry/api.py` and `incremental.py` provide that
without changing a number in the file-based path.

### API

```python
from visionforge.geometry.api import GeometryOptions, build_room_model
from visionforge.geometry.incremental import IncrementalRoomModel

res = build_room_model(points, cameras, GeometryOptions(), seed=0)   # points (N,3); cameras = cameras.json list or None
res.room_model        # the dict room_model.json would contain, byte-for-byte the same structure (incl. ply_path)
res.plane_inliers     # {plane_id: indices into res.cleaned_points}
res.statistics        # the statistics.json dict (processing_time_seconds = build time)
res.cleaned_points    # (M,3) voxel-downsampled + outlier-filtered cloud the planes were fitted to

inc = IncrementalRoomModel(GeometryOptions(), min_points=200, min_new_points=100, min_interval_s=2.0, seed=0)
r = inc.update(points, cameras, now=t)   # RoomModelResult, or None when gated; inc.latest keeps the last one
```

`GeometryOptions` mirrors `pipeline.main()`'s CLI arguments with the same
defaults (asserted by `test_geometry_options_defaults_match_the_cli_parser`).
`pipeline.main()` is now a thin wrapper: read PLY + cameras → `build_room_model`
→ write the same nine files (`pointcloud/{raw,cleaned}.ply`, `planes/<id>.ply`,
`room_model.json`, `visualizations/{detected_planes,coordinate_frame}.ply`,
`statistics.json`); exit codes and messages unchanged. Only two stdout
progress lines moved ("Loaded camera poses" now precedes the cloud statistics;
"Exporting per-plane point clouds" now follows "Measuring room"); nothing
parses them.

`IncrementalRoomModel.update` re-fits only when the cloud grew by
≥ `min_new_points` **and** ≥ `min_interval_s` passed since the last fit
(`now` is injectable); otherwise it returns `None`. Below `min_points` it
returns an explicit empty result — zero planes, every `room.*` field `null`,
a `reason` string — never a guess. A re-initialised tracker segment should
create a new `IncrementalRoomModel` (different frame). An optional
`prefilter_voxel_size` (incremental only) bounds cost on big clouds; it was not
needed (see timing).

### Randomness, and how equivalence was proven

The only random step in P2 is Open3D's `PointCloud.segment_plane` RANSAC.
`seed` (also `--seed` on `geometry.pipeline`, `reconstruct` and `live`) calls
`o3d.utility.random.seed` + `numpy.random.seed`, as requested — **but Open3D
0.20's `segment_plane` is not reproducible under that seed**: seeding before
every call on the same cleaned cloud still gives different models (4 calls →
3–4 distinct, with and without `OMP_NUM_THREADS=1`; pinned by
`test_seeded_segment_plane_is_not_reproducible`, which fails loudly if a future
Open3D becomes deterministic). The cleaning stage *is* deterministic
(`test_clean_point_cloud_is_deterministic`).

So the equivalence proof is **exact by replay, tolerance with live RANSAC**:

* `tests/fixtures/p2/{final_demo,live_synth_30}/` hold the input PLY +
  `cameras.json`, the RANSAC draws (model + inlier list of every
  `segment_plane` call, in order) recorded from one run of the **pre-refactor**
  `pipeline.main()`, and that run's `room_model.json`, `statistics.json` and
  file list.
* `test_build_room_model_equals_prerefactor_output_given_same_ransac_draws`
  and `test_main_writes_prerefactor_files_given_same_ransac_draws` replay the
  draws (asserting the same call sequence on clouds of the same sizes) into
  the new API and the new `main()`: `room_model.json` and `statistics.json`
  (minus wall time) are **equal to the pre-refactor output, exactly**, and the
  same nine files are written — on both the COLMAP cloud and the live 30 fps
  cloud.
* `test_main_and_build_room_model_agree_to_tolerance_with_real_ransac`: with
  real RANSAC, `main()` (subprocess), `build_room_model` and the reference agree
  on plane count, normals (|dot| > 0.995), support (±5 %); plane *types* are
  only asserted on `final_demo` — on `live_synth_30` they are known to flip
  between runs (§6).

Before/after on the 2 fps clip, both CLIs run with `--seed 0` (task 5):

| | P1 cloud before vs after | `room_model.json` |
|---|---|---|
| `visionforge live --output` | **byte-identical** (`md5 cc7f0f3d…`, the tracker is deterministic) | not byte-identical: same 3 planes, same types, normals within 0.36°, support 605/93/78 vs 604/92/74, room L/W/H 12.485/5.150/4.125 vs 12.482/5.110/4.057 |
| `visionforge reconstruct` | **different** (COLMAP is not deterministic run to run) | not comparable: the two COLMAP clouds are in different gauges (normals differ by 15–18°); same 3 planes/types, L/W/H 19.76/7.89/6.66 vs 19.94/7.98/6.76 |

Byte-identical `room_model.json` is therefore **not achievable** with Open3D's
RANSAC; the replay tests are the proof that the refactor changed nothing. The
one way to get true reproducibility would be a seeded numpy RANSAC behind
`extract_dominant_planes` — a change to P2's extraction, left to its owner.

### Timing (`build_room_model`, this machine, min of 3)

| cloud | points | cleaned | planes | wall time |
|---|---|---|---|---|
| live_synth_30 | 897 | 817 | 4 | **0.014 s** |
| 10× jittered copies | 8 970 | 3 356 | 4 | **0.040 s** |
| 50× jittered copies | 44 850 | 5 459 | 4 | **0.070 s** |

(50× breakdown: cleaning 0.013 s → 5 414 points; one `segment_plane` 0.001 s.)
Far below the 2 s bound, so no pre-downsample is needed; `prefilter_voxel_size`
exists but is off by default (at 50× with 2× the default voxel it drops the fit
to 1 576 points / 0.030 s). **Refresh interval for step 2:** compute is not
the limit — a 1 s `min_interval_s` with `min_new_points=100` costs < 0.1 s per
refresh even at 45 k points; the real constraint will be the JSON size sent
to the client, not P2.

## 9. Live session protocol (Phase 3 step 2)

`src/visionforge/live/session.py` (`LiveSession`) + `src/visionforge/api/live.py`
(mounted by `create_app`). A client streams JPEG frames over one WebSocket; the
server tracks them with `LiveTracker`, re-fits the room model with
`IncrementalRoomModel` on the **active tracker segment** (in memory:
`segment_points` / `segment_cameras` → `build_room_model` → `build_scene_graph`
→ `DigitalTwin.from_parts`), pushes a status per processed frame, and on
`finish` exports a run directory identical in layout to `visionforge live
--output`, registered in the `SessionStore` so the REST API and frontend open it
like any other session.

### Messages

| direction | message | meaning |
|---|---|---|
| client → | text `{"width": W, "height": H, "intrinsics": {fx,fy,cx,cy,k1,source?}?}` or `{"intrinsics_from_cameras": [cameras.json entries], "intrinsics_size": [w,h]?}`, plus `"record": true?` | optional, before the first frame: frame size and/or intrinsics **for that size** — or, with `intrinsics_size` (or `width`/`height` on the cameras entry, as `visionforge calibrate` writes), for another size with the same aspect ratio, rescaled server-side before the downscale. `intrinsics.source` is `client` (default) or `phone_default` (the Live screen's 0.8 × longer-side stopgap). `record` keeps every received frame (below) |
| ← server | text `{"configured": true, "intrinsics": {...}, "processed_size": [w,h], "recording": bool, "keyframe_min_gap": 3}` | |
| client → | **binary** JPEG | one frame; the server assigns `frame_index` = frames received so far |
| ← server | text status (below) | one per **processed** frame (dropped frames get none) |
| client → | text `{"cmd": "finish"}` | process what is pending, export, build P2/scene graph/twin |
| ← server | text `{"finished": true, "session_id", "run_dir", "stage_status", "frames", "received", "dropped", "twin_updates"}` then close 1000 | |

Status fields: `session_id, frame_index, state (INITIALIZING|TRACKING|LOST),
n_tracked, n_inliers, reprojection_rms, is_keyframe, map_size, n_keyframes,
segment, n_segments, frames, dropped, source_size, processed_size,
intrinsics_source, pose ({rotation_quat [x,y,z,w] of cam_from_world,
translation} or null — null whenever not TRACKING, never the last pose),
twin_update` (a full `DigitalTwin.to_dict()` **only on the frame where the
incremental geometry re-fitted**, else null).

`GET /live` lists active sessions (`frames`, `dropped`, `twin_updates`,
`last_status`); `DELETE /live/{id}` closes the socket (1001 "deleted") and
drops it. A second socket on an active id is accepted and closed with **4409**
"already active"; an invalid id with 4400.

### Limits and behaviour

* **Downscale:** frames wider than `max_width` (640) are resized before
  tracking and the intrinsics (given or guessed) are scaled with them; `k1` is
  unchanged (normalised coordinates). `processed_size` and the exported
  `tracking_report.json` intrinsics are the scaled ones. The frame size may not
  change mid-session.
* **Frames are not stored unless asked.** The tracker keeps one previous
  grayscale frame (KLT needs it); nothing else. With `"record": true` in the
  configure message (`live/recording.py`) every **received** JPEG — including
  the ones backpressure then drops — is written to
  `outputs/<id>/frames/<frame_index:06d>.jpg`, indexed by
  `outputs/<id>/frames.jsonl` (`frame_index, received_at, bytes, file,
  processed`) with the configure message in `outputs/<id>/configure.json`;
  the `finished` reply and `run_status.live.recording` give the counts. A
  recording is replayed at its original timing with
  `scripts/replay_live.py --frames-dir outputs/<id>/frames [--fps N]
  [--processed-only] [--record]`, or run offline — same bytes, same frame
  indices, recorded intrinsics, live tracker settings — with
  `visionforge live --frames-dir outputs/<id>/frames --output <dir2>
  [--processed-only]` (`live/offline.py`). `frames/` is never a session, never
  provenance, never persisted. This is how real footage gets tuned without
  re-walking the room.
* **Keyframe gap:** live sessions use `keyframe_min_gap = 3` (§11); the CLI
  keeps `TrackerConfig`'s 1. Every keyframe's reason is in
  `tracking_report.keyframe_reasons` (§3).
* **Timing:** `tracking_report.timing` / `run_status.live.timing` (§3) are
  measured by the session itself — process time per frame, inter-arrival
  interval, delivered fps.
* **Map cap:** `TrackerConfig.max_map_points` (20 000 for live sessions, unbounded
  for the CLI): after each keyframe the oldest map points not observed by any live
  feature track are dropped until the segment is under the cap. Measured points
  are forgotten, never invented.
* **Geometry refresh:** `IncrementalRoomModel(min_interval_s=1.0, min_new_points=50,
  min_points=200)` per segment; a re-fit below `min_points` yields a twin whose
  `room_model` has zero planes and a `reason` (`p2_room_geometry: "skipped"`).
* **LOST / re-initialisation:** the status says LOST with `pose: null`; a
  successful re-initialisation opens a new tracker segment (`segment` increments)
  and the session starts a **fresh `IncrementalRoomModel`** — points of different
  segments are never fitted together. On finish the segment with the most keyframes
  is exported (`tracking_report.segments` lists all).
* **Backpressure:** the socket task only parks the newest frame; a worker task
  hands it to a thread (the tracker is CPU-bound, the event loop stays responsive).
  A frame arriving while one is being processed **replaces** the parked one and
  `dropped` increments. `finish` first drains what is parked.
* **finish when nothing initialised:** `run_status.json` gets
  `live_tracking: "failed"` + an `error`, there is no `p2/`, `cameras.json` is
  `[]`, and a `twin.json` with `room_model: null` is still written so
  `GET /sessions/{id}/twin` answers 200 with that provenance (and
  `/room_model`, `/measurements` 404) — honest, not a 500. If P2 itself fails on a
  real map, the stage is marked `failed` with the error and the twin says so.

### Measured: `scripts/replay_live.py` against uvicorn (30 fps clip, 10 fps, 640 wide)

```
$ python scripts/replay_live.py --video data/input/synthetic_box_room_30fps.mp4 --url ws://localhost:8765/live/live_ws_demo --fps 10 --max-width 640
source 800x600 -> sending 640x480 at 10.0 fps to ws://localhost:8765/live/live_ws_demo
configured: {"configured":true,"session_id":"live_ws_demo","intrinsics":{"fx":640.0,"fy":640.0,"cx":320.0,"cy":240.0,"k1":0.0,"source":"guess"},"processed_size":[640,480]}
[    0] INITIALIZING tracked= 210 inliers=   0 rms=    - map=    0 kf=  0 seg=None dropped=0 -
[    1] INITIALIZING tracked= 210 inliers=   0 rms=    - map=    0 kf=  0 seg=None dropped=0 -
...
[   28] TRACKING     tracked= 245 inliers= 199 rms= 0.06 map=  199 kf=  2 seg=0 dropped=0 KF twin_update(planes=0, reason='199 points < min_points=200')
[   61] TRACKING     tracked= 257 inliers= 215 rms= 0.51 map=  266 kf=  4 seg=0 dropped=0 KF twin_update(planes=3)
[   90] TRACKING     tracked= 303 inliers= 243 rms= 0.39 map=  328 kf=  6 seg=0 dropped=0 KF twin_update(planes=2)
...
[  359] TRACKING     tracked= 344 inliers= 339 rms= 0.54 map=  724 kf= 25 seg=0 dropped=0 -
sent 360 frames; sending finish
finished: {"finished": true, "session_id": "live_ws_demo", "run_dir": "outputs\\live_ws_demo", "stage_status": {"live_tracking": "success", "p2_room_geometry": "success", "scene_graph": "success", "twin": "success"}, "frames": 360, "received": 360, "dropped": 0, "twin_updates": 8}
statuses received: 360, twin updates: 8
```

360 frames in 40 s wall (paced at 10 fps by the client), 0 dropped, 8 twin
updates, 25 keyframes, 724 map points at 640×480 (the 800×600 CLI run gave 32 /
897), finish built `p2/` (3 planes), `scene_graph.json`, `twin.json`. The session
is then a normal session: `GET /sessions/live_ws_demo/twin` serves it. The first
twin update at frame 28 reports zero planes with the reason, not a guess.

## 10. Live screen (Phase 3 steps 4+5)

Route `#/live` (also `/live`) in the React/Capacitor frontend. Files:
`frontend/src/live/{source,encode,pump,status,wsUrl}.ts`,
`components/LiveScreen.tsx`, `lib/route.ts` (+ `useRoute.ts`). The existing
session view is unchanged apart from reading the route and a "● Live tracking"
button; `Viewer3D` gained one optional prop, `cloudUrl`.

* **Sources** (`source.ts`): `CameraSource` (getUserMedia, rear camera preferred)
  and `FileSource` (`<input type=file>` → `<video>`); both expose
  `start() → {width, height}`, `frame()`, `stop()`. No frames are stored.
* **Pump** (`pump.ts`, pure, tested with fake timers): every `1/fps` (10 fps)
  it asks the encoder (`encode.ts`: canvas at ≤ 640 px wide, JPEG q 0.7) for a
  frame and sends it as one binary message, after the `{"width","height"}` text
  message. It never queues: a tick is skipped and counted when the last send
  was < 1/fps ago (`rate`), when `ws.bufferedAmount` exceeds one frame's bytes
  (`buffer`), when an encode is still in flight (`busy`), or when the source
  has no frame (`no-frame`). Stop sends `{"cmd":"finish"}`; the server's
  `finished` reply ends the session. A file source stops by itself at its end.
* **Status reducer** (`status.ts`, pure, tested): state, counts, server
  `dropped`, client `skippedClient`, measured fps (statuses/s over the last 10),
  `lastTwin` (a new object only when `twin_update` is non-null — the viewer's
  rebuild effect keys on it), `twinUpdates`, `lostEpisodes` (start/end frame),
  segment changes.
* **Screen**: session id (default `live-<timestamp>`), source selector, Start /
  Stop, preview, the status strip, a full-width banner — amber INITIALIZING with
  "translate the camera sideways", green TRACKING, blinking red LOST — and
  `Viewer3D` fed with `lastTwin` and `cloudUrl = /live/<id>/cloud` (the active
  segment's current map as PLY, served by the backend so the live points go
  through the same PLY + `frames.ts` room-frame path as a finished session).
  "no geometry yet: <reason>" is shown when a twin update has zero planes and a
  reason. On `finished` the app navigates to `#/session/<id>`.
* **ws URL** (`wsUrl.ts`, tested): from the same `API_BASE` as `lib/api.ts` —
  `http://…` → `ws://…`, `https://…` → `wss://…`, relative `/api` →
  `ws(s)://<page host>/api` (Vite's dev proxy now has `ws: true`). The Android
  build therefore uses `ws://10.0.2.2:8000/live/<id>` (grep `dist/` for
  `10.0.2.2:8000` and `wss://` after `npm run build`).
* **Android**: `CAMERA` permission + `<uses-feature android.hardware.camera
  required=false>` in the manifest; `androidScheme: 'http'` keeps `ws://` from
  being mixed content; `npm run build && npx cap sync android` done.
  Emulator: done, see "Stage 1" below; **phone untested** — see
  `docs/live_android_checklist.md`.

### Desktop verification (real Chrome, DevTools protocol, no extension)

The Claude-in-Chrome extension was not connected, so `scripts/drive_live_ui.py`
drives a real headless Chrome (fake media device enabled) against the Vite dev
server (5173, proxying to uvicorn on 0.0.0.0:8000): it selects the source,
clicks Start, reads the banner / strip / viewer canvas once a second, clicks
Stop and checks the hand-off. Browsers do not play OpenCV's default `mp4v`
clips, so the clip is re-rendered as VP8/WebM
(`generate_synthetic_clip.py --fourcc VP80 --output ….webm`, same frames).

File source (`synthetic_box_room_30fps.webm`), observed per second:

```
t= 1s INITIALIZING canvas=False | frame 3 tracked 200 inliers 0 map 0 keyframes 0 … skipped 3 5.1 fps twin updates 0 | waiting for the first twin update…
t= 2s TRACKING     canvas=False | frame 8 tracked 242 inliers 183 map 190 keyframes 2 segment 0 dropped 0 skipped 8 5.0 fps twin updates 1 | no geometry yet: 190 points < min_points=200
t= 3s TRACKING     canvas=True  | frame 11 tracked 266 inliers 232 map 247 keyframes 3 … twin updates 2
t= 8s TRACKING     canvas=True  | frame 29 tracked 391 inliers 372 map 566 keyframes 13 … twin updates 6
t=12s TRACKING     canvas=True  | frame 42 tracked 340 inliers 330 map 694 keyframes 18 … 3.3 fps twin updates 8   (video ended)
clicked Stop … hash after finish: #/session/live-1792100321625
session view: selected "live-1792100321625", canvas: true, measurements: Length 4.672 Width 3.803 Height 14.882 (floor_to_ceiling) …
states seen: ['INITIALIZING', 'TRACKING'] | first viewer canvas at 3.1 s | console errors: []
```

What rendered (screenshots in `outputs/live_ui/`): the preview showed the
textured box room playing; the banner went amber INITIALIZING → green
TRACKING; the strip updated every status; at frame 12 the viewer drew two
translucent planes (green `plane_000 (floor)`, red `plane_001 (wall)`) with
labels, the yellow room polygon and the live map as white dots, and at frame 42
a different set (a large red wall, `plane_002 (floor)`) — i.e. planes really
are redrawn on each twin update, and P2's label instability (§6) is visible
live. After Stop the session view opened on the new session with the 3D twin,
Room Measurements and the provenance footer. uvicorn:

```
INFO:  "WebSocket /live/live-1792100321625" [accepted]
INFO:  connection open
INFO:  "GET /live/live-1792100321625/cloud HTTP/1.1" 200 OK   (×7, one per twin update)
3 planes remain after merging coplanar segments.
Classifications: {'floor': 1, 'ceiling': 1, 'wall': 1, 'unknown': 0}
INFO:  "GET /sessions/live-1792100321625/measurements HTTP/1.1" 200 OK
INFO:  "GET /sessions/live-1792100321625/twin HTTP/1.1" 200 OK
INFO:  "GET /sessions/live-1792100321625/cloud HTTP/1.1" 200 OK
```

Delivered rate: the first run gave 3–5 statuses/s for 10 fps requested. The
strip's skip breakdown (added for this) showed `busy 11 / rate 46`: the pump's
rate gate measured from the previous send's *completion*, so a ~50 ms async
JPEG encode pushed every second tick inside the window — a pump bug, fixed
(the gate now measures from the tick that captured the previous frame). Re-run:
**6.0 statuses/s, 64 frames in the 12 s clip, `busy 22 / rate 22 / buffer 0`**
— the remaining `busy` skips are encodes over 100 ms on headless Chrome's
SwiftShader renderer; a GPU-backed browser or phone should do better. The
server never dropped a frame (`dropped 0`) and the file source stopped by
itself at the end of the clip ("video ended — finishing" → `finished` →
session view).

Camera source (Chrome's fake device, 640×360): getUserMedia succeeded, statuses
flowed at ~5/s, the banner stayed **INITIALIZING** for all 64 frames (a fake
pattern has no parallax — exactly the emulator caveat), Stop → `finished` with
`live_tracking: failed`, navigation to the session view, which shows the
honest `GET …/measurements failed: 404` and no geometry. (Follow-up for the
session view, out of scope here: it loads twin and measurements together, so a
failed live session shows the error instead of the twin's `stage_status`.)

No physical webcam is attached to this PC, so a real camera was not tried.

### Stage 1 — Android emulator (human test, 2026-10-16)

Android Studio emulator, `VITE_API_BASE_URL=http://10.0.2.2:8000`, uvicorn on
the PC (`docs/live_android_checklist.md` §1):

* CAMERA permission prompt shown, getUserMedia OK on the virtual camera.
* `WS /live/<id>` accepted; strip live; **254 features tracked**; banner stayed
  **INITIALIZING** — the virtual camera is static (no parallax), which is the
  tracker's honest answer, not a bug.
* **0.2 fps delivered**: the emulator's WebView JPEG-encodes the canvas in
  software, so nearly every pump tick was a `busy` skip. The pump never queued
  and counted every skip, as designed; the figure is the emulator's.
* Stop → `finished` → session list with the session marked `live_tracking:
  failed` / `twin: success`.

Three issues, fixed in step 6 prep (below): (a) the session view showed
`GET …/measurements failed: 404` instead of the twin's `stage_status`; (b)
the VP8/WebM test clip did not decode in the emulator's WebView ("no
supported source was found"); (c) Android back from the file picker exited
the app.

### Step 6 prep (phone)

* **Runtime backend URL.** `lib/backend.ts::apiBase()` is the one function
  the REST client (`lib/api.ts`), the live socket / live cloud
  (`live/wsUrl.ts::currentLive*`) and the PLY loader read the base URL
  through: the build default `VITE_API_BASE_URL` or an override kept in
  `localStorage["visionforge.apiBase"]` (every access in try/catch). The
  **Backend** field (`components/BackendField.tsx`, on the Live header and
  the sessions sidebar) sets it, shows `using <url>`, and probes
  `GET /sessions` with a 5 s timeout: `connection: ok (N sessions, M ms)` /
  `failed: <reason>` + Retry. Emulator (`10.0.2.2`) ↔ phone (PC LAN IP)
  without a rebuild; `.env.production` now defaults to
  `http://192.168.1.37:8000` (the PC's Wi-Fi IPv4), present twice in `dist/`.
  The session list and the selected session reload when the base changes.
* **(a)** `lib/sessionLoad.ts::loadSessionView`: twin first, then
  measurements; `ApiError` (new, carries the status) 404 on measurements
  keeps the twin and yields a notice — `noGeometryNotice` says
  *"no geometry: live tracking failed (never initialised)"* when
  `stage_status.live_tracking == failed`, otherwise names the failed /
  running stages. The session view renders that, the stage list, the live
  frame/keyframe/map counts and the provenance footer in place of the viewer.
* **(b)** `generate_synthetic_clip.py --fourcc avc1`: OpenCV's wheel has no
  H.264 encoder in its FFmpeg (it wants Cisco's openh264 DLL), but Windows
  Media Foundation does, so H.264 fourccs try `CAP_MSMF` first — on this PC
  that writes real H.264 (`Codec on disk: h264`;
  `data/input/synthetic_box_room_30fps_h264.mp4`, 360 frames, 20 MB). When no
  backend can, the script exits with the DLL / `ffmpeg -c:v libx264`
  alternatives; it also re-reads the output and fails on a short frame count
  instead of leaving an empty file. The WebM clip needs a VP8-capable WebView.
* **(c)** `@capacitor/app` **8.1.2** (pinned) `backButton` listener in
  `lib/backButton.ts` (`resolveBack`, pure, tested): a running live session →
  Stop (its `finished` reply opens the session view); the Live screen or a
  session → the sessions list; the sessions list → `App.exitApp()`. No-op on
  the web. `cap sync` registered the plugin (`capacitor.settings.gradle`,
  `capacitor.build.gradle`).
* **Tests:** vitest 35 → **53** (`backend.test.ts` 8, `sessionLoad.test.ts`
  5, `backButton.test.ts` 3, `wsUrl.test.ts` +1 for the override reaching
  REST and the socket through the one function); backend 176 unchanged;
  `npm run build` clean.

**Phone untested** — the stage 2 procedure and what to paste back are in
`docs/live_android_checklist.md` §3–4.

## 7. Real footage

Until §11 (2026-10-16) **nothing above said anything about physical-camera
video**: §1–§10 are the rendered box room (the 30 fps clip in §6 is still the
rendered room, only resampled). §11 is the first real run — one phone, one
room, mostly rotation — and it already showed a wrong focal guess and a
keyframe policy tuned on synthetic frames; motion blur, rolling shutter,
textureless walls and real lens distortion remain unmeasured until a
recorded (replayable) walk-through exists.
`docs/real_video_checklist.md` applies to the live path too, plus: watch
`lost_episodes` and `segments` (a real walk-through will almost certainly lose
tracking at least once), and whether initialisation happens at all when the
operator starts by panning.

## 11. First real-phone run (Phase 3 step 6, 2026-10-16)

Session `live-1792149775026`: iQOO Neo 7, Wi-Fi to the PC at 192.168.1.37,
camera source, portrait. **The first physical-camera footage this project
has ever processed.** The run's `tracking_report.json`, `run_status.json`,
`p2/room_model.json` and `p2/statistics.json` are kept verbatim in
`docs/results/live-1792149775026/` (not the PLY; frames were not recorded —
recording did not exist yet, see below).

### Numbers (verbatim from the report)

| | |
|---|---|
| frames | **219** (received 220, `dropped` 1, 19 twin updates) |
| states | **131 TRACKING / 65 INITIALIZING / 23 LOST** (tracking fraction 0.598) |
| LOST episodes | **6** (68–69, 73–76, 116–117, 119–124, 128–129, 166–172) |
| segments | **7**; exported **segment 5 = frames 128–165 only** (23 keyframes, 986 points); the others 3 / 4 / 16 / 2 / 4 / 5 keyframes |
| keyframes (seg. 5) | **23 — almost every frame: 128, 130, 131, 132, 133, 134, 135, 136, 137, 141, 148, …** |
| map | **986** points, mean reprojection RMS **1.14 px** |
| intrinsics | **GUESS fx = fy = 1138** at **640 × 1138 portrait** (source `guess`, `max(w, h)`) |
| timing | **null** (the session did not measure it) |
| P2 | **7 planes {floor 1, wall 3, unknown 3}**, `up_source` **`architectural_planes+largest_plane_legacy`**, up confidence 0.56; room 12.1 × 11.5 × 10.4 (arbitrary scale, so meaningless as metres) |

### Motion caveat — read before drawing conclusions

The operator mostly **rotated** the phone and walked very little. The
tracker's initialisation gate needs translation (parallax), and a rotation
produces none, so the 65 INITIALIZING frames, the 6 LOST episodes and the
short segments are largely **the parallax gate behaving correctly**, not a
tracker defect. **Do not retune the LOST / initialisation thresholds from
this run.** The next run follows `docs/live_android_checklist.md` §3 (slow
sideways walk, 2–3 m) with **Record frames** ticked, so tuning can happen on
replayable footage instead.

### Findings (the real ones)

1. **Intrinsics were a guess.** `fx = max(w, h) = 1138` at 640 × 1138 is a
   ~53° field of view along the long side; phone main cameras are wider
   (≈ 60–75°), so the focal was over-estimated. Stopgap now in place:
   the Live screen sends `CameraIntrinsics.phone_default` = **0.8 × the
   longer side** (~64°, source `phone_default`), computed for the size it
   sends and scaled by the server like any intrinsics. Real fix:
   `visionforge calibrate --video <clip> --output <json>` (P0 + P1 / COLMAP
   on a 20–30 s clip from the same phone in the same orientation, slow
   sideways walk) → the Live screen's **Intrinsics** field → sent as
   `intrinsics_from_cameras` + `intrinsics_size`, rescaled server-side to
   the received frames (tested). Both are documented in §9 and the checklist.
2. **Keyframe on (almost) every frame.** 23 keyframes in 38 frames of segment
   5: the `tracked_fraction < 0.6` gate fires every frame once the map is
   small and features churn. Live sessions now use **`keyframe_min_gap = 3`**
   (`LiveSession` default; the CLI keeps 1), and every keyframe records which
   condition fired and with what values in `tracking_report.keyframe_reasons`
   so the next run says *why*. Nothing else was retuned — that is what the
   recording is for.
3. **`timing: null`.** The session never measured itself. It now records
   per-frame process time (whole feed and tracker only), inter-arrival
   interval and delivered fps — mean / p50 / p95 / max, frames over 100 ms —
   into `tracking_report.timing` and `run_status.live.timing`, never null.

### Flagged for P2's owner: camera-gravity disagreement

`p2/statistics.json` → `geometry.up_sources`: the **camera_gravity** source
(the keyframes' down direction, 23 samples, coherence 0.998, confidence
**0.999**) points **20.2° away** from the final up axis, which P2 took from
`architectural_planes` + `largest_plane_legacy` (confidence 0.82 / 0.58,
final 0.56) — `agrees_with_final: false` **although the phone was held
upright** the whole time. The phone's gravity is the one source here that
is not a guess from a 986-point cloud with 3 `unknown` planes; the
arbitration preferred the plane heuristic. Not changed here (P2's owner);
recorded so the next run can be compared.

### What changed for the next run

Recording (`{"record": true}` → `outputs/<id>/frames/` + `frames.jsonl` +
`configure.json`, §9), offline replay (`visionforge live --frames-dir`,
`scripts/replay_live.py --frames-dir`), timing, `phone_default` intrinsics,
`visionforge calibrate`, `keyframe_min_gap = 3` for live sessions,
`keyframe_reasons`. Tests: backend 176 → 190, vitest 53 → 61.
