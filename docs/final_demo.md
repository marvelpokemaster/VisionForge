# Final demo: video → digital twin → API → frontend

This is the actual end-to-end chain, run for real on a completely fresh
`git clone` (not this repository's working copy) as part of Task H's
verification — see `docs/PROJECT_STATE.md` §26 for what that run actually
printed. `scripts/run_demo.sh` (bash) and `scripts/run_demo.ps1`
(PowerShell) automate every step below.

**Read this first:** the input video is a **synthetic rendered clip**
(`scripts/generate_synthetic_clip.py`), not physical-camera footage. See
"Known limitations" at the bottom before drawing any conclusion from this
demo about real-world robustness.

## Run it yourself

```powershell
# PowerShell (Windows)
.\scripts\run_demo.ps1
```

```bash
# bash (git-bash / WSL / Linux / macOS)
bash scripts/run_demo.sh
```

Either script, from a completely clean checkout with nothing pre-installed:
creates a `.venv`, `pip install -r requirements.txt`s into it, generates
`data/input/synthetic_box_room.mp4` if it doesn't exist, runs
`visionforge reconstruct --video ... --output outputs/demo --input-type
synthetic --no-viewer --persist`, starts the API on `:8000`, then
`npm ci && npm run build` and starts the frontend dev server on `:5173`.

## Step by step: what a reviewer will actually see

### 1. Generating the synthetic clip

```
python scripts/generate_synthetic_clip.py --output data/input/synthetic_box_room.mp4
```

Prints `Wrote 24 frames to ... at 2.0 fps` and the file size (~500KB). This
is a genuinely rendered video — a textured 6-face box room, perspective-
warped with real homographies from 24 camera poses that dolly sideways
while tilting from floor-level to ceiling-level — not a placeholder or a
fabricated point cloud. See `docs/PROJECT_STATE.md` §16 for how and why it
was built this way (no ML, no GPU 3D renderer — Open3D's `OffscreenRenderer`
produced all-black frames in the original build environment).

### 2. The offline pipeline

```
python -m visionforge.cli reconstruct --video data/input/synthetic_box_room.mp4 \
    --output outputs/demo --input-type synthetic --no-viewer --persist
```

Six stages print to the console as they run (`[1/6]` through `[6/6]`):
frame extraction, classical SfM reconstruction (SIFT → FLANN → PyCOLMAP
incremental mapping — real feature matching and triangulation, ~1-2
minutes), RANSAC room geometry, scene graph generation, a spatial-query
demo printout, and building+persisting `twin.json`. A reviewer will see
real numbers throughout — keypoint/match counts, registered camera count,
triangulated point count, detected plane count and classification, room
dimensions with their `method` and honest non-metric units — never a
placeholder.

### 3. The API

```
uvicorn visionforge.api.app:app --host 127.0.0.1 --port 8000
```

`GET /sessions`, `GET /sessions/demo/twin`, and `POST
/sessions/demo/query` all return real data read from `outputs/demo/`. Actual
`curl` output from the clean-checkout run (see `docs/PROJECT_STATE.md` §26
for the full pipeline log this run produced):

```
$ curl -s http://localhost:8000/sessions
[{"id":"demo","run_dir":"outputs\\demo","provenance":{"run_dir":"C:\\vftest\\outputs\\demo","source_files":{"room_model":"p2/room_model.json","cameras":"p1/reconstruction/cameras.json","scene_graph":"scene_graph.json","sparse_cloud":"p1/reconstruction/sparse_cloud.ply"},"stage_status":{"p0_frame_extraction":"success","p1_reconstruction":"success","p2_room_geometry":"success","scene_graph":"success","twin":"success"},"input_type":"synthetic","scale":{"metric_available":false,"scale_factor":1.0},"measurement_methods":{"length_method":"floor_extent","width_method":"floor_extent","height_method":"wall_extent_estimate","floor_area_method":"floor_extent"}}}]

$ curl -s http://localhost:8000/sessions/demo/twin
# keys: provenance, room_model, cameras, scene_graph, sparse_cloud_path
# room_model.room: length=20.597, width=8.535, height=6.544 (method: wall_extent_estimate), floor_area=175.80
# num planes: 3
# sparse_cloud_path: p1/reconstruction/sparse_cloud.ply

$ curl -s -X POST http://localhost:8000/sessions/demo/query \
    -H "Content-Type: application/json" -d '{"question": "Which wall is largest?"}'
{"question_type":"largest_wall","supported":true,"answer":{"wall_id":"plane_002","area":{"value":37.58388744369306,"metric":false,"units":"reconstruction_units"}}}

$ curl -s -X POST http://localhost:8000/sessions/demo/query \
    -H "Content-Type: application/json" -d '{"question": "What color is the floor?"}'
{"question_type":null,"supported":false,"answer":null,"message":"Unsupported question.","supported_question_types":["What is the room height?","Which wall is largest?","Which walls are parallel?","How far is the camera from the nearest wall?"]}
```

The last call is a deliberately unsupported question — it demonstrates the
API telling the truth about what it can't answer (`supported: false`, a
listed set of what it *can* answer) rather than guessing.

### 4. The frontend

```
cd frontend && npm ci && npm run build && npm run dev
```

Opening `http://localhost:5173` shows: a session list with `demo` and a
**SYNTHETIC** badge with per-stage status checkmarks; a measurements panel
(length/width/height/floor area, each with its value, units, and
`method`); a query box; and the 3D viewer. In the viewer (confirmed by
actually driving a real Chrome tab in Task F, §24 — not assumed): the
floor renders as a flat polygon with the walls rising vertically from its
edges (the room-frame transform is correct — COLMAP's frame is arbitrary/
often not Y-up; three.js is Y-up), the point cloud sits on the floor,
clicking a plane highlights it gold and populates the inspect panel with
its real relations, camera frusta with real, distinct orientations are
strung along an orange trajectory line, and a "synthetic input — not
physical-camera footage" banner is visible the whole time.

## Known limitations

- **Synthetic input only.** Every verification in this repository — every
  task, every log entry, this demo — has run against the rendered
  synthetic clip. **No physical-camera video has ever been processed.**
  See `docs/PROJECT_STATE.md` §12/§15 and `docs/real_video_checklist.md`
  for what to re-check once one has been.
- **No ceiling in the demo clip.** The synthetic room's camera path
  registers a floor and 2 walls; no plane classifies as `ceiling` in this
  particular run. `room.height` therefore comes from the `wall_extent_
  estimate` fallback (the highest wall point above the floor), not a
  measured floor-to-ceiling distance — a real but weaker method, honestly
  labeled via `height_method` (§21). A room where P2 detects an actual
  ceiling plane would use the stronger `floor_to_ceiling` method instead.
- **Non-metric units.** No reference distance was supplied to this run, so
  `scale.metric_available` is `false` and every length/area is in
  arbitrary `reconstruction_units`, not meters. This is monocular SfM's
  inherent scale ambiguity (§9), not a bug — the honest alternative would
  be to fabricate a meters conversion, which this project explicitly never
  does.
- **Height from a wall-extent estimate, not a direct measurement** (see
  above) — repeated here because it's the single most likely number in
  this demo to be misread as more precise than it is.
- **Clone into a short path on Windows.** `pycolmap`'s compiled `_core`
  extension failed to import with `DLL load failed ... filename or
  extension is too long` when this repo was cloned into a deeply nested
  temp path during Task H's clean-checkout verification — a Windows
  `MAX_PATH` limitation, not a code bug. Re-cloning to a short path (e.g.
  `C:\vftest`) fixed it immediately. If you hit this, move the clone
  closer to a drive root rather than debugging the pipeline.
