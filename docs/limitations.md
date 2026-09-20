# Known Limitations

VisionForge is a research prototype prioritizing technical honesty over commercial polish.

1. **Scale Ambiguity**: Monocular reconstruction inherently cannot deduce absolute metric scale. The offline pipeline accepts a reference distance to calibrate scale. Without it, dimensions are arbitrary.
2. **Live Scale Drift**: The live tracking mode utilizes classical visual odometry (VO). Because it does not run global Bundle Adjustment or loop closure in real-time, scale will drift over long trajectories.
3. **Manhattan World Assumption**: Plane classification assumes rooms have flat, orthogonal walls. Slanted roofs or highly irregular geometry will be marked as "unknown".
4. **Featureless Walls**: Classical feature extractors (SIFT/KLT) fail on blank, textureless white walls. A densely textured environment yields the best point cloud.
5. **No Semantic Object Detection**: VisionForge builds a *geometric* scene graph (walls, floors). It deliberately avoids neural networks, so it does not identify semantic objects like chairs or monitors.
