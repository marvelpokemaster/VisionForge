// Loading a session for the session view: the twin FIRST (it is always there
// for a registered session, even a failed one -- its provenance.stage_status
// says what happened), THEN the measurements, which 404 whenever there is no
// scene_graph.json, i.e. for every session whose geometry stage never ran.
// Before this the two were awaited together and a failed live session showed
// "GET .../measurements failed: 404" instead of the twin.
import type { Twin } from "../types/twin";
import { ApiError, type RoomMeasurementsResponse } from "./api";

export interface SessionLoaders {
  getTwin(sessionId: string): Promise<Twin>;
  getMeasurements(sessionId: string): Promise<RoomMeasurementsResponse>;
}

export interface SessionView {
  twin: Twin;
  measurements: RoomMeasurementsResponse | null;
  /** Why there is nothing to draw / measure, when there is not; null otherwise. */
  notice: string | null;
}

export function hasGeometry(twin: Twin): boolean {
  return twin.room_model !== null && twin.room_model.planes.length > 0;
}

/** The honest one-liner for a twin with no planes, from its stage_status. */
export function noGeometryNotice(twin: Twin): string | null {
  if (hasGeometry(twin)) return null;
  const status = twin.provenance.stage_status ?? {};
  if (status.live_tracking === "failed") return "no geometry: live tracking failed (never initialised)";
  const failed = Object.entries(status)
    .filter(([, v]) => v === "failed")
    .map(([k]) => k);
  if (failed.length > 0) return `no geometry: ${failed.join(", ")} failed`;
  const running = Object.entries(status)
    .filter(([, v]) => v === "running")
    .map(([k]) => k);
  if (running.length > 0) return `no geometry yet: ${running.join(", ")} still running`;
  return "no geometry: this session has no room model";
}

export async function loadSessionView(sessionId: string, loaders: SessionLoaders): Promise<SessionView> {
  const twin = await loaders.getTwin(sessionId); // a failure here IS an error: nothing to show
  let measurements: RoomMeasurementsResponse | null;
  try {
    measurements = await loaders.getMeasurements(sessionId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      measurements = null; // expected whenever the geometry stage never produced a scene graph
    } else {
      throw err;
    }
  }
  const notice = noGeometryNotice(twin) ?? (measurements === null ? "measurements not available for this session" : null);
  return { twin, measurements, notice };
}
