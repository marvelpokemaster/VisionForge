// Folds the per-frame status messages of WS /live/{id} (docs/live_tracking.md
// §9) into one summary for the live screen. Pure.
import type { Twin } from "../types/twin";

export type TrackState = "INITIALIZING" | "TRACKING" | "LOST";

export interface LivePose {
  rotation_quat: [number, number, number, number];
  translation: [number, number, number];
}

export interface LiveStatusMessage {
  session_id: string;
  frame_index: number;
  state: TrackState;
  n_tracked: number;
  n_inliers: number;
  reprojection_rms: number | null;
  is_keyframe: boolean;
  map_size: number;
  n_keyframes: number;
  segment: number | null;
  n_segments: number;
  frames: number;
  dropped: number;
  source_size: [number, number];
  processed_size: [number, number];
  intrinsics_source: string;
  pose: LivePose | null;
  twin_update: Twin | null;
}

export interface LostEpisode {
  start: number; // frame index of the first LOST status
  end: number | null; // last LOST frame index, null while still lost
}

export interface LiveSummary {
  state: TrackState | "IDLE";
  frameIndex: number | null;
  nTracked: number;
  nInliers: number;
  reprojectionRms: number | null;
  mapSize: number;
  nKeyframes: number;
  segment: number | null;
  lastSegment: number | null; // last non-null segment seen (survives LOST, where segment is null)
  segmentChanges: number; // re-initialisations into a new segment
  dropped: number; // server-side (backpressure)
  skippedClient: number; // frames the pump chose not to send
  fpsMeasured: number | null; // statuses per second, over the last few arrivals
  lastTwin: Twin | null;
  twinUpdates: number;
  lostEpisodes: LostEpisode[];
  frames: number; // frames the server processed
  processedSize: [number, number] | null;
  intrinsicsSource: string | null;
  arrivalsMs: number[]; // internal: recent status arrival times
}

const FPS_WINDOW = 10;

export function initialSummary(): LiveSummary {
  return {
    state: "IDLE",
    frameIndex: null,
    nTracked: 0,
    nInliers: 0,
    reprojectionRms: null,
    mapSize: 0,
    nKeyframes: 0,
    segment: null,
    lastSegment: null,
    segmentChanges: 0,
    dropped: 0,
    skippedClient: 0,
    fpsMeasured: null,
    lastTwin: null,
    twinUpdates: 0,
    lostEpisodes: [],
    frames: 0,
    processedSize: null,
    intrinsicsSource: null,
    arrivalsMs: []
  };
}

/** The twin the viewer should draw: a NEW object only when this message
 * carries a twin_update, otherwise the previous one (same reference, so the
 * viewer's rebuild effect does not fire). */
export function twinForRedraw(prevTwin: Twin | null, msg: Pick<LiveStatusMessage, "twin_update">): Twin | null {
  return msg.twin_update ?? prevTwin;
}

/** "no geometry yet" explanation for a twin whose room model has no planes. */
export function noGeometryReason(twin: Twin | null): string | null {
  if (!twin || !twin.room_model) return null;
  if (twin.room_model.planes.length > 0) return null;
  return twin.provenance.reason ?? "no planes fitted";
}

export function reduceStatus(prev: LiveSummary, msg: LiveStatusMessage, nowMs: number): LiveSummary {
  const arrivals = [...prev.arrivalsMs, nowMs].slice(-FPS_WINDOW);
  let fps: number | null = null;
  if (arrivals.length >= 2) {
    const span = arrivals[arrivals.length - 1] - arrivals[0];
    fps = span > 0 ? ((arrivals.length - 1) * 1000) / span : null;
  }

  const episodes = prev.lostEpisodes.map((e) => ({ ...e }));
  const open = episodes.length > 0 && episodes[episodes.length - 1].end === null ? episodes[episodes.length - 1] : null;
  if (msg.state === "LOST") {
    if (!open) episodes.push({ start: msg.frame_index, end: null });
  } else if (open) {
    open.end = prev.frameIndex ?? msg.frame_index;
  }

  const segmentChanges =
    prev.lastSegment !== null && msg.segment !== null && msg.segment !== prev.lastSegment
      ? prev.segmentChanges + 1
      : prev.segmentChanges;
  const lastSegment = msg.segment ?? prev.lastSegment;

  const lastTwin = twinForRedraw(prev.lastTwin, msg);

  return {
    state: msg.state,
    frameIndex: msg.frame_index,
    nTracked: msg.n_tracked,
    nInliers: msg.n_inliers,
    reprojectionRms: msg.reprojection_rms,
    mapSize: msg.map_size,
    nKeyframes: msg.n_keyframes,
    segment: msg.segment,
    lastSegment,
    segmentChanges,
    dropped: msg.dropped,
    skippedClient: prev.skippedClient,
    fpsMeasured: fps,
    lastTwin,
    twinUpdates: prev.twinUpdates + (msg.twin_update ? 1 : 0),
    lostEpisodes: episodes,
    frames: msg.frames,
    processedSize: msg.processed_size,
    intrinsicsSource: msg.intrinsics_source,
    arrivalsMs: arrivals
  };
}

export function addClientSkips(prev: LiveSummary, n: number): LiveSummary {
  return n === 0 ? prev : { ...prev, skippedClient: prev.skippedClient + n };
}
