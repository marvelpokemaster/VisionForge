import * as THREE from "three";
import type { RoomModel, Vec2 } from "../types/twin";
import {
  createWoodFloorMaterial,
  createPlasterWallMaterial,
} from "./studioMaterials";
import { makeTextSprite } from "./labelSprite";

export interface RoomBounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  centerX: number;
  centerZ: number;
  sizeX: number;
  sizeZ: number;
  maxDim: number;
  wallHeight: number;
}

export function computeRoomBounds(roomModel?: RoomModel | null): RoomBounds {
  const room = roomModel?.room;
  const poly = room?.bounding_polygon_room;

  let pts: Vec2[] = [];
  if (poly && poly.length >= 3) {
    pts = poly;
  } else {
    const l = Math.max(room?.length ?? 5.5, 3.0);
    const w = Math.max(room?.width ?? 5.0, 3.0);
    pts = [
      [-w / 2, -l / 2],
      [w / 2, -l / 2],
      [w / 2, l / 2],
      [-w / 2, l / 2],
    ];
  }

  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;

  for (const [x, z] of pts) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }

  const centerX = (minX + maxX) / 2;
  const centerZ = (minZ + maxZ) / 2;
  const sizeX = Math.max(maxX - minX, 2.0);
  const sizeZ = Math.max(maxZ - minZ, 2.0);
  const maxDim = Math.max(sizeX, sizeZ, 4.0);
  const wallHeight = 2.6; // Standard residential wall height in meters

  return {
    minX,
    maxX,
    minZ,
    maxZ,
    centerX,
    centerZ,
    sizeX,
    sizeZ,
    maxDim,
    wallHeight,
  };
}

/**
 * Builds the complete 3D architectural room enclosure:
 * - Hardwood oak plank floor with procedural grain & bevels
 * - Perimeter walls with baseboards, corner posts & crown moldings
 * - Cutaway dollhouse front so the interior is easily visible
 * - Usable free space clearance outline
 * - Architectural dimension extension lines & labels
 */
