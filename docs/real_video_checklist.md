# Checklist: once a real (physical-camera) `room.mp4` has been processed

Everything in this repo — Task A through Task H — has only ever been
exercised against the synthetic rendered clip
(`data/input/synthetic_box_room.mp4`, see §16 in `PROJECT_STATE.md`) or
hand-built synthetic fixtures in the test suite. Real indoor smartphone
footage will differ in every way that matters: motion blur, rolling
shutter, textureless walls, reflective surfaces, inconsistent lighting,
genuinely non-Manhattan geometry, and camera intrinsics that don't match
the two-view stage's `focal = max(w, h)` heuristic. This is the Spatial
Intelligence + Digital Twin layer's own checklist for what to re-verify
once the CV side (P0-P1, owned separately — see `PROJECT_STATE.md` §12)
has produced a real reconstruction. None of this requires code changes by
default; it's what to *look at* first, and where to go digging if the
output looks wrong.

## 1. Plane counts and classification

- How many planes did P2 actually find, and how do they classify
  (`{floor, ceiling, wall, unknown}`)? A real room usually has 4+ walls, not
  the demo clip's 2 (no ceiling was ever detected in the synthetic clip —
  see below). If real footage produces far fewer planes than expected
  (e.g. only 1-2), the walls were probably textureless or the camera path
  didn't give RANSAC enough distinct, well-supported surfaces.
