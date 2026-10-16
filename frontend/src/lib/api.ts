import type { Session, Twin, QuestionResponse, Measurement } from "../types/twin";
import { apiBase } from "./backend";

export interface RoomMeasurementsResponse {
  length: Measurement | null;
  width: Measurement | null;
  height: Measurement | null;
  floor_area: Measurement | null;
}

// The base URL is read per call from lib/backend.ts (build default from
// VITE_API_BASE_URL -- "/api" proxied by Vite in dev, the PC's URL in the
// Android build -- or the runtime "Backend" override kept in localStorage).
// Never cache it in a module constant: the user can change it at any time.

/** A non-2xx reply, with the status so callers can treat a 404 differently. */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) {
    throw new ApiError(`GET ${path} failed: ${res.status} ${res.statusText}`, res.status);
  }
  return (await res.json()) as T;
}

export function listSessions(): Promise<Session[]> {
  return getJSON<Session[]>("/sessions");
}

export function getTwin(sessionId: string): Promise<Twin> {
  return getJSON<Twin>(`/sessions/${encodeURIComponent(sessionId)}/twin`);
}

export function getMeasurements(sessionId: string): Promise<RoomMeasurementsResponse> {
  return getJSON<RoomMeasurementsResponse>(`/sessions/${encodeURIComponent(sessionId)}/measurements`);
}

export async function askQuestion(sessionId: string, question: string): Promise<QuestionResponse> {
  const res = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });
  if (!res.ok) {
    throw new ApiError(`POST query failed: ${res.status} ${res.statusText}`, res.status);
  }
  return (await res.json()) as QuestionResponse;
}

export function cloudUrl(sessionId: string): string {
  return `${apiBase()}/sessions/${encodeURIComponent(sessionId)}/cloud`;
}
