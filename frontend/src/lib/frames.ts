import type { CoordinateSystem, Vec3, Vec4 } from "../types/twin";

/**
 * Everything the API already computes (plane centroids/boundaries, camera
 * positions, intersection segments, the room bounding polygon) is served
 * pre-transformed into the room frame (the `*_room` fields). The ONE thing
 * that is NOT pre-transformed is the raw sparse point cloud PLY, which is
 * only ever produced in the reconstruction frame (COLMAP's convention,
 * arbitrary orientation -- typically Y-down, which would render upside
 * down in three.js's Y-up world). This module is the single place that
 * transform happens, client-side, mirroring room_model.py's
 * `_room_frame_point` exactly:
 *
 *   rel = point - origin
 *   room = [dot(rel, x_axis), dot(rel, up_axis), dot(rel, z_axis)]
 *
 * so that room-frame Y is up_axis, matching three.js's +Y up convention.
 */
export function toRoomFrame(point: Vec3, coordSystem: CoordinateSystem): Vec3 {
  const [px, py, pz] = point;
  const [ox, oy, oz] = coordSystem.origin;
  const rel: Vec3 = [px - ox, py - oy, pz - oz];

  const [xAxis, zAxis] = coordSystem.horizontal_axes;
  const upAxis = coordSystem.up_axis;

  return [dot3(rel, xAxis), dot3(rel, upAxis), dot3(rel, zAxis)];
}

/** Transforms a flat Float32Array of xyz triples (as loaded from a PLY) into
 * the room frame in place-compatible form, returning a new Float32Array. */
export function transformPointsToRoomFrame(
  points: Float32Array,
  coordSystem: CoordinateSystem
): Float32Array {
  const out = new Float32Array(points.length);
  for (let i = 0; i + 2 < points.length; i += 3) {
    const [x, y, z] = toRoomFrame([points[i], points[i + 1], points[i + 2]], coordSystem);
    out[i] = x;
    out[i + 1] = y;
    out[i + 2] = z;
  }
  return out;
}

function dot3(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/** Same rotation-direction transform as toRoomFrame, but for a direction
 * vector (no origin subtraction) -- used for camera orientation, not
 * position. */
export function toRoomFrameDirection(direction: Vec3, coordSystem: CoordinateSystem): Vec3 {
  const [xAxis, zAxis] = coordSystem.horizontal_axes;
  const upAxis = coordSystem.up_axis;
  return [dot3(direction, xAxis), dot3(direction, upAxis), dot3(direction, zAxis)];
}

/** Unit-quaternion [x,y,z,w] -> 3x3 rotation matrix (rows), mirroring
 * scene_graph.py's _quat_to_rotation_matrix exactly, for parity with the
 * backend's own camera math. */
export function quaternionToRotationMatrix(q: Vec4): [Vec3, Vec3, Vec3] {
  let [qx, qy, qz, qw] = q;
  const n = Math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw);
  qx /= n;
  qy /= n;
  qz /= n;
  qw /= n;
  return [
    [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
    [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
    [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]
  ];
}

function transposeMatVec3(m: [Vec3, Vec3, Vec3], v: Vec3): Vec3 {
  // m^T @ v
  return [
    m[0][0] * v[0] + m[1][0] * v[1] + m[2][0] * v[2],
    m[0][1] * v[0] + m[1][1] * v[1] + m[2][1] * v[2],
    m[0][2] * v[0] + m[1][2] * v[1] + m[2][2] * v[2]
  ];
}

export interface CameraAxesRoomFrame {
  forward: Vec3;
  up: Vec3;
  right: Vec3;
}

/**
 * A camera's forward/up/right directions in the room frame, derived from
 * cameras.json's rotation_quat (cam_from_world: p_cam = R @ p_world + t,
 * COLMAP convention: the camera looks along local +Z, X is right, Y is
 * DOWN the image). World-frame direction = R^T @ local_direction; that
 * world-frame vector is then rotated (not translated) into the room frame
 * via toRoomFrameDirection, exactly mirroring how positions are handled.
 */
export function cameraAxesRoomFrame(rotationQuat: Vec4, coordSystem: CoordinateSystem): CameraAxesRoomFrame {
  const R = quaternionToRotationMatrix(rotationQuat);
  const forwardWorld = transposeMatVec3(R, [0, 0, 1]);
  const upWorld = transposeMatVec3(R, [0, -1, 0]); // local -Y, since image Y points down
  const rightWorld = transposeMatVec3(R, [1, 0, 0]);

  return {
    forward: toRoomFrameDirection(forwardWorld, coordSystem),
    up: toRoomFrameDirection(upWorld, coordSystem),
    right: toRoomFrameDirection(rightWorld, coordSystem)
  };
}
