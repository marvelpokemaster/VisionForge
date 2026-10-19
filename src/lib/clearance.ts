import type { FurnitureCatalogItem, PlacedFurniture, AutoPackResult } from "../types/furniture";
import type { RoomModel } from "../types/twin";

export const FURNITURE_CATALOG: Record<string, FurnitureCatalogItem> = {
  bed_queen: {
    id: "bed_queen",
    name: "Queen Bed",
    category: "bedroom",
    length: 2.1,
    width: 1.6,
    height: 0.9,
    color: "#3b82f6",
  },
  bed_single: {
    id: "bed_single",
    name: "Single Bed",
    category: "bedroom",
    length: 2.0,
    width: 1.0,
    height: 0.8,
    color: "#60a5fa",
  },
  sofa_3seater: {
    id: "sofa_3seater",
    name: "3-Seater Sofa",
    category: "living",
    length: 2.2,
    width: 0.9,
    height: 0.85,
    color: "#10b981",
  },
  sofa_2seater: {
    id: "sofa_2seater",
    name: "2-Seater Sofa",
    category: "living",
    length: 1.5,
    width: 0.85,
    height: 0.85,
    color: "#34d399",
  },
  work_desk: {
    id: "work_desk",
    name: "Work Desk",
    category: "office",
    length: 1.4,
    width: 0.7,
    height: 0.75,
    color: "#f59e0b",
  },
  dining_table: {
    id: "dining_table",
    name: "Dining Table",
    category: "dining",
    length: 1.6,
    width: 0.9,
    height: 0.75,
    color: "#8b5cf6",
  },
  wardrobe: {
    id: "wardrobe",
    name: "Wardrobe",
    category: "bedroom",
    length: 1.2,
    width: 0.6,
    height: 2.0,
    color: "#6b7280",
  },
  nightstand: {
    id: "nightstand",
    name: "Nightstand",
    category: "bedroom",
    length: 0.5,
    width: 0.5,
    height: 0.55,
    color: "#9ca3af",
  },
};

/** Get the 4 corners of an oriented bounding box on the floor (X-Z plane). */
export function getOrientedBoxCorners(
  cx: number,
  cz: number,
  length: number,
  width: number,
  angleDeg = 0.0
): number[][] {
  const rad = (angleDeg * Math.PI) / 180.0;
  const cosA = Math.cos(rad);
  const sinA = Math.sin(rad);

  const hx = length / 2.0;
  const hz = width / 2.0;

  const localCorners: [number, number][] = [
    [-hx, -hz],
    [hx, -hz],
    [hx, hz],
    [-hx, hz],
  ];

  return localCorners.map(([lx, lz]) => [
    cx + lx * cosA - lz * sinA,
    cz + lx * sinA + lz * cosA,
  ]);
}

/** Classical ray-casting point-in-polygon test. */
export function pointInPolygon2D(pt: [number, number], polygon: number[][]): boolean {
  if (polygon.length < 3) return false;
  const [x, y] = pt;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    const intersect = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

/** Check if two 2D line segments intersect. */
function segmentsIntersect(
  p1: [number, number],
  p2: [number, number],
  p3: [number, number],
  p4: [number, number]
): boolean {
  const ccw = (a: [number, number], b: [number, number], c: [number, number]) =>
    (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0]);

  return (
    ccw(p1, p3, p4) !== ccw(p2, p3, p4) &&
    ccw(p1, p2, p3) !== ccw(p1, p2, p4)
  );
}

/** Separating Axis Theorem (SAT) for convex 2D polygons. */
export function polygonsIntersect(polyA: number[][], polyB: number[][]): boolean {
  const polys = [polyA, polyB];

  for (let i = 0; i < polys.length; i++) {
    const polygon = polys[i];
    for (let i1 = 0; i1 < polygon.length; i1++) {
      const i2 = (i1 + 1) % polygon.length;
      const p1 = polygon[i1];
      const p2 = polygon[i2];

      const normal = [-(p2[1] - p1[1]), p2[0] - p1[0]];

      let minA = Infinity;
      let maxA = -Infinity;
      for (const p of polyA) {
        const projected = normal[0] * p[0] + normal[1] * p[1];
        if (projected < minA) minA = projected;
        if (projected > maxA) maxA = projected;
      }

      let minB = Infinity;
      let maxB = -Infinity;
      for (const p of polyB) {
        const projected = normal[0] * p[0] + normal[1] * p[1];
        if (projected < minB) minB = projected;
        if (projected > maxB) maxB = projected;
      }

      if (maxA < minB || maxB < minA) {
        return false;
      }
    }
  }

  return true;
}

