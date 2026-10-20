import * as THREE from "three";
import type { Vec3 } from "../types/twin";

/** Fan-triangulated filled geometry from an ordered (convex) polygon.
 * Materials should use THREE.DoubleSide so winding order never matters. */
export function polygonToFilledGeometry(boundary?: Vec3[] | null): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  if (!boundary || boundary.length < 3) return geometry;

  const positions: number[] = [];
  const uvs: number[] = [];
  for (const [x, y, z] of boundary) {
    positions.push(x, y, z);
    // Project UVs onto horizontal XZ plane for floors/ceilings or planar projection
    uvs.push(x * 0.75, z * 0.75);
  }

  const indices: number[] = [];
  for (let i = 1; i < boundary.length - 1; i++) {
    indices.push(0, i, i + 1);
  }

  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

/** A closed line loop around the polygon's boundary, for the wireframe outline. */
export function polygonToLineLoopGeometry(boundary?: Vec3[] | null): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  if (!boundary || boundary.length === 0) return geometry;
  const positions: number[] = [];
  for (const [x, y, z] of boundary) positions.push(x, y, z);
  if (boundary.length > 0) {
    positions.push(boundary[0][0], boundary[0][1], boundary[0][2]);
  }
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}
