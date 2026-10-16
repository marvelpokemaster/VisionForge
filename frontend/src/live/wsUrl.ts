// The live socket must reach the same backend as the REST calls in lib/api.ts,
// so its URL is derived from the SAME base -- apiBase() in lib/backend.ts, the
// one function that knows about the build default and the runtime override.
// An absolute http(s) base becomes ws(s) on the same host/path; a relative
// base (the "/api" that Vite proxies in dev) becomes ws(s)://<current
// host>/api, matching the page's own scheme.
import { apiBase } from "../lib/backend";

export interface LocationLike {
  protocol: string; // "http:" | "https:"
  host: string; // host[:port]
}

export function liveSocketOrigin(apiBase: string, loc: LocationLike): string {
  const base = apiBase.replace(/\/+$/, "");
  if (/^https:\/\//i.test(base)) return "wss://" + base.slice("https://".length);
  if (/^http:\/\//i.test(base)) return "ws://" + base.slice("http://".length);
  if (/^wss?:\/\//i.test(base)) return base;
  const scheme = loc.protocol === "https:" ? "wss" : "ws";
  const path = base === "" ? "" : base.startsWith("/") ? base : "/" + base;
  return `${scheme}://${loc.host}${path}`;
}

export function liveSocketUrl(apiBase: string, sessionId: string, loc: LocationLike): string {
  return `${liveSocketOrigin(apiBase, loc)}/live/${encodeURIComponent(sessionId)}`;
}

/** The active segment's current map, served by GET /live/{id}/cloud. */
export function liveCloudUrl(apiBase: string, sessionId: string): string {
  return `${apiBase.replace(/\/+$/, "")}/live/${encodeURIComponent(sessionId)}/cloud`;
}

/** The two above, against the backend currently in effect (default or the
 * runtime override) -- what the Live screen actually connects to. */
export function currentLiveSocketUrl(sessionId: string, loc: LocationLike): string {
  return liveSocketUrl(apiBase(), sessionId, loc);
}

export function currentLiveCloudUrl(sessionId: string): string {
  return liveCloudUrl(apiBase(), sessionId);
}