/** Check if an oriented bounding box fits entirely within a room polygon without colliding with boundaries. */
export function validatePlacementGeometry(
  roomModel: RoomModel,
  item: {
    furniture_id: string;
    center_x: number;
    center_z: number;
    angle_deg?: number;
    custom_length?: number;
    custom_width?: number;
  },
  placedItems: PlacedFurniture[] = []
): { valid: boolean; reason: string; corners: number[][] } {
  const cat = FURNITURE_CATALOG[item.furniture_id];
  const length = item.custom_length ?? (cat ? cat.length : 1.0);
  const width = item.custom_width ?? (cat ? cat.width : 1.0);
  const angle = item.angle_deg ?? 0.0;

  const corners = getOrientedBoxCorners(item.center_x, item.center_z, length, width, angle);

  const boundingPoly = roomModel.room?.bounding_polygon_room;
  if (!boundingPoly || boundingPoly.length < 3) {
    const rL = roomModel.room?.length ?? 5.0;
    const rW = roomModel.room?.width ?? 4.0;
    const hx = rL / 2;
    const hz = rW / 2;
    for (const c of corners) {
      if (Math.abs(c[0]) > hx || Math.abs(c[1]) > hz) {
        return {
          valid: false,
          reason: `Item extends outside room dimensions (${rL.toFixed(1)}m x ${rW.toFixed(1)}m)`,
          corners,
        };
      }
    }
  } else {
    for (const c of corners) {
      if (!pointInPolygon2D([c[0], c[1]], boundingPoly)) {
        return {
          valid: false,
          reason: "Part of furniture extends outside room boundary polygon",
          corners,
        };
      }
    }

    for (let i = 0; i < corners.length; i++) {
      const c1: [number, number] = [corners[i][0], corners[i][1]];
      const c2: [number, number] = [
        corners[(i + 1) % corners.length][0],
        corners[(i + 1) % corners.length][1],
      ];
      for (let j = 0; j < boundingPoly.length; j++) {
        const w1: [number, number] = [boundingPoly[j][0], boundingPoly[j][1]];
        const w2: [number, number] = [
          boundingPoly[(j + 1) % boundingPoly.length][0],
          boundingPoly[(j + 1) % boundingPoly.length][1],
        ];
        if (segmentsIntersect(c1, c2, w1, w2)) {
          return {
            valid: false,
            reason: "Furniture edge intersects with room wall boundary",
            corners,
          };
        }
      }
    }
  }

  for (const other of placedItems) {
    const oLength = other.length ?? 1.0;
    const oWidth = other.width ?? 1.0;
    const oCorners = getOrientedBoxCorners(
      other.center_x,
      other.center_z,
      oLength,
      oWidth,
      other.angle_deg ?? 0.0
    );
    if (polygonsIntersect(corners, oCorners)) {
      return {
        valid: false,
        reason: `Collides with existing furniture item '${other.name ?? other.furniture_id}'`,
        corners,
      };
    }
  }

  return {
    valid: true,
    reason: "Valid placement within clearance boundary",
    corners,
  };
}

/** Auto-pack candidate furniture into usable floor space. */
export function autoPackGeometry(
  roomModel: RoomModel,
  furnitureId: string,
  spacing = 0.3,
  maxItems = 30,
  customLength?: number,
  customWidth?: number
): AutoPackResult {
  const cat = FURNITURE_CATALOG[furnitureId];
  const length = customLength ?? (cat ? cat.length : 1.0);
  const width = customWidth ?? (cat ? cat.width : 1.0);
  const height = cat ? cat.height : 0.8;

  const boundingPoly = roomModel.room?.bounding_polygon_room;
  let minX = -2.0, maxX = 2.0, minZ = -2.0, maxZ = 2.0;

  if (boundingPoly && boundingPoly.length >= 3) {
    minX = Math.min(...boundingPoly.map((p) => p[0]));
    maxX = Math.max(...boundingPoly.map((p) => p[0]));
    minZ = Math.min(...boundingPoly.map((p) => p[1]));
    maxZ = Math.max(...boundingPoly.map((p) => p[1]));
  } else {
    const rL = (roomModel.room?.length ?? 4.0) / 2;
    const rW = (roomModel.room?.width ?? 3.5) / 2;
    minX = -rL; maxX = rL;
    minZ = -rW; maxZ = rW;
  }

  const stepX = length + spacing;
  const stepZ = width + spacing;

  const packed: PlacedFurniture[] = [];

  for (let x = minX + length / 2 + 0.1; x + length / 2 <= maxX - 0.1; x += stepX) {
    for (let z = minZ + width / 2 + 0.1; z + width / 2 <= maxZ - 0.1; z += stepZ) {
      if (packed.length >= maxItems) break;

      const check = validatePlacementGeometry(
        roomModel,
        {
          furniture_id: furnitureId,
          center_x: x,
          center_z: z,
          angle_deg: 0,
          custom_length: length,
          custom_width: width,
        },
        packed
      );

      if (check.valid) {
        packed.push({
          id: `autopack_${furnitureId}_${packed.length + 1}`,
          furniture_id: furnitureId,
          name: `${cat?.name ?? furnitureId} #${packed.length + 1}`,
          center_x: Number(x.toFixed(3)),
          center_z: Number(z.toFixed(3)),
          angle_deg: 0,
          length,
          width,
          height,
          color: cat?.color ?? "#3b82f6",
          valid: true,
          reason: "Auto-packed in clearance zone",
        });
      }
    }
  }

  const roomArea = roomModel.room?.floor_area ?? (maxX - minX) * (maxZ - minZ);
  const packedArea = packed.length * (length * width);
  const efficiency = roomArea > 0 ? (packedArea / roomArea) * 100 : 0;

  return {
    furniture_id: furnitureId,
    furniture_name: cat?.name ?? furnitureId,
    unit_dimensions: {
      length,
      width,
      height,
    },
    max_count: packed.length,
    placements: packed.map((p) => ({
      id: p.id,
      furniture_id: p.furniture_id,
      center_x: p.center_x,
      center_z: p.center_z,
      angle_deg: p.angle_deg,
      custom_length: length,
      custom_width: width,
      custom_height: height,
    })),
    floor_area_m2: Number(roomArea.toFixed(2)),
    occupied_area_m2: Number(packedArea.toFixed(2)),
    usable_free_area_m2: Number(Math.max(0, roomArea - packedArea).toFixed(2)),
    coverage_ratio: Number((efficiency / 100).toFixed(3)),
  };
}
