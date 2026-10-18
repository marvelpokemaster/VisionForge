// The ONE place the backend base URL comes from. Everything that talks to the
// backend -- REST in lib/api.ts, the live WebSocket / live cloud in
// live/wsUrl.ts, the PLY loader in Viewer3D -- calls apiBase().
//
//   default:  VITE_API_BASE_URL at build time ("/api" on the Vite dev server,
//             http://<PC>:8000 in the Android build, see .env.production)
//   override: the "Backend" field on the Live screen / sessions sidebar, kept
//             in localStorage so switching emulator (10.0.2.2) <-> phone
//             (PC LAN IP) needs no rebuild.
//
// localStorage access is wrapped in try/catch throughout: it can be absent
// (node tests), throw (private mode / blocked site data) or be read-only.

export const DEFAULT_API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "https://visionforge-spatial-api.onrender.com";
export const STORAGE_KEY = "visionforge.apiBase";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function defaultStorage(): StorageLike | null {
  try {
    const s = (globalThis as { localStorage?: StorageLike }).localStorage;
    return s ?? null;
  } catch {
    return null;
  }
}

/** Trim and drop trailing slashes; "" / whitespace means "no override". */
export function normalizeApiBase(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined) return null;
  const v = raw.trim().replace(/\/+$/, "");
  return v === "" ? null : v;
}

/** Something a phone user can fix before Start: a usable override is an
 * absolute http(s) URL or a site-relative path. Returns the problem, or null. */
export function validateApiBase(raw: string): string | null {
  const v = normalizeApiBase(raw);
  if (v === null) return null;
  if (/^https?:\/\/[^/\s]+/i.test(v) || v.startsWith("/")) return null;
  return `"${v}" is not an http(s) URL; expected e.g. http://<server-ip>:8000`;
}

/** The stored override, or null when none / unreadable. */
export function readApiBaseOverride(storage: StorageLike | null = defaultStorage()): string | null {
  if (!storage) return null;
  try {
    const raw = normalizeApiBase(storage.getItem(STORAGE_KEY));
    if (!raw) return null;
    // On production builds, ignore obsolete localhost/emulator hostnames
    if (import.meta.env.PROD && /^https?:\/\/(localhost|127\.0\.0\.1|10\.0\.2\.2)(:\d+)?(\/|$)/i.test(raw)) {
      return null;
    }
    return raw;
  } catch {
    return null;
  }
}

/** The effective base: the override when set, otherwise the build default. */
export function apiBase(storage: StorageLike | null = defaultStorage(), fallback: string = DEFAULT_API_BASE): string {
  return readApiBaseOverride(storage) ?? normalizeApiBase(fallback) ?? "/api";
}

const listeners = new Set<() => void>();

/** Persist (or clear, with null / "") the override; returns the new effective
 * base. Listeners (useApiBase) are notified even when storage is unavailable,
 * so the UI always reflects what the code will use. */
export function setApiBaseOverride(raw: string | null, storage: StorageLike | null = defaultStorage()): string {
  const v = normalizeApiBase(raw);
  if (storage) {
    try {
      if (v === null) storage.removeItem(STORAGE_KEY);
      else storage.setItem(STORAGE_KEY, v);
    } catch {
      // read-only / quota / private mode: keep going with the default
    }
  }
  for (const l of listeners) l();
  return apiBase(storage);
}

export function subscribeApiBase(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export type ProbeResult =
  | { ok: true; sessions: number; ms: number; authRequired?: boolean }
  | { ok: false; error: string; ms: number };

/** GET <base>/sessions with a timeout: "can this device reach the backend at all?" */
export async function probeBackend(
  base: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 5000,
  now: () => number = () => Date.now(),
  storage: StorageLike | null = defaultStorage()
): Promise<ProbeResult> {
  const t0 = now();
  const ctl = typeof AbortController === "function" ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  try {
    const headers = { ...authHeaders(storage) };
    const res = await fetchImpl(`${base}/sessions`, {
      ...(ctl ? { signal: ctl.signal } : {}),
      headers,
    });
    // In production with VISIONFORGE_REQUIRE_AUTH=1, 401 proves the server is reached and live
    if (res.status === 401) {
      return { ok: true, sessions: 0, ms: now() - t0, authRequired: true };
    }
    if (!res.ok) return { ok: false, error: `GET /sessions -> ${res.status} ${res.statusText}`.trim(), ms: now() - t0 };
    const body: unknown = await res.json();
    const sessions = Array.isArray(body) ? body.length : 0;
    return { ok: true, sessions, ms: now() - t0 };
  } catch (err) {
    const aborted = err instanceof Error && err.name === "AbortError";
    const error = aborted
      ? `no answer within ${timeoutMs / 1000} s (wrong IP, firewall, or backend not on 0.0.0.0?)`
      : err instanceof Error
        ? err.message
        : String(err);
    return { ok: false, error, ms: now() - t0 };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export const AUTH_TOKEN_KEY = "visionforge.authToken";

export function readAuthToken(storage: StorageLike | null = defaultStorage()): string | null {
  if (!storage) return null;
  try {
    return normalizeApiBase(storage.getItem(AUTH_TOKEN_KEY));
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null, storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    if (!token || token.trim() === "") storage.removeItem(AUTH_TOKEN_KEY);
    else storage.setItem(AUTH_TOKEN_KEY, token.trim());
  } catch {
    // ignore
  }
}

export function authHeaders(storage: StorageLike | null = defaultStorage()): Record<string, string> {
  const token = readAuthToken(storage);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

