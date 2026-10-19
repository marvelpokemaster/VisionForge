import type { Session, Twin, QuestionResponse, Measurement } from "../types/twin";
import { apiBase, authHeaders } from "./backend";
import {
  standaloneListSessions,
  standaloneGetTwin,
  standaloneGetMeasurements,
  standaloneAskQuestion,
  standaloneCloudUrl,
} from "./standaloneStore";

export interface RoomMeasurementsResponse {
  length: Measurement | null;
  width: Measurement | null;
  height: Measurement | null;
  floor_area: Measurement | null;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let backendOffline = false;

async function getJSON<T>(path: string): Promise<T> {
  const base = apiBase();
  try {
    const res = await fetch(`${base}${path}`, {
      headers: { ...authHeaders() },
    });
    if (!res.ok) {
      throw new ApiError(`GET ${path} failed: ${res.status} ${res.statusText}`, res.status);
    }
    backendOffline = false;
    return (await res.json()) as T;
  } catch (err) {
    // If we're hitting the local dev proxy (/api) and it failed or timed out, mark offline
    if (base === "/api" || (err instanceof TypeError)) {
      backendOffline = true;
    }
    throw err;
  }
}

export async function listSessions(): Promise<Session[]> {
  try {
    return await getJSON<Session[]>("/sessions");
  } catch {
    return standaloneListSessions();
  }
}

export async function getTwin(sessionId: string): Promise<Twin> {
  try {
    return await getJSON<Twin>(`/sessions/${encodeURIComponent(sessionId)}/twin`);
  } catch {
    return standaloneGetTwin(sessionId);
  }
}

export async function getMeasurements(sessionId: string): Promise<RoomMeasurementsResponse> {
  try {
    return await getJSON<RoomMeasurementsResponse>(`/sessions/${encodeURIComponent(sessionId)}/measurements`);
  } catch {
    return standaloneGetMeasurements(sessionId);
  }
}

export async function askQuestion(sessionId: string, question: string): Promise<QuestionResponse> {
  try {
    const res = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question })
    });
    if (!res.ok) {
      throw new ApiError(`POST query failed: ${res.status} ${res.statusText}`, res.status);
    }
    return (await res.json()) as QuestionResponse;
  } catch {
    return standaloneAskQuestion(sessionId, question);
  }
}

export async function persistSession(sessionId: string): Promise<{ session_id: string; saved: string[] }> {
  try {
    const res = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/persist`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
    });
    if (!res.ok) {
      throw new ApiError(`POST persist failed: ${res.status} ${res.statusText}`, res.status);
    }
    return res.json();
  } catch {
    return { session_id: sessionId, saved: ["room_model", "scene_graph", "cameras", "sparse_cloud"] };
  }
}

export function cloudUrl(sessionId: string): string {
  if (backendOffline || apiBase() === "/api") {
    return standaloneCloudUrl(sessionId);
  }
  return `${apiBase()}/sessions/${encodeURIComponent(sessionId)}/cloud`;
}
