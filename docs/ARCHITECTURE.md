# VisionForge — System Architecture

## 1. System Overview & Component Topology
VisionForge is a client-server classical computer vision system that transforms video input into a metric, interactive 3D digital twin of an indoor architectural room.

```
[ Android Phone / Browser ]
         │
         │ (HTTP / WebSocket)
         ▼
[ FastAPI / Uvicorn Server ]
   ├── REST API (/sessions, /cloud, /query)
   └── WebSocket Live Session (/live/{id})
         │
         ▼
[ VisionForge Core Engine ]
   ├── Ingestion (P0: OpenCV / FFmpeg)
   ├── Offline SfM (P1: SIFT + PyCOLMAP)
   ├── Online Live Tracker (Phase 3: KLT + PnP + Keyframes)
   ├── 3D Room Geometry (P2: Incremental & Batch Planar RANSAC)
   ├── Spatial Scene Graph (P3: Adjacency, Alignment, Bounds)
   └── Digital Twin Data Layer (P4: twin.json + Provenance)
         │
         ▼
[ Persistence Layer ]
   ├── Local Filesystem (outputs/<session>/)
   └── Supabase PostgreSQL (opt-in)
```

---

## 2. Subsystem Descriptions

### 2.1 Ingestion Pipeline (`visionforge.video`)
* **Purpose:** Ingests video (`.mp4`), extracts discrete frames at a target sampling rate, computes sharpness using the variance of the Laplacian, and rejects motion-blurred frames.
* **Outputs:** Extracted frames in `p0/frames/`, `contact_sheet.jpg`, and `p0/metadata.json`.

### 2.2 Classical Reconstruction Engine (`visionforge.reconstruction`)
* **Offline Pipeline:**
  * Two-view initialization using SIFT feature extraction and Lowe's ratio test (0.75).
  * Robust geometric verification via Essential Matrix estimation (`findEssentialMat` with RANSAC) to recover initial relative pose $(R, t)$.
  * Full incremental Structure-from-Motion via PyCOLMAP to register remaining cameras and triangulate 3D points.
  * Outputs: `p1/reconstruction/sparse_cloud.ply` and `p1/reconstruction/cameras.json`.

### 2.3 Real-Time Live Monocular Tracker (`visionforge.live`)
* **Online Pipeline:**
  * Fast feature detection (FAST / GoodFeaturesToTrack) and Pyramidal Lucas-Kanade Optical Flow (KLT) tracking.
  * Two-keyframe parallax-gated initialization (`findEssentialMat` with `USAC_ACCURATE`).
  * Per-frame camera pose estimation using Perspective-n-Point (`solvePnPRansac`) against known 3D map points.
  * Keyframe decision gate based on feature tracking ratio (< 0.6) and optical flow parallax (> 30 px).
  * State Machine: `INITIALIZING` ➔ `TRACKING` ➔ `LOST` (with automatic re-initialization into new segments).
  * Offline replay tooling: `scripts/replay_live.py` and `visionforge.cli live --frames-dir`.

### 2.4 Room Geometry Engine (`visionforge.geometry`)
* **Batch (`pipeline.py` & `api.py`):**
  * Voxel downsampling (default 0.5% of cloud bounding box diagonal).
  * Statistical outlier removal via DBSCAN clustering.
  * Dominant plane extraction via iterative planar RANSAC.
  * Coplanar segment merging for near-duplicate planes ($\Delta d \le 2\times \text{thresh}$, $|n_1 \cdot n_2| \ge 0.98$).
  * Architectural classification: Identifies the global UP vector by fusing camera gravity, Manhattan pair alignments, and architectural support heuristics. Classifies planes into `floor`, `ceiling`, `wall`, or `unknown`.
  * Computes 2D convex hull boundaries, true surface area, and plane-plane intersection line segments.
* **Incremental (`incremental.py`):**
  * `IncrementalRoomModel` continuously refits geometry on a growing point cloud during live sessions.
  * Gated by point count growth ($\ge 100$ new points) and minimum time intervals ($\ge 1.0$ s).

### 2.5 Spatial Scene Graph & Query Engine (`visionforge.spatial`)
* **Scene Graph (`scene_graph.py`):**
  * Hierarchical graph: `Room` root node containing surface nodes (`floor`, `walls`, `ceiling`) and `camera` trajectory nodes.
  * Typed geometric edges with supporting numerical evidence: `parallel_to` (angle), `perpendicular_to` (angle), `adjacent_to` (boundary distance), `intersects` (3D line segment), `above` / `below` (height delta), and `inside` (point-in-polygon ray-casting test).
