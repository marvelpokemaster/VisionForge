import * as THREE from "three";
import type { OrbitControls } from "three/addons/controls/OrbitControls.js";

export type CameraPreset = "isometric" | "topdown" | "eyelevel";

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
        title="Perspective 3D Isometric View"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.12 6.4-6.05-4.06a2 2 0 0 0-2.17-.05L2.9 8.4a2 2 0 0 0-.9 1.66v7.88a2 2 0 0 0 .93 1.7l6.05 4.06a2 2 0 0 0 2.17.05l9.95-6.1a2 2 0 0 0 .9-1.66V9.1c0-.7-.37-1.35-.98-1.7z" />
          <polyline points="3.29 7 12 12 20.71 7" />
          <line x1="12" y1="22" x2="12" y2="12" />
        </svg>
        <span>3D Orbit</span>
      </button>

      <button
        type="button"
        className={`hud-btn ${activePreset === "topdown" ? "active" : ""}`}
        onClick={() => onSelectPreset("topdown")}
        title="2D Top-Down Floor Plan"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <path d="M3 9h18" />
          <path d="M9 21V9" />
        </svg>
        <span>Floor Plan</span>
      </button>

      <button
        type="button"
        className={`hud-btn ${activePreset === "eyelevel" ? "active" : ""}`}
        onClick={() => onSelectPreset("eyelevel")}
        title="Eye-Level Interior Walkthrough"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
        <span>Eye Level</span>
      </button>
    </div>
  );
}
