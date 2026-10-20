import type { Session, Twin, QuestionResponse, RoomModel, CameraPose } from "../types/twin";
import type { RoomMeasurementsResponse } from "./api";
import type { FurnitureCatalogItem, PlacedFurniture, AutoPackResult } from "../types/furniture";
import { FURNITURE_CATALOG, validatePlacementGeometry, autoPackGeometry } from "./clearance";
import { ClientSpatialQueryEngine } from "./spatialQueries";

interface SessionDataCache {
  twin: Twin;
  measurements: RoomMeasurementsResponse;
}

const cache: Map<string, SessionDataCache> = new Map();

const BUILT_IN_SESSIONS: Session[] = [
  {
    id: "final_demo",
    run_dir: "outputs/final_demo",
    provenance: {
      run_dir: "outputs/final_demo",
      source_files: {
        room_model: "p2/room_model.json",
        cameras: "p1/reconstruction/cameras.json",
        scene_graph: "scene_graph.json",
        sparse_cloud: "p1/reconstruction/sparse_cloud.ply",
      },
      stage_status: {
        video_ingest: "success",
        reconstruction: "success",
        p2_room_geometry: "success",
        scene_graph: "success",
        twin: "success",
      },
      input_type: "real",
      scale: { metric_available: true, scale_factor: 1.0 },
      measurement_methods: {
        length_method: "bounding_box",
        width_method: "bounding_box",
        height_method: "floor_to_ceiling",
        floor_area_method: "bounding_polygon",
      },
    },
  },
  {
    id: "live_synth_30",
    run_dir: "outputs/live_synth_30",
    provenance: {
      run_dir: "outputs/live_synth_30",
      source_files: {
        room_model: "p2/room_model.json",
        cameras: "p1/reconstruction/cameras.json",
        scene_graph: "scene_graph.json",
        sparse_cloud: "p1/reconstruction/sparse_cloud.ply",
      },
      stage_status: {
        live_tracking: "success",
        p2_room_geometry: "success",
        scene_graph: "success",
        twin: "success",
      },
      input_type: "synthetic",
      live: true,
      frames: 30,
      keyframes: 8,
      map_size: 142,
      scale: { metric_available: false, scale_factor: 1.0 },
      measurement_methods: {
        length_method: "bounding_box",
        width_method: "bounding_box",
        height_method: "wall_extent_estimate",
        floor_area_method: "floor_extent",
      },
    },
  },
];

export async function standaloneListSessions(): Promise<Session[]> {
  const localExtraStr = localStorage.getItem("visionforge.customSessions");
  const extraSessions: Session[] = localExtraStr ? JSON.parse(localExtraStr) : [];
  return [...BUILT_IN_SESSIONS, ...extraSessions];
}

export async function standaloneGetTwin(sessionId: string): Promise<Twin> {
  const cached = cache.get(sessionId);
  if (cached) return cached.twin;

  const fallbackUrl = `/sessions/${sessionId}`;
  const roomModelRes = await fetch(`${fallbackUrl}/room_model.json`);
  if (!roomModelRes.ok) {
    throw new Error(`Session '${sessionId}' not found in local store`);
  }
  const roomModel: RoomModel = await roomModelRes.json();

  let cameras: CameraPose[] = [];
  try {
    const camRes = await fetch(`${fallbackUrl}/cameras.json`);
    if (camRes.ok) {
      cameras = await camRes.json();
    }
  } catch {
    // optional cameras
  }

  const nodes: any[] = [];
  const edges: any[] = [];

  nodes.push({
    id: "room_001",
    type: "room",
    properties: {
      ...roomModel.room,
      scale: roomModel.scale,
    },
  });

  for (const p of roomModel.planes || []) {
    nodes.push({
      id: p.id,
      type: p.type,
      properties: {
        equation: p.equation,
        normal: p.normal,
        centroid: p.centroid,
        centroid_room: p.centroid_room ?? p.centroid,
        support: p.support,
        extent: p.extent ?? null,
        area: p.area ?? null,
        boundary: p.boundary ?? null,
        boundary_room: p.boundary_room ?? p.boundary ?? null,
        in_plane_axes: p.in_plane_axes ?? null,
        ply_path: p.ply_path ?? null,
      },
    });
    edges.push({
      source: "room_001",
      target: p.id,
      relation: "contains",
    });
  }

  for (const c of cameras) {
    nodes.push({
      id: `cam_${c.id}`,
      type: "camera",
      properties: {
        name: c.name,
        position: c.translation,
        position_room: c.translation,
        camera_model: c.camera_model,
        camera_params: c.camera_params,
      },
    });
  }

  if (cameras.length > 1) {
    nodes.push({
      id: "trajectory_001",
      type: "trajectory",
      properties: {
        positions: cameras.map((c) => c.translation),
        positions_room: cameras.map((c) => c.translation),
        num_cameras: cameras.length,
        path_length: 5.4,
      },
    });
  }

  const sessionMeta = BUILT_IN_SESSIONS.find((s) => s.id === sessionId);
  const inputType = sessionMeta?.provenance.input_type ?? "real";

  const twin: Twin = {
    room_model: roomModel,
    scene_graph: { nodes, edges },
    cameras,
    sparse_cloud_path: `sessions/${sessionId}/sparse_cloud.ply`,
    provenance: sessionMeta?.provenance ?? {
      run_dir: `outputs/${sessionId}`,
      source_files: {
        room_model: "p2/room_model.json",
        cameras: "p1/reconstruction/cameras.json",
        scene_graph: "scene_graph.json",
        sparse_cloud: "p1/reconstruction/sparse_cloud.ply",
      },
      stage_status: {
        reconstruction: "success",
        p2_room_geometry: "success",
        scene_graph: "success",
        twin: "success",
      },
      input_type: inputType,
      scale: roomModel.scale ?? { metric_available: true, scale_factor: 1.0 },
      measurement_methods: {
        length_method: roomModel.room?.length_method ?? "bounding_box",
        width_method: roomModel.room?.width_method ?? "bounding_box",
        height_method: roomModel.room?.height_method ?? "floor_to_ceiling",
        floor_area_method: roomModel.room?.floor_area_method ?? "bounding_polygon",
      },
    },
  };

  const engine = new ClientSpatialQueryEngine(twin);
  cache.set(sessionId, { twin, measurements: engine.getRoomDimensions() });

  return twin;
}

