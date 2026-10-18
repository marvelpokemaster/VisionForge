import { describe, it, expect } from "vitest";
import { buildFrustumGeometry } from "./frustum";

describe("buildFrustumGeometry", () => {
  it("builds frustum with default parameters when cameraParams is undefined", () => {
    const geom = buildFrustumGeometry([0, 0, 0], [0, 0, 1], [0, 1, 0], [1, 0, 0], undefined);
    expect(geom).toBeDefined();
    const pos = geom.getAttribute("position");
    expect(pos).toBeDefined();
    // 4 apex-to-corner segments + 4 base rectangle segments = 8 segments = 16 vertices
    expect(pos.count).toBe(16);
  });

  it("correctly reads PINHOLE parameters [fx, fy, cx, cy]", () => {
    // fx = 800, fy = 600, cx = 320, cy = 240
    const geom = buildFrustumGeometry(
      [0, 0, 0],
      [0, 0, 1],
      [0, 1, 0],
      [1, 0, 0],
      [800, 600, 320, 240],
      1.0,
      "PINHOLE"
    );
    const pos = geom.getAttribute("position");
    expect(pos.count).toBe(16);

    // apex is at (0, 0, 0)
    expect(pos.getX(0)).toBe(0);
    expect(pos.getY(0)).toBe(0);
    expect(pos.getZ(0)).toBe(0);

    // Corner 0 is center + u + r = (0,0,1) + (0, 240/600, 0) + (320/800, 0, 0) = (0.4, 0.4, 1.0)
    expect(pos.getX(1)).toBeCloseTo(0.4);
    expect(pos.getY(1)).toBeCloseTo(0.4);
    expect(pos.getZ(1)).toBeCloseTo(1.0);
  });

  it("correctly reads SIMPLE_RADIAL parameters [f, cx, cy, k]", () => {
    // f = 800, cx = 400, cy = 300, k = 0.01
    const geom = buildFrustumGeometry(
      [0, 0, 0],
      [0, 0, 1],
      [0, 1, 0],
      [1, 0, 0],
      [800, 400, 300, 0.01],
      1.0,
      "SIMPLE_RADIAL"
    );
    const pos = geom.getAttribute("position");
    // Corner 0 is center + u + r = (0,0,1) + (0, 300/800, 0) + (400/800, 0, 0) = (0.5, 0.375, 1.0)
    expect(pos.getX(1)).toBeCloseTo(0.5);
    expect(pos.getY(1)).toBeCloseTo(0.375);
    expect(pos.getZ(1)).toBeCloseTo(1.0);
  });
});
