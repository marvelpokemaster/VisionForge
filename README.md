# VisionForge — 3D Digital Twin & Architectural Room Studio

VisionForge is a pure classical computer vision system and architectural 3D digital twin studio built with React 19, TypeScript, Vite, and Three.js. It transforms ordinary smartphone video walk-arounds into interactive 3D digital twins with real metric measurements, usable floor clearance polygons, in-canvas 3D furniture manipulation, and automated space-packing algorithms.

---

## 🌟 Key Highlights & Architectural Features

### 1. Classical 4-Stage Video-to-Twin Pipeline
* **Zero Deep Learning / Zero AI Black Boxes**: Strictly powered by classical computer vision and 2D/3D computational geometry (SIFT/ORB feature correspondence, epipolar geometry, RANSAC planar surface segmentation, and polygon intersection math).
* **Automated Reconstruction Flow**:
  1. **Video Ingestion & Parallax Sampling**: Extracts sharp, blur-free frames with sufficient baseline movement.
  2. **Feature Matching & Tracking**: Identifies correspondences across frames to solve camera pose trajectories.
  3. **Architectural Plane Segmentation**: Fits mathematical plane equations for floors, walls, and ceilings using RANSAC.
  4. **Digital Twin Synthesis**: Extracts 2D/3D boundary polygons, calculates plane-plane intersections, and builds an interconnected spatial scene graph.

### 2. Warm Architectural 3D Studio (Three.js WebGL)
* **Procedural PBR Materials (Zero External Assets)**: High-resolution procedural oak wood plank flooring generated on an offscreen HTML5 canvas with realistic plank bevel seams and grain curves; paired with warm matte plaster walls and soft perimeter outlines.
* **Studio Lighting Rig**: Three-point warm illumination (3200K golden key light with soft shadow mapping, 6500K cool ambient fill, and subtle floor rim light).
* **Instant Camera Presets**: 1-click viewpoint transitions for **3D Orbit**, **2D Floor Plan**, and **Eye-Level Walkthrough** with smooth damping and automatic manual-override cancelation when the user interacts with `OrbitControls`.
* **Persistent WebGL Viewport**: The 3D canvas remains mounted persistently across tabs so the GPU rendering context never re-initializes during navigation.

### 3. Spatial Intelligence & Floor Clearance Studio
* **Separating Axis Theorem (SAT) Collision Engine**: Real-time 2D/3D collision detection ensuring placed furniture items fit inside the room boundary polygon without clipping walls or overlapping other items.
* **Direct In-Canvas 3D Gizmos (`TransformControls`)**: Click and drag any furniture item directly in the 3D viewport along the $XZ$ floor plane, or switch to $Y$-axis rotation mode while UI sliders and collision badges update in lockstep.
* **Auto-Pack Usable Space Solver**: One-click space optimizer that computes the maximum number of furniture units that fit into the available floor clearance, outputting exact unit counts and floor coverage efficiency ratios.

### 4. Metric Measurement & Conversational Room Assistant
* **Calibrated Dimensions**: Room Length, Width, Ceiling Height, and Usable Floor Area with transparent estimation methodology tags.
* **Tape-Measure Scale Calibration**: Recalibrates scene scale against a known physical tape measurement.
* **Spatial Scene Graph NLP Assistant**: Ask natural language spatial queries (*"What is the ceiling height?"*, *"Which wall is largest?"*, *"Which walls are parallel?"*) and receive deterministic answers directly from the scene graph.

### 5. 1-Click Export & Production Tools
* **High-Res Snapshot (PNG)**: 1-click floor plan screenshot capture directly from the WebGL drawing buffer.
* **Layout Export (JSON)**: Export the calibrated digital twin, surface polygons, and placed furniture coordinates for CAD or architectural tools.

---

## 🚀 Getting Started

### Prerequisites
- Node.js 20+
- npm

### Installation & Development

```bash
# Clone the repository
git clone https://github.com/marvelpokemaster/VisionForge.git
cd VisionForge

# Install dependencies
npm install

# Start the development server on port 3000
npm run dev

# Build for production
npm run build
```

Open `http://localhost:3000` in your browser to explore the studio.

---

## 📁 Project Architecture

```
├── public/
│   ├── sessions/final_demo/    # Reference physical room scan & PLY point cloud
│   └── sessions/live_synth_30/ # Synthetic room tracking scan & PLY point cloud
├── src/
│   ├── components/
│   │   ├── StudioViewer.tsx     # Persistent Three.js WebGL viewport & TransformControls
│   │   ├── CameraControlsHUD.tsx# Floating camera preset HUD (Isometric, Floor Plan, Eye Level)
│   │   ├── FurnishTab.tsx       # Furniture catalog, SAT collision, and Auto-Pack dock
│   │   ├── MeasureTab.tsx       # Metric dimensions, scale calibration, and NLP assistant
│   │   ├── SurfaceInspectorTab.tsx # Click-to-inspect plane surface details
│   │   ├── UploadStudio.tsx     # Hero drag-and-drop video reconstruction pipeline
│   │   └── BackendField.tsx     # Optional remote server & live phone streaming config
│   ├── lib/
│   │   ├── studioMaterials.ts   # Procedural oak wood floor & plaster wall materials
│   │   ├── clearance.ts         # Computational geometry, SAT collision, and Auto-Pack solver
│   │   ├── spatialQueries.ts    # Spatial scene graph query parser
│   │   └── standaloneStore.ts   # Zero-config offline fixture provider & local persistence
│   ├── types/
│   │   ├── twin.ts              # Digital twin, planes, cameras, and scene graph schemas
│   │   └── furniture.ts         # Furniture catalog, placement items, and pack results
│   ├── App.tsx                  # Main 4-tab studio application shell
│   └── index.css                # Architectural design system tokens & responsive styles
├── vite.config.ts               # Vite configuration (port 3000, backend proxy)
└── package.json
```

---

## 📜 License

MIT License. See [LICENSE](LICENSE) for details.