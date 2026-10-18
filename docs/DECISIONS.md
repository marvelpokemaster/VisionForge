# VisionForge — Architecture Decision Records (ADR)

## ADR-001: Pure Classical Computer Vision (Zero Neural Networks / No ML)
* **Date:** 2026-09-20
* **Status:** Accepted (Non-negotiable project rule)
* **Context:** Modern 3D reconstruction often reaches for deep learning (SuperPoint, LoFTR, DINO, neural SLAM, learned depth). We need a system that operates deterministically on consumer devices without requiring multi-gigabyte models, GPUs, or opaque failure modes.
* **Decision:** Exclusively use classical, geometrically grounded computer vision algorithms: SIFT, ORB, KLT optical flow, RANSAC, Essential Matrix decomposition, PnP, and planar RANSAC.
* **Consequences:**
  * Requires explicit handling of low-texture surfaces and lighting variation.
  * Ensures complete mathematical transparency, predictable runtime complexity, and zero dependence on cloud AI APIs or proprietary model weights.

---

## ADR-002: Client-Server Architecture for Live Tracking (Phone Camera Streaming to PC)
* **Date:** 2026-10-15
* **Status:** Accepted
* **Context:** Executing real-time dense or even semi-dense monocular SLAM with OpenCV and Open3D in pure JavaScript on a mobile phone webview causes severe thermal throttling and battery drain. Native Android C++ NDK bindings with Open3D would require a heavy custom toolchain.
* **Decision:** Implement a client-server architecture. The phone (Capacitor Android app) captures frames from the camera and streams downscaled JPEG images over a WebSocket (`/live/{id}`) to a local PC backend. The PC processes KLT/PnP tracking and incremental geometry, streaming state updates and sparse point clouds back to the phone for Three.js rendering.
* **Consequences:**
  * Enables fast development, rich Python debugging, and full use of Open3D/PyCOLMAP.
  * Requires the mobile device and PC to be connected on the same local network (Wi-Fi).
  * Phase 4 will explore standalone on-device execution once algorithms are fully optimized.

---

## ADR-003: Monocular Scale Handling & Explicit Metric Provenance
* **Date:** 2026-09-21
* **Status:** Accepted
* **Context:** Monocular visual reconstruction suffers from fundamental scale ambiguity. A model can be internally consistent but arbitrarily scaled.
* **Decision:** Never invent, hallucinate, or guess real-world metric units. Every measurement in `room_model.json` and `twin.json` must carry an explicit `scale.metric_available: boolean` flag and specify the `*_method` used (e.g. `floor_to_ceiling` vs `wall_extent`). Unscaled values are clearly marked as uncalibrated reconstruction units.
* **Consequences:**
  * Downstream consumers (and the frontend UI) are warned when data is non-metric.
  * Real-world furniture placement requires an explicit calibration step (e.g. user entering a known reference distance or sensor fusion).

---

## ADR-004: Incremental Room Geometry Fitting with Time & Growth Throttling
* **Date:** 2026-10-16
* **Status:** Accepted
* **Context:** In a live tracking session, running 3D DBSCAN and multi-plane RANSAC on every incoming video frame (30 fps) is computationally prohibitive and causes visual flickering of planes.
* **Decision:** Implement `IncrementalRoomModel` with double gating:
  1. Minimum point growth: Point cloud must grow by at least $\Delta N \ge 100$ points.
  2. Minimum time interval: At least $\Delta t \ge 1.0$ s must pass since the last fit.
* **Consequences:**
  * Keeps server CPU usage low, allowing tracking (PnP) to maintain high frame rates.
  * Delivers smooth, stable twin updates to the client without plane jitter.

---

## ADR-005: Dual-Backend Persistence (Local JSON Default, Supabase Opt-in)
* **Date:** 2026-09-21
* **Status:** Accepted
* **Context:** Developers need to run VisionForge completely offline without cloud credentials. Simultaneously, multi-user deployments require database persistence for session management and queryable measurements.
* **Decision:** Provide an abstract `PersistenceBackend` with two implementations:
  1. `LocalJsonBackend`: Default zero-config storage in `outputs/<session_id>/persistence/`.
  2. `SupabaseBackend`: Activated only when `SUPABASE_URL` and `SUPABASE_KEY` environment variables are provided.
* **Consequences:**
  * Zero setup friction for local developers.
  * Large 3D point cloud files (`sparse_cloud.ply`) remain stored as file references rather than bloated database columns.

---

## ADR-006: In-Memory Geometry API (`build_room_model`) with CLI Wrapper
* **Date:** 2026-10-16
* **Status:** Accepted
* **Context:** Originally, the geometry pipeline (`pipeline.py`) read from disk and wrote files to disk. Live tracking required running geometry directly on in-memory NumPy arrays without disk round-trips.
* **Decision:** Refactor the core geometry logic into an in-memory function `build_room_model(points, cameras, options, seed)` returning a `RoomModelResult` dataclass. Keep `pipeline.main()` as a thin CLI wrapper that parses arguments, calls `build_room_model`, and writes output files.
* **Consequences:**
  * Clean separation of concerns between computational geometry and filesystem I/O.
  * Enables both fast batch CLI execution and real-time live streaming updates.

---

## ADR-007: Up-Axis Fusion Arbitration (Gravity Prior vs Architectural Planar Alignment)
* **Date:** 2026-10-17
* **Status:** Proposed / Under Implementation
* **Context:** Determining the true vertical "UP" vector in a room relies on multiple sources: camera gravity (from upright camera poses), Manhattan plane pairs, and architectural heuristics (floor vs ceiling support). On physical mobile scans, plane heuristics with low confidence (0.56) occasionally outvoted camera gravity (confidence 0.999), causing the room to orient sideways.
* **Decision:** When camera gravity is available with high confidence ($\ge 0.95$) from an upright device pose, it must act as a hard veto/override over unverified planar heuristics.
* **Consequences:**
  * Guarantees correct floor/wall classification when the user holds their phone upright.
  * Eliminates inverted or sideways room coordinates.
