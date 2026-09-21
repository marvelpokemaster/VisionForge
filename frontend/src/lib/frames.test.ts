import { describe, it, expect } from "vitest";
import { toRoomFrame, transformPointsToRoomFrame, quaternionToRotationMatrix, cameraAxesRoomFrame } from "./frames";
import type { CoordinateSystem } from "../types/twin";

describe("toRoomFrame", () => {
  it("translates by origin under an axis-aligned (identity) frame", () => {
    const coordSystem: CoordinateSystem = {
      origin: [1, 2, 3],
      up_axis: [0, 1, 0],
      horizontal_axes: [
        [1, 0, 0],
        [0, 0, 1]
      ]
    };
    // rel = (2-1, 5-2, 3-3) = (1, 3, 0)
    expect(toRoomFrame([2, 5, 3], coordSystem)).toEqual([1, 3, 0]);
    // the origin itself must map to (0, 0, 0)
    expect(toRoomFrame([1, 2, 3], coordSystem)).toEqual([0, 0, 0]);
  });

  it("correctly assigns X/Y/Z under a non-identity (permuted) frame -- a hand-built case", () => {
    // A deliberately non-trivial orthonormal frame: room X comes from
    // world Y, room Y (up) comes from world X, room Z stays world Z.
    // This is a real, valid case (any wall/floor's own axes end up looking
    // like this), and unlike an axis-aligned frame it actually exercises
    // that each output component is the dot product with the RIGHT axis.
    const coordSystem: CoordinateSystem = {
      origin: [0, 0, 0],
      up_axis: [1, 0, 0],
      horizontal_axes: [
        [0, 1, 0],
        [0, 0, 1]
      ]
    };
    // point (2,3,4): room_x = dot(p, [0,1,0]) = 3
    //                room_y = dot(p, [1,0,0]) = 2
    //                room_z = dot(p, [0,0,1]) = 4
    expect(toRoomFrame([2, 3, 4], coordSystem)).toEqual([3, 2, 4]);
  });

  it("matches the server's own room-frame values for a real floor centroid", () => {
    // Taken from an actual twin.json: the floor plane is the room-frame
    // origin reference, so its own centroid must map to (0,0,0).
    const coordSystem: CoordinateSystem = {
      origin: [-6.137041072005592, -2.175390772123907, 17.00535949663795],
      up_axis: [0.3417692142071482, 0.08600146349779596, -0.9358405593350108],
      horizontal_axes: [
        [0.9397786015958685, -0.0346239240715746, 0.3400255341358937],
        [0.0031597789072086817, 0.995693191780542, 0.09265572642386682]
      ]
    };
    const floorCentroid: [number, number, number] = [
      -6.137041072005592, -2.175390772123907, 17.00535949663795
    ];
    const [x, y, z] = toRoomFrame(floorCentroid, coordSystem);
    expect(x).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(0, 9);
    expect(z).toBeCloseTo(0, 9);
  });
});

describe("transformPointsToRoomFrame", () => {
  it("transforms a flat xyz Float32Array point-by-point", () => {
    const coordSystem: CoordinateSystem = {
      origin: [0, 0, 0],
      up_axis: [0, 1, 0],
      horizontal_axes: [
        [1, 0, 0],
        [0, 0, 1]
      ]
    };
    const points = new Float32Array([1, 2, 3, 4, 5, 6]);
    const out = transformPointsToRoomFrame(points, coordSystem);
    expect(Array.from(out)).toEqual([1, 2, 3, 4, 5, 6]); // identity frame -> unchanged
  });

  it("preserves array length and applies a real translation to every point", () => {
    const coordSystem: CoordinateSystem = {
      origin: [1, 1, 1],
      up_axis: [0, 1, 0],
      horizontal_axes: [
        [1, 0, 0],
        [0, 0, 1]
      ]
    };
    const points = new Float32Array([1, 1, 1, 2, 2, 2]);
    const out = transformPointsToRoomFrame(points, coordSystem);
    expect(out.length).toBe(6);
    expect(Array.from(out)).toEqual([0, 0, 0, 1, 1, 1]);
  });
});

describe("quaternionToRotationMatrix", () => {
  it("matches the independently known matrix for a +90deg rotation about Z", () => {
    // Same hand-built case as the backend's test_quat_to_rotation_matrix_known_90deg_about_z.
    const s = Math.sin(Math.PI / 4);
    const c = Math.cos(Math.PI / 4);
    const R = quaternionToRotationMatrix([0, 0, s, c]);

    const expected = [
      [0, -1, 0],
      [1, 0, 0],
      [0, 0, 1]
    ];
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        expect(R[i][j]).toBeCloseTo(expected[i][j], 9);
      }
    }
  });
});

describe("cameraAxesRoomFrame", () => {
  it("for identity rotation under an identity room frame, matches COLMAP's own convention directly", () => {
    // R = I: forward = R^T@[0,0,1] = [0,0,1]; up = R^T@[0,-1,0] = [0,-1,0]
    // (COLMAP's image Y points down, so "up" is world -Y when unrotated);
    // right = R^T@[1,0,0] = [1,0,0]. An identity room frame leaves these unchanged.
    const identityFrame: CoordinateSystem = {
      origin: [0, 0, 0],
      up_axis: [0, 1, 0],
      horizontal_axes: [
        [1, 0, 0],
        [0, 0, 1]
      ]
    };
    const axes = cameraAxesRoomFrame([0, 0, 0, 1], identityFrame);
    expect(axes.forward.map((v) => Math.round(v))).toEqual([0, 0, 1]);
    expect(axes.up.map((v) => Math.round(v))).toEqual([0, -1, 0]);
    expect(axes.right.map((v) => Math.round(v))).toEqual([1, 0, 0]);
  });
});
