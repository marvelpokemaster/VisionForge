import { apiBase, authHeaders } from "./backend";
import type { FurnitureCatalogItem, PlacedFurniture, AutoPackResult } from "../types/furniture";

export async function fetchFurnitureCatalog(): Promise<Record<string, FurnitureCatalogItem>> {
  const res = await fetch(`${apiBase()}/furniture/catalog`, {
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch furniture catalog: ${res.statusText}`);
  }
  return res.json();
}

export async function validateFurniturePlacement(
  sessionId: string,
  item: {
    furniture_id: string;
    center_x: number;
    center_z: number;
    angle_deg: number;
    custom_length?: number;
    custom_width?: number;
  },
  placedItems: PlacedFurniture[] = []
): Promise<{ valid: boolean; reason: string; corners: number[][] }> {
  const res = await fetch(`${apiBase()}/sessions/${sessionId}/furniture/validate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      furniture_id: item.furniture_id,
      center_x: item.center_x,
      center_z: item.center_z,
      angle_deg: item.angle_deg,
      placed_items: placedItems.map((p) => ({
        id: p.id,
        furniture_id: p.furniture_id,
        center_x: p.center_x,
        center_z: p.center_z,
        angle_deg: p.angle_deg,
        custom_length: p.length,
        custom_width: p.width,
        custom_height: p.height,
      })),
      custom_length: item.custom_length,
      custom_width: item.custom_width,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Validation request failed: ${res.statusText}`);
  }
  return res.json();
}

export async function autoPackFurniture(
  sessionId: string,
  furnitureId: string,
  spacing = 0.2,
  maxItems = 30
): Promise<AutoPackResult> {
  const res = await fetch(`${apiBase()}/sessions/${sessionId}/furniture/auto_pack`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      furniture_id: furnitureId,
      spacing,
      max_items: maxItems,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Auto pack request failed: ${res.statusText}`);
  }
  return res.json();
}

export async function calibrateScale(
  sessionId: string,
  referenceType: "room_width" | "room_length",
  knownDistanceMeters: number
): Promise<{ success: boolean; scale: any; room: any }> {
  const res = await fetch(`${apiBase()}/sessions/${sessionId}/scale/calibrate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({
      reference_type: referenceType,
      known_distance_meters: knownDistanceMeters,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Calibration failed: ${res.statusText}`);
  }
  return res.json();
}

export interface PersistedFurnitureLayout {
  placed_items: Array<{
    id: string;
    furniture_id: string;
    name?: string;
    center_x: number;
    center_z: number;
    angle_deg: number;
    custom_length?: number;
    custom_width?: number;
    custom_height?: number;
    color?: string;
    valid?: boolean;
    reason?: string;
  }>;
  pack_spacing?: number;
}

export async function saveFurnitureLayout(
  sessionId: string,
  placedItems: PlacedFurniture[],
  packSpacing: number = 0.2
): Promise<{ status: string; session_id: string }> {
  const payload: PersistedFurnitureLayout = {
    placed_items: placedItems.map((p) => ({
      id: p.id,
      furniture_id: p.furniture_id,
      name: p.name,
      center_x: p.center_x,
      center_z: p.center_z,
      angle_deg: p.angle_deg,
      custom_length: p.length,
      custom_width: p.width,
      custom_height: p.height,
      color: p.color,
      valid: p.valid,
      reason: p.reason,
    })),
    pack_spacing: packSpacing,
  };

  const res = await fetch(`${apiBase()}/sessions/${sessionId}/furniture/layout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Save layout failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchFurnitureLayout(
  sessionId: string
): Promise<{ placedItems: PlacedFurniture[]; packSpacing: number } | null> {
  const res = await fetch(`${apiBase()}/sessions/${sessionId}/furniture/layout`, {
    headers: {
      ...authHeaders(),
    },
  });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Fetch layout failed: ${res.statusText}`);
  }
  const data = await res.json();
  const rawItems = data.placed_items || [];
  const placedItems: PlacedFurniture[] = rawItems.map((item: any) => ({
    id: item.id || `furniture_${Date.now()}_${Math.random()}`,
    furniture_id: item.furniture_id || "bed_queen",
    name: item.name || item.furniture_id || "Furniture",
    center_x: item.center_x ?? 0.0,
    center_z: item.center_z ?? 0.0,
    angle_deg: item.angle_deg ?? 0.0,
    length: item.custom_length ?? item.length ?? 1.0,
    width: item.custom_width ?? item.width ?? 1.0,
    height: item.custom_height ?? item.height ?? 0.8,
    color: item.color || "#3b82f6",
    valid: item.valid ?? true,
    reason: item.reason || "Loaded from saved layout",
  }));
  return {
    placedItems,
    packSpacing: data.pack_spacing ?? 0.2,
  };
}