* **Query Engine (`queries.py`):**
  * Deterministic spatial evaluation answering questions such as room height, floor area, largest wall, nearest wall to camera, and rectangular clearances. Unsupported questions return explicit fallback notices.

### 2.6 Digital Twin & Persistence (`visionforge.twin` & `visionforge.persistence`)
* **Digital Twin (`digital_twin.py`):**
  * Bundles `room_model.json`, `cameras.json`, `scene_graph.json`, and an execution provenance block into `twin.json`.
  * The sparse point cloud (`sparse_cloud.ply`) is referenced as a relative path and is never embedded into JSON.
* **Persistence:**
  * `LocalJsonBackend`: Zero-config local persistence under `outputs/<session_id>/persistence/`.
  * `SupabaseBackend`: PostgreSQL storage mapping sessions, versioned models, and queryable measurement rows.

---

## 3. Coordinate Systems & Transforms

VisionForge uses three distinct 3D coordinate frames:

1. **Camera Frame:**
   * Standard OpenCV convention: $+X$ points right, $+Y$ points down, $+Z$ points forward along the optical axis.
2. **Reconstruction Frame (World Frame):**
   * The arbitrary 3D coordinate space produced by PyCOLMAP or the live PnP tracker. Scale is unanchored (arbitrary monocular scale).
3. **Room Frame:**
   * Derived by the geometry pipeline after determining the primary architectural UP vector $\hat{u}$ and floor plane:
     * Ground plane: The floor surface sits at $Y_{\text{room}} = 0$.
     * $+Y_{\text{room}}$ points vertically upward toward the ceiling.
     * $X_{\text{room}}$ and $Z_{\text{room}}$ align with the principal horizontal wall directions.
   * All boundary polygons, camera trajectory coordinates, and clearance tests are transformed into this room frame for human-interpretable rendering and measurement.

---

## 4. Scale Handling & Ambiguity

* **Monocular Limitation:** Pure monocular vision cannot observe absolute metric scale without external priors.
* **Current Behavior:** Default outputs are in unscaled reconstruction units.
* **Calibration Pathways:**
  1. *Manual Reference Distance:* Passing `--reference-distance <meters>` and `--reference-reconstruction-distance <units>` scales all measurements by $s = d_{\text{metric}} / d_{\text{rec}}$.
  2. *Camera Calibration:* `visionforge calibrate --video <clip.mp4>` computes intrinsic parameters ($f_x, f_y, c_x, c_y, k_1$).
  3. *Phase 4 Target:* Sensor fusion with mobile accelerometer/gravity and interactive two-point floor distance calibration.

---

## 5. Network & Streaming Protocols

### 5.1 REST Endpoints (FastAPI)
* `GET /sessions`: List all local and persisted sessions.
* `GET /sessions/{id}/twin`: Retrieve the full digital twin JSON.
* `GET /sessions/{id}/cloud`: Stream the binary/ASCII `sparse_cloud.ply`.
* `GET /sessions/{id}/room_model`: Retrieve geometric planes and room dimensions.
* `GET /sessions/{id}/scene_graph`: Retrieve spatial relationships.
* `POST /sessions/{id}/query`: Execute natural language or method queries.

### 5.2 Live WebSocket Protocol (`/live/{id}`)
* **Client to Server:**
  * Handshake: `{"width": 640, "height": 480, "intrinsics": {...}, "record": true}`
  * Frame Pump: Binary JPEG bytes or `{"image": "<base64>", "timestamp": 123456.78}`
  * Termination: `{"cmd": "finish"}`
* **Server to Client:**
  * Status: `{"state": "TRACKING", "map_size": 842, "pose": {...}, "fps": 28.5, "twin_update": {...}}`
  * Completion: `{"finished": true, "session_id": "live-...", "run_dir": "..."}`

---

## 6. Frontend & Mobile Architecture

* **Frontend Stack:** Single-page React 19 application built with Vite and Three.js.
  * `Viewer3D.tsx`: Interactive WebGL viewer rendering the PLY point cloud, colored semi-transparent planes (Floor: green, Walls: red, Ceiling: blue), camera frustums, and trajectory lines.
  * `LiveScreen.tsx`: Interface handling mobile camera streaming, WebSocket status, state banners, and live point cloud updates.
* **Mobile Stack:** Capacitor 8 native container for Android (`frontend/android/`).
  * Intercepts Android hardware back button events (`@capacitor/app`).
  * Manages native camera permissions (`android.permission.CAMERA`).
  * Connects over LAN Wi-Fi to the Python backend host via configurable runtime URL.