export function buildArchitecturalRoomShell(
  roomModel: RoomModel | undefined | null,
  options: {
    cutawayFront?: boolean;
    wallHeight?: number;
    showDimensions?: boolean;
  } = {}
): THREE.Group {
  const group = new THREE.Group();
  group.name = "ArchitecturalRoomShell";

  const {
    cutawayFront = true,
    wallHeight = 2.6,
    showDimensions = true,
  } = options;

  const room = roomModel?.room;
  const rawPoly = room?.bounding_polygon_room;

  let pts: Vec2[] = [];
  if (rawPoly && rawPoly.length >= 3) {
    pts = rawPoly;
  } else {
    const l = Math.max(room?.length ?? 5.5, 3.0);
    const w = Math.max(room?.width ?? 5.0, 3.0);
    pts = [
      [-w / 2, -l / 2],
      [w / 2, -l / 2],
      [w / 2, l / 2],
      [-w / 2, l / 2],
    ];
  }

  const bounds = computeRoomBounds(roomModel);
  const { centerX, centerZ } = bounds;

  // 1. Procedural Oak Hardwood Floor (triangulated with proper UVs)
  const shape = new THREE.Shape();
  shape.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) {
    shape.lineTo(pts[i][0], pts[i][1]);
  }
  shape.closePath();

  const floorGeom = new THREE.ShapeGeometry(shape);
  floorGeom.rotateX(Math.PI / 2); // Rotate flat into horizontal XZ plane

  // Assign world-scale UV coordinates so wood planks tile at 1.2m per cycle
  const posAttr = floorGeom.attributes.position;
  const uvs = new Float32Array(posAttr.count * 2);
  for (let i = 0; i < posAttr.count; i++) {
    uvs[i * 2] = (posAttr.getX(i) - bounds.minX) * 0.7;
    uvs[i * 2 + 1] = (posAttr.getZ(i) - bounds.minZ) * 0.7;
  }
  floorGeom.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
  floorGeom.computeVertexNormals();

  const floorMesh = new THREE.Mesh(floorGeom, createWoodFloorMaterial());
  floorMesh.receiveShadow = true;
  floorMesh.position.y = 0.0;
  group.add(floorMesh);

  // Floor Perimeter Bevel Line (Dark Bronze)
  const floorLinePts = pts.map(([x, z]) => new THREE.Vector3(x, 0.003, z));
  floorLinePts.push(new THREE.Vector3(pts[0][0], 0.003, pts[0][1]));
  const floorOutlineGeom = new THREE.BufferGeometry().setFromPoints(floorLinePts);
  const floorOutlineMat = new THREE.LineBasicMaterial({
    color: 0x5a3e28,
    linewidth: 2,
  });
  group.add(new THREE.Line(floorOutlineGeom, floorOutlineMat));

  // 2. Extruded Architectural Perimeter Walls
  const numPts = pts.length;
  const wallMat = createPlasterWallMaterial(false);

  // Cutaway wall material for front-facing segments
  const cutawayMat = new THREE.MeshStandardMaterial({
    color: 0xf5eee4,
    roughness: 0.8,
    metalness: 0.02,
    transparent: true,
    opacity: 0.78,
    side: THREE.DoubleSide,
    depthWrite: true,
  });

  const baseboardMat = new THREE.MeshStandardMaterial({
    color: 0x2b1e16, // Rich walnut baseboard
    roughness: 0.45,
    metalness: 0.1,
    side: THREE.DoubleSide,
  });

  const crownLineMat = new THREE.LineBasicMaterial({
    color: 0xd8cebf,
    linewidth: 1.5,
  });

  const cornerLineMat = new THREE.LineBasicMaterial({
    color: 0xc8bcab,
    linewidth: 1.5,
  });

  for (let i = 0; i < numPts; i++) {
    const p1 = pts[i];
    const p2 = pts[(i + 1) % numPts];

    const dx = p2[0] - p1[0];
    const dz = p2[1] - p1[1];
    const segLen = Math.sqrt(dx * dx + dz * dz);
    if (segLen < 0.05) continue;

    // Normal vector pointing outward
    const nx = -dz / segLen;
    const nz = dx / segLen;

    // Midpoint Z of this wall segment
    const midZ = (p1[1] + p2[1]) / 2;

    // Determine if this wall is facing the front/camera in dollhouse view
    // (Walls on the positive Z side or with positive normal Z face the viewer)
    const isFrontWall = cutawayFront && (midZ > centerZ + bounds.sizeZ * 0.1 || nz > 0.4);
    const thisWallHeight = isFrontWall ? 1.05 : wallHeight;

    // A. Wall Quad
    const wallGeom = new THREE.BufferGeometry();
    const positions = new Float32Array([
      p1[0], 0, p1[1],
      p2[0], 0, p2[1],
      p2[0], thisWallHeight, p2[1],
      p1[0], thisWallHeight, p1[1],
    ]);
    const wallUvs = new Float32Array([
      0, 0,
      segLen * 0.8, 0,
      segLen * 0.8, thisWallHeight * 0.8,
      0, thisWallHeight * 0.8,
    ]);
    const indices = [0, 1, 2, 0, 2, 3];

    wallGeom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    wallGeom.setAttribute("uv", new THREE.BufferAttribute(wallUvs, 2));
    wallGeom.setIndex(indices);
    wallGeom.computeVertexNormals();

    const wallMesh = new THREE.Mesh(wallGeom, isFrontWall ? cutawayMat : wallMat);
    wallMesh.castShadow = true;
    wallMesh.receiveShadow = true;
    group.add(wallMesh);

    // B. Baseboard Molding (0.12m tall along bottom)
    const baseH = 0.12;
    const baseGeom = new THREE.BufferGeometry();
    const bPos = new Float32Array([
      p1[0], 0, p1[1],
      p2[0], 0, p2[1],
      p2[0], baseH, p2[1],
      p1[0], baseH, p1[1],
    ]);
    baseGeom.setAttribute("position", new THREE.BufferAttribute(bPos, 3));
    baseGeom.setIndex([0, 1, 2, 0, 2, 3]);
    baseGeom.computeVertexNormals();

    const baseMesh = new THREE.Mesh(baseGeom, baseboardMat);
    // Subtle normal push to avoid z-fighting
    baseMesh.position.set(nx * 0.004, 0, nz * 0.004);
    group.add(baseMesh);

    // C. Crown / Top Trim Line
    const crownPts = [
      new THREE.Vector3(p1[0], thisWallHeight, p1[1]),
      new THREE.Vector3(p2[0], thisWallHeight, p2[1]),
    ];
    const crownGeom = new THREE.BufferGeometry().setFromPoints(crownPts);
    group.add(new THREE.Line(crownGeom, crownLineMat));

    // D. Corner Post (Vertical line at corner)
    const cornerPts = [
      new THREE.Vector3(p1[0], 0, p1[1]),
      new THREE.Vector3(p1[0], thisWallHeight, p1[1]),
    ];
    const cornerGeom = new THREE.BufferGeometry().setFromPoints(cornerPts);
    group.add(new THREE.Line(cornerGeom, cornerLineMat));
  }

  // 3. Usable Floor Clearance Area (SAT Inset Boundary)
  // Subtle amber dashed-like boundary showing free floor space
  const insetFactor = 0.35; // 35cm wall buffer
  const insetPts: THREE.Vector3[] = [];
  for (let i = 0; i < numPts; i++) {
    const p = pts[i];
    // Vector towards center
    const toCenterX = centerX - p[0];
    const toCenterZ = centerZ - p[1];
    const dist = Math.sqrt(toCenterX * toCenterX + toCenterZ * toCenterZ);
    if (dist > 0.001) {
      const shift = Math.min(insetFactor, dist * 0.25);
      insetPts.push(
        new THREE.Vector3(
          p[0] + (toCenterX / dist) * shift,
          0.006,
          p[1] + (toCenterZ / dist) * shift
        )
      );
    }
  }
  if (insetPts.length >= 3) {
    insetPts.push(insetPts[0].clone());
    const usableGeom = new THREE.BufferGeometry().setFromPoints(insetPts);
    const usableMat = new THREE.LineBasicMaterial({
      color: 0xe07a5f,
      linewidth: 1.5,
      transparent: true,
      opacity: 0.65,
    });
    group.add(new THREE.Line(usableGeom, usableMat));
  }

  // 4. Architectural Dimension Annotations
  if (showDimensions && room) {
    const lVal = room.length.toFixed(1);
    const wVal = room.width.toFixed(1);
    const areaVal = room.floor_area.toFixed(1);

    // Dimension badge along width (top/back wall)
    const widthSprite = makeTextSprite(`Width: ${wVal}m`);
    widthSprite.position.set(centerX, 0.2, bounds.minZ - 0.45);
    widthSprite.scale.set(0.85, 0.42, 1);
    group.add(widthSprite);

    // Dimension badge along length (left wall)
    const lengthSprite = makeTextSprite(`Length: ${lVal}m`);
    lengthSprite.position.set(bounds.minX - 0.45, 0.2, centerZ);
    lengthSprite.scale.set(0.85, 0.42, 1);
    group.add(lengthSprite);

    // Area badge in center floor
    const areaSprite = makeTextSprite(`${areaVal} m² Floor Area`);
    areaSprite.position.set(centerX, 0.08, centerZ);
    areaSprite.scale.set(0.9, 0.45, 1);
    group.add(areaSprite);
  }

  return group;
}
