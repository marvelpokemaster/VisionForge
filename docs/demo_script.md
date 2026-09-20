# Faculty Demonstration Script

This script outlines exactly how to demonstrate VisionForge to faculty to highlight its classical computer vision foundation and functional digital twin capabilities.

## Introduction (2 mins)
* "VisionForge is an indoor digital twin system built entirely on classical computer vision. No deep learning, no YOLO, no faked geometry. Everything you see is derived from geometric principles."

## Phase 1: Offline Pipeline (3 mins)
* *Action*: Run `python -m visionforge.cli reconstruct --video room.mp4` (or mock equivalent).
* *Talking points*:
  * "The system extracts SIFT features, sequentially matches them, and runs incremental Structure-from-Motion."
  * "It cleans the point cloud and uses RANSAC to fit geometric planes."
  * "Notice the spatial query engine output in the terminal: it calculates floor area and dimensions purely from the planar boundaries."
  * *Show the 3D Viewer*: "The viewer shows the semantic planes (Green = Floor, Blue = Ceiling, Red = Walls). These aren't neural network guesses; they are mathematical planes intersecting in 3D space."

## Phase 2: Live "Iron Man" Mode (3 mins)
* *Action*: Run `python -m visionforge.cli live` while pointing the laptop webcam at the room.
* *Talking points*:
  * "We now switch to live visual odometry. The left window shows KLT feature tracking in real-time."
  * "The right window shows the 3D Digital Twin. As I move the camera, it computes the Essential Matrix, recovers relative pose, and updates the virtual camera trajectory."
  * "You can see the sparse map growing dynamically as new points are triangulated."
  * "This demonstrates the foundation of a spatial understanding system running locally and classically."

## Conclusion (1 min)
* Acknowledge scale drift in monocular live mode as a known limitation, and explain how the Scene Graph architecture sets the stage for higher-level spatial reasoning.
