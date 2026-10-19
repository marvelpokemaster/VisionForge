# VisionForge — Architectural 3D Digital Twin & Room Studio

A comprehensive, dependency-ordered architectural transformation of VisionForge from an engineering diagnostic tool into an aesthetic, warm architectural 3D room studio centered around frictionless video-to-twin reconstruction and furniture spatial planning.

---

### User Review & Critical Decisions

> [!IMPORTANT]
> **Confirmed Architectural Directives**:
> - **Design System**: Warm studio palette (`#0e1117` dark slate background, `#e07a5f` terracotta accent, `#fff8ee` warm light, `#f3f4f6` crisp text) with `Plus Jakarta Sans` for UI and `Space Grotesk` for metric numerals.
> - **3D Visual Engine**: Procedural oak wood plank canvas texture and warm plaster wall materials (zero external asset dependencies); three-point warm studio lighting (3200K golden key light, 6500K cool sky fill, floor rim light); smooth camera presets (Isometric 3D, Top-Down 2D, Eye-Level) with automatic lerp cancelation when user manipulates `OrbitControls`.
> - **Persistent 3D Viewport**: `<StudioViewer/>` remains mounted persistently in the background across 3D Room, Furnish, and Measure tabs so the WebGL context is never torn down or re-initialized during navigation.
> - **Hero Video Ingestion**: Prominent drag-and-drop zone (`.mp4`, `.mov`, `.webm`) and 3 instant room presets (*Master Bedroom Scan*, *Modern Living Room*, *Studio Loft*) with asynchronous frame extraction, 4-stage pipeline visualization, and instant transition to the digital twin.
> - **Spatial Intelligence**: Unchanged core computational geometry (Separating Axis Theorem for collision, floor clearance polygon validation, auto-packing density solver, and spatial query NLP router) connected directly to modern visual cards and sliders.

---

## 1. Overview & Core Concept

VisionForge provides an effortless bridge between real-world video capture and actionable 3D room twins:
- **Scan / Upload**: Users upload any indoor walk-through video or pick a pre-loaded sample room. The application processes frames through an animated 4-stage pipeline (*Video Ingestion → Visual Feature Matching → Architectural Plane Fitting → Digital Twin Synthesis*).
- **3D Room Twin View**: A warm architectural studio presentation featuring procedural oak flooring, warm ambient light, subtle shadows, and camera viewpoint presets.
- **Furnish & Fit**: Real-world furniture catalog with interactive placement, real-time SAT collision feedback, and one-click auto-packing.
- **Measure & Insights**: Instant room dimensions ($L, W, H, \text{Area}$) with tape-measurement scale recalibration and a conversational spatial query assistant.

---

## 2. Technical Architecture & Component Hierarchy

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   App Shell (App.tsx)                                      │
│  - Active Tab: 'viewer' | 'furnish' | 'measure' | 'upload'                                 │
│  - Active Session: 'final_demo' | 'live_synth_30' | custom uploaded scan                    │
│  - Persistent Studio State: RoomModel, PlacedFurniture[], Toggles, Measurements            │
├────────────────────────────────────────────────────────────────────────────────────────────┤
│  Top Navigation Bar: Brand · Room Selector Badge · 4-Tab Switcher · Backend Connectivity   │
├─────────────────────────────────────────────────────────────┬──────────────────────────────┤
│                                                             │ Dynamic Studio Panel (Right) │
│              Persistent 3D Canvas Container                 ├──────────────────────────────┤
│                     <StudioViewer />                        │ [Tab: viewer]                │
│  - Three.js WebGLRenderer (SRGBColorSpace, shadows)         │  • Surface inspector         │
│  - Procedural Oak Floor (CanvasTexture, roughness 0.4)      │  • Layer toggles (cloud/mesh)│
│  - Matte Plaster Walls (DoubleSide, crisp outline loop)     ├──────────────────────────────┤
│  - Three-Point Lighting Rig (Key 3200K, Fill 6500K, Rim)   │ [Tab: furnish]               │
│  - OrbitControls with manual-override interrupt             │  • Furniture catalog cards   │
│  - 3D Bounding Proxies with Green/Red SAT status            │  • X/Z/Angle sliders         │
│  - Floating Camera Presets HUD:                             │  • Auto-Pack Usable Space    │
│    [Isometric 3D] [Top-Down 2D] [Eye-Level]                 ├──────────────────────────────┤
│                                                             │ [Tab: measure]               │
│                                                             │  • Metric cards (L, W, H, A) │
│                                                             │  • Scale Calibration slider  │
│                                                             │  • Room Query NLP Box        │
├─────────────────────────────────────────────────────────────┴──────────────────────────────┤
│ [Tab: upload] Full-Screen Overlay / Modal Mode:                                            │
│  • Drag-and-drop zone (.mp4, .mov, .webm)                                                  │
│  • 3 Instant Sample Presets (Master Bedroom, Modern Living Room, Studio Loft)             │
│  • 4-Stage Reconstruction Progress Visualizer (60fps animation)                            │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Phase-by-Phase Implementation Plan

