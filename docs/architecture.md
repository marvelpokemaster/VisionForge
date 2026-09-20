# VisionForge Architecture

VisionForge is a purely classical computer vision pipeline designed to convert a monocular video sequence into a semantically aware geometric digital twin of an indoor space.

## Components

1. **Video Ingestion (Prototype 0)**
   - Extracts discrete frames from a continuous video sequence.
   - Evaluates frame sharpness to select optimal keyframes.

2. **Visual Reconstruction (Prototype 1)**
   - Utilizes SIFT features for image description.
   - Matches features sequentially using FLANN/Brute-Force matchers.
   - Validates geometry using the Essential Matrix and RANSAC.
   - Employs Incremental Structure-from-Motion (via pycolmap) to generate a global sparse point cloud and camera trajectory.

3. **Room Geometry (Prototype 2)**
   - Voxel downsampling and statistical noise removal via Open3D.
   - Iterative planar RANSAC to extract dominant geometric surfaces.
   - Classifies planes (Floor, Ceiling, Walls) via normal vectors and height heuristics.
   - Constructs a scaled geometric model (length, width, height, area).

4. **Spatial Scene Graph & Queries (Final Prototype)**
   - Connects semantic entities (Room -> contains -> Walls/Floor).
   - Establishes geometric relationships (`adjacent_to`, `parallel_to`, `perpendicular_to`).
   - Query engine provides deterministic architectural answers (`get_floor_area`, `check_rectangular_fit`).

5. **Digital Twin Viewer (Final Prototype)**
   - Open3D-powered 3D visualization.
   - Displays bounding boxes oriented along plane normals, color-coded by semantic classification.
   - Offline Mode: Complete final geometry.
   - Live Mode: Real-time Classical Visual Odometry (KLT + 5-point algorithm) displaying the sparse map and trajectory growth.

## External Libraries
- **OpenCV**: Feature extraction, optical flow, geometric verification.
- **Open3D**: Point cloud manipulation, planar RANSAC, 3D visualization.
- **Pycolmap**: Incremental Structure-from-Motion.