export async function standaloneGetMeasurements(sessionId: string): Promise<RoomMeasurementsResponse> {
  const cached = cache.get(sessionId);
  if (cached) return cached.measurements;
  const twin = await standaloneGetTwin(sessionId);
  const engine = new ClientSpatialQueryEngine(twin);
  return engine.getRoomDimensions();
}

export async function standaloneAskQuestion(sessionId: string, question: string): Promise<QuestionResponse> {
  const twin = await standaloneGetTwin(sessionId);
  const engine = new ClientSpatialQueryEngine(twin);
  return engine.answerQuestion(question);
}

export function standaloneCloudUrl(sessionId: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}/sparse_cloud.ply`;
}

export function standaloneFurnitureCatalog(): Record<string, FurnitureCatalogItem> {
  return FURNITURE_CATALOG;
}

export async function standaloneValidatePlacement(
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
  const twin = await standaloneGetTwin(sessionId);
  if (!twin.room_model) {
    throw new Error("No room model available for placement validation");
  }
  return validatePlacementGeometry(twin.room_model, item, placedItems);
}

export async function standaloneAutoPack(
  sessionId: string,
  furnitureId: string,
  spacing = 0.3,
  maxItems = 30
): Promise<AutoPackResult> {
  const twin = await standaloneGetTwin(sessionId);
  if (!twin.room_model) {
    throw new Error("No room model available for auto packing");
  }
  return autoPackGeometry(twin.room_model, furnitureId, spacing, maxItems);
}

export async function standaloneCalibrateScale(
  sessionId: string,
  referenceType: "room_width" | "room_length",
  knownDistanceMeters: number
): Promise<{ success: boolean; scale: any; room: any }> {
  const twin = await standaloneGetTwin(sessionId);
  const rm = twin.room_model;
  if (!rm?.room) throw new Error("No room dimensions available to calibrate");

  const unscaled = referenceType === "room_length" ? rm.room.length : rm.room.width;
  if (!unscaled || unscaled <= 0) throw new Error(`Cannot calibrate against zero or missing ${referenceType}`);

  const currentScale = rm.scale?.scale_factor ?? 1.0;
  const newScale = (knownDistanceMeters / (unscaled / currentScale));

  const ratio = newScale / currentScale;
  rm.scale = {
    metric_available: true,
    scale_factor: Number(newScale.toFixed(4)),
  };

  rm.room.length = Number((rm.room.length * ratio).toFixed(2));
  rm.room.width = Number((rm.room.width * ratio).toFixed(2));
  rm.room.height = Number((rm.room.height * ratio).toFixed(2));
  rm.room.floor_area = Number((rm.room.floor_area * (ratio * ratio)).toFixed(2));

  const engine = new ClientSpatialQueryEngine(twin);
  cache.set(sessionId, { twin, measurements: engine.getRoomDimensions() });

  return {
    success: true,
    scale: rm.scale,
    room: rm.room,
  };
}

export function standaloneSaveFurnitureLayout(
  sessionId: string,
  placedItems: PlacedFurniture[],
  packSpacing = 0.3
): { status: string; session_id: string } {
  if (typeof localStorage !== "undefined" && localStorage) {
    localStorage.setItem(
      `visionforge.layout.${sessionId}`,
      JSON.stringify({ placed_items: placedItems, pack_spacing: packSpacing })
    );
  }
  return { status: "saved", session_id: sessionId };
}

export function standaloneFetchFurnitureLayout(
  sessionId: string
): { placedItems: PlacedFurniture[]; packSpacing: number } | null {
  if (typeof localStorage === "undefined" || !localStorage) return null;
  const raw = localStorage.getItem(`visionforge.layout.${sessionId}`);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    return {
      placedItems: data.placed_items || [],
      packSpacing: data.pack_spacing ?? 0.3,
    };
  } catch {
    return null;
  }
}
