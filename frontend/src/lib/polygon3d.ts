import * as THREE from "three";
import type { Vec3 } from "../types/twin";

/** Fan-triangulated filled geometry from an ordered (convex) polygon.
 * Materials should use THREE.DoubleSide so winding order never matters. */
export function polygonToFilledGeometry(boundary: Vec3[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  if (boundary.length < 3) return geometry;

  const positions: number[] = [];
  for (const [x, y, z] of boundary) positions.push(x, y, z);

  const indices: number[] = [];
  for (let i = 1; i < boundary.length - 1; i++) {
    indices.push(0, i, i + 1);
  }

  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

/** A closed line loop around the polygon's boundary, for the wireframe outline. */
export function polygonToLineLoopGeometry(boundary: Vec3[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  const positions: number[] = [];
  for (const [x, y, z] of boundary) positions.push(x, y, z);
  if (boundary.length > 0) {
    positions.push(boundary[0][0], boundary[0][1], boundary[0][2]);
  }
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}
