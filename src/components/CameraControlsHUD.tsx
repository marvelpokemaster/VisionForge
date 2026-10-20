import * as THREE from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";

export type CameraPreset = "isometric" | "topdown" | "eyelevel" | "front";

interface Props {
  camera: THREE.PerspectiveCamera | null;
  controls: OrbitControls | null;
  activePreset: CameraPreset | null;
  onSelectPreset: (preset: CameraPreset) => void;
}

export default function CameraControlsHUD({
  activePreset,
  onSelectPreset,
}: Props) {
  return (
    <div className="camera-hud">
      <button
        type="button"
        className={`hud-btn ${activePreset === "isometric" ? "active" : ""}`}
        onClick={() => onSelectPreset("isometric")}
        title="3D Dollhouse View (Cutaway walls)"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.12 6.4-6.05-4.06a2 2 0 0 0-2.17-.05L2.9 8.4a2 2 0 0 0-.9 1.66v7.88a2 2 0 0 0 .93 1.7l6.05 4.06a2 2 0 0 0 2.17.05l9.95-6.1a2 2 0 0 0 .9-1.66V9.1c0-.7-.37-1.35-.98-1.7z" />
          <polyline points="3.29 7 12 12 20.71 7" />
          <line x1="12" y1="22" x2="12" y2="12" />
        </svg>
        <span>3D Dollhouse</span>
      </button>

      <button
        type="button"
        className={`hud-btn ${activePreset === "topdown" ? "active" : ""}`}
        onClick={() => onSelectPreset("topdown")}
        title="2D Blueprint Floor Plan"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <path d="M3 9h18" />
          <path d="M9 21V9" />
        </svg>
        <span>2D Blueprint</span>
      </button>

      <button
        type="button"
        className={`hud-btn ${activePreset === "eyelevel" ? "active" : ""}`}
        onClick={() => onSelectPreset("eyelevel")}
        title="Inside Room Walkthrough (1.5m human eye level)"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
        <span>Inside Room</span>
      </button>

      <button
        type="button"
        className={`hud-btn ${activePreset === "front" ? "active" : ""}`}
        onClick={() => onSelectPreset("front")}
        title="Front Architectural Elevation"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="18" height="14" x="3" y="5" rx="2" />
          <line x1="3" y1="12" x2="21" y2="12" />
        </svg>
        <span>Front Elevation</span>
      </button>
    </div>
  );
}
