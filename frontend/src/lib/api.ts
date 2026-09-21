import type { Session, Twin, QuestionResponse, Measurement } from "../types/twin";

export interface RoomMeasurementsResponse {
  length: Measurement | null;
  width: Measurement | null;
  height: Measurement | null;
  floor_area: Measurement | null;
}

// Always same-origin "/api/...", proxied by Vite's dev server (see
// vite.config.ts) to the FastAPI backend -- the frontend never hardcodes a
// host, per the task requirement.
const API_BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
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
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });
  if (!res.ok) {
    throw new Error(`POST query failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as QuestionResponse;
}

export function cloudUrl(sessionId: string): string {
  return `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/cloud`;
}
