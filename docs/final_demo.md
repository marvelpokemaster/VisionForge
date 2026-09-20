# Final Demonstration Guide

VisionForge provides a unified CLI for both Offline and Live demonstrations.

## DEMO A — Offline Construction
This mode runs the complete batch pipeline from video ingestion to digital twin visualization.

```bash
visionforge reconstruct --video path/to/room.mp4
```

**What it does:**
1. Extracts keyframes.
2. Runs Incremental SfM to produce a 3D sparse cloud.
3. Detects architectural planes and extracts room dimensions.
4. Generates a semantic Scene Graph.
5. Runs spatial queries on the room geometry.
6. Launches an interactive 3D Digital Twin Viewer showing the colorized architectural planes.

## DEMO B — Live Camera Mode
This mode demonstrates the "Iron Man" capability: processing a live video stream, tracking the camera, and growing the map in real time using pure classical visual odometry.

```bash
visionforge live
```

**What it does:**
1. Opens the default webcam.
2. Tracks points using the KLT optical flow algorithm.
3. Recovers camera pose via Essential Matrix decomposition.
4. Triangulates 3D points in real time.
5. Displays a 2D HUD (showing FPS and Mapped Points) alongside an Open3D 3D Digital Twin tracking the trajectory and sparse map.

*Note: Live mode is a visual odometry demonstration. It has scale drift and does not perform global loop closure (unlike the offline SfM pipeline).*