- Check `room_model.json`'s `planes[].support` (inlier count) per plane.
  A plane with very low support relative to the others is a candidate for
  being spurious (noise fit to a small, coincidentally-planar cluster of
  points) rather than a real surface — this is a judgment call, not an
  automatic filter (Task A/B were told not to fabricate a
  "confidence" field that doesn't exist).
- **If planes fragment** (the same physical wall split into 2+ RANSAC
  segments, the original bug the split-floor fix — §17 — was written for):
  check `merge_coplanar_planes`'s two thresholds in
  `geometry/plane_fitting.py`: `normal_dot_threshold` (default 0.98) and
  `offset_factor` (default 2.0, i.e. merge tolerance = `2 * RANSAC
  distance_threshold`). Real noisy point clouds may need a looser
  `normal_dot_threshold` (e.g. 0.95) or a larger `offset_factor` if a real
  wall's RANSAC segments disagree more than the synthetic clip's did.
  Don't just widen these blindly — check the merge is still leaving
  genuinely distinct, perpendicular surfaces (e.g. two different walls of a
  rectangular room) unmerged.

## 2. Scale-relative thresholds

- `geometry/pipeline.py`'s `--voxel-size`/`--plane-distance-threshold`
  default to 0.5%/1% of the raw cloud's bounding-box diagonal. Print the
  resolved values (`statistics.json`'s `resolved_thresholds`, or the
  pipeline's own stdout) for the real run and sanity-check them against the
  room's real physical size if you have any independent estimate (even a
  rough "this room is about 4m x 5m" from memory) — monocular SfM scale is
  arbitrary, so these numbers being "weird" in isolation is expected, but
  wildly inconsistent with the room's real proportions would suggest a
  scale problem upstream in P1, not this layer.
- `spatial/scene_graph.py`'s `ADJACENCY_DISTANCE_FRACTION` (0.05) and
  `ABOVE_BELOW_EPSILON_FRACTION` (0.02) are fractions of a *different* scale
  reference (the room's own boundary-derived bounding-box diagonal,
  computed in `scene_graph.py` itself, not P2's). If real adjacent
  surfaces (a wall genuinely touching the floor) aren't getting an
  `adjacent_to` edge, check the actual `polygon_min_distance` value against
  this threshold before loosening it — a real gap this large usually means
  the two RANSAC segments genuinely don't overlap in that region (occlusion,
  missing coverage), not that the threshold is wrong.

## 3. "Not measurable" states rendering correctly in the UI

The synthetic clip's `room.height` happens to always come back *measurable*
(via the `wall_extent_estimate` fallback, since it has 2 walls). **A real
room with only 1 wall detected, or a floor with no walls or ceiling at all,
will genuinely hit the `None` case** that Task C's tests covered but the
real pipeline never has. Check, on the real session:

- `GET /sessions/{id}/measurements` (or the frontend's Measurements panel)
  — does a `None` field render as "not measurable" (the intended, explicit
  state), and never silently as `0`? This was tested synthetically
  (`test_room_height_none_without_ceiling_or_walls`,
  `MeasurementsPanel.tsx`'s `not-measurable` row) but never against a real
  `None` produced by an actual under-detected room.
- If `height_method` comes back `"wall_extent_estimate"` on a real room,
  remember it's a real but weaker estimate (see §21) — the true ceiling
  height could differ substantially if the detected wall segment doesn't
  span the full floor-to-ceiling range.

## 4. Gravity prior / `up_axis` source

`classify_planes` (in `geometry/plane_fitting.py`) picks the **largest**
detected plane as the floor candidate and derives `up_axis` from its
normal — there is no independent gravity/IMU prior anywhere in this
pipeline (classical CV only, no sensor fusion was ever implemented). On the
synthetic clip this works because the floor genuinely is the largest,
cleanly-detected plane. **On a real room, verify the largest plane
actually IS the floor** before trusting `up_axis`/the room frame at all:
if a real room has a much larger, more textured wall than its floor (e.g.
the floor is mostly hidden behind furniture, or a wall has far more SIFT
coverage), `classify_planes` will get the up-direction wrong, and
everything downstream (room-frame transform, camera "above floor" checks,
the frontend's Y-up rendering) will be tilted or upside down relative to
true gravity, honestly-but-wrongly. There is no automated flag for this;
eyeball the point cloud / rendered planes and check the floor is actually
flat-and-horizontal-looking in the frontend viewer, the way §24's
synthetic-clip verification did.

## 5. `within_boundary` flags on real camera-to-surface distances

`SpatialQueryEngine.distance_from_camera_to_surface` (and
`get_nearest_wall_to_camera`) flag whether the foot of the perpendicular
actually lands inside that surface's real detected boundary polygon. On
the synthetic clip, several of these came back `False` (see §20's
real-data notes) because the detected wall boundaries didn't cover the
camera's full path. On a real room with more complete wall coverage, check
whether `within_boundary` is `True` more consistently — if it's still
mostly `False`, that's a sign the walls' *boundary polygons* (not just
their infinite planes) are under-covering the real wall extent, which
traces back to RANSAC inlier coverage / the convex hull in
`room_model.py`'s `_plane_boundary`, not a bug in the flag itself.

## 6. Frustum count vs. frame count

`Viewer3D.tsx` renders one camera frustum per `camera` node in the scene
graph, which comes from however many cameras COLMAP's incremental SfM
actually registered — **not** the number of frames extracted by P0. On the
synthetic clip these matched (24 frames in, 24 cameras registered) because
the clip was easy (clean synthetic textures, deliberate parallax). A real
video is very likely to have **fewer registered cameras than extracted
frames** (frames COLMAP couldn't register: motion blur, insufficient
texture, a bad match). Check `p1/reconstruction/statistics.json`'s
`reconstructed_cameras` against `p0/metadata.json`'s `extracted_frames` —
if the gap is large, that's expected and informative (which parts of the
walk-through failed to register), not a viewer bug; the frustum count is
supposed to reflect it honestly.

## 7. General sanity pass

- Run `pytest tests/` and `cd frontend && npm run build && npm run test`
  after processing the real video through the pipeline — none of this
  layer's code changes for a real video, but it's worth reconfirming
  nothing regressed in whatever session does this work.
- Re-read `docs/PROJECT_STATE.md` §9 (Known Problems) before drawing
  conclusions from a single real run — scale ambiguity and the
  Manhattan-world assumption are pre-existing, known limitations of P1/P2
  that this layer inherits, not something a real video will "reveal" as new.
