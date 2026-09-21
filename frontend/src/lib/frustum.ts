import * as THREE from "three";
import type { Vec3 } from "../types/twin";

/** A small wireframe camera frustum (apex + 4 base corners), oriented by
 * real forward/up/right vectors and sized from the camera's own intrinsics
 * (fx, cx, cy) when available, so the frustum's shape is honest rather
 * than an arbitrary fixed cone. */
export function buildFrustumGeometry(
  position: Vec3,
  forward: Vec3,
  up: Vec3,
  right: Vec3,
  cameraParams: number[] | undefined,
  size = 0.4
): THREE.BufferGeometry {
  const [fx, cx, cy] = cameraParams && cameraParams.length >= 3 ? cameraParams : [1, 1, 1];
  const halfW = Math.max(0.1, cx / fx) * size;
  const halfH = Math.max(0.1, cy / fx) * size;

  const apex = new THREE.Vector3(...position);
  const f = new THREE.Vector3(...forward).normalize().multiplyScalar(size);
  const u = new THREE.Vector3(...up).normalize().multiplyScalar(halfH);
  const r = new THREE.Vector3(...right).normalize().multiplyScalar(halfW);

  const center = apex.clone().add(f);
  const corners = [
    center.clone().add(u).add(r),
    center.clone().add(u).sub(r),
    center.clone().sub(u).sub(r),
    center.clone().sub(u).add(r)
  ];

  const positions: number[] = [];
  const pushSegment = (a: THREE.Vector3, b: THREE.Vector3) => {
    positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
  };

  // apex -> each base corner
  for (const c of corners) pushSegment(apex, c);
  // base rectangle edges
  for (let i = 0; i < corners.length; i++) {
    pushSegment(corners[i], corners[(i + 1) % corners.length]);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}