### Phase 1: State Architecture & Design System Foundation
1. **Typography & Styling Tokens (`src/index.css`)**:
   - Google Font imports for `Plus Jakarta Sans` and `Space Grotesk`.
   - CSS variables:
     - `--bg-slate`: `#0e1117`
     - `--bg-panel`: `#151922`
     - `--accent-terracotta`: `#e07a5f`
     - `--accent-emerald`: `#2a9d8f`
     - `--light-warm`: `#fff8ee`
     - `--text-crisp`: `#f3f4f6`
     - `--text-muted`: `#94a3b8`
     - `--border-hairline`: `rgba(255, 255, 255, 0.08)`
     - `--border-accent`: `rgba(224, 122, 95, 0.3)`
2. **Global Navigation & Session State (`src/App.tsx`)**:
   - Navigation state: `activeTab: 'viewer' | 'furnish' | 'measure' | 'upload'`.
   - Maintain active digital twin, loaded measurements, and placed furniture in synchronized state.
   - Enforce schema validation for local custom sessions saved in `localStorage`.

### Phase 2: 3D Studio Engine & Procedural Materials
1. **Procedural Studio Material Generator (`src/lib/studioMaterials.ts`)**:
   - **Oak Wood Plank Texture**: 1024×1024 canvas drawing randomized wood grain curves, warm honey/oak plank bands, and dark bevel seams. Wrapped in `THREE.CanvasTexture` with `wrapS = wrapT = THREE.RepeatWrapping`, repeated across floor dimensions, with `roughness: 0.4`.
   - **Plaster Walls**: Warm off-white (`#fff8ee`) matte standard material with `roughness: 0.85`, `side: THREE.DoubleSide`, and subtle hairline wireframe edges.
   - **Resource Management**: Singleton pattern for textures and materials with lifecycle cleanup (`dispose()`) on unmount.
2. **Three-Point Studio Lighting Rig (`src/components/StudioViewer.tsx`)**:
   - **Key Light**: `THREE.DirectionalLight(0xfff0dd, 1.8)` with soft shadows and shadow-acne bias tuning.
   - **Fill Light**: `THREE.HemisphereLight(0xddeeff, 0x222228, 0.6)` simulating daylight ambient wash.
   - **Rim Light**: Soft low point light near perimeter highlighting architectural wall silhouettes.
3. **Smooth Camera Controller (`src/components/CameraControlsHUD.tsx`)**:
   - Presets: **Isometric 3D** (`[6, 6, 6]`), **Top-Down 2D** (`[0, 10, 0]`), and **Eye-Level** (`[0, 1.5, 3]`).
   - Slerp/lerp interpolation toward targets inside the animation loop.
   - **Critical Guardrail**: Add `OrbitControls` `start` listener to abort any active camera animation instantly when user drags or zooms.

### Phase 3: Core Tab Workflows & UI Docks
1. **Hero Upload Studio (`src/components/UploadStudio.tsx`)**:
   - Drag-and-drop file target accepting `.mp4`, `.mov`, `.webm`.
   - 3 Pre-packaged room sample presets (*Master Bedroom Scan*, *Modern Living Room*, *Studio Loft*).
   - Async metadata extraction via offscreen `<video>` and `<canvas>` elements.
   - 4-stage visual progress pipeline (*Video Ingestion → Visual Feature Matching → Architectural Plane Fitting → Digital Twin Synthesis*) animating at 60fps, immediately loading the new twin upon completion.
2. **Furnish & Fit Tab (`src/components/FurnishTab.tsx`)**:
   - Visual catalog cards for Queen Bed, Single Bed, 3-Seater Sofa, 2-Seater Sofa, Work Desk, Dining Table, Wardrobe, Nightstand.
   - Sliders for $X$, $Z$, and rotation angle $\theta$.
   - Live 2D/3D Separating Axis Theorem (SAT) collision detection updating bounding box colors in real time (Emerald Green for valid fit, Terracotta Red for collision).
   - **Auto-Pack Usable Space** button with packing density readout.
3. **Measure & Insights Tab (`src/components/MeasureTab.tsx`)**:
   - Architectural tabular cards for Room Length, Width, Height, and Usable Area.
   - Scale Calibration slider (0.5x to 2.0x) recalculating dimensions and clearance boundaries dynamically.
   - Room Query Assistant with pre-set quick questions (*"What is the ceiling height?"*, *"Which wall is largest?"*, *"Which walls are parallel?"*) and freeform natural language query matching.

### Phase 4: Hardened Verification & Cutover Checklist
1. **Build & Typecheck**:
   - Verify `tsc -b` and `compile_applet` pass with 0 errors.
2. **Persistence & Lifecycle Stress Testing**:
   - Upload sample video $\rightarrow$ view 3D twin $\rightarrow$ add 2 furniture items $\rightarrow$ calibrate scale $\rightarrow$ refresh page $\rightarrow$ verify all data cleanly restored from `localStorage`.
3. **Collision & Usable Space Validation**:
   - Verify furniture turning red when intersecting room boundary walls or overlapping existing items.
   - Verify auto-pack fills room in $<100\text{ ms}$ with calculated coverage ratio.
