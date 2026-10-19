// Minimal hash router: "#/live" is the live screen, "#/session/<id>" selects a
// session, anything else is the default session view. Hash-based so it works
// both on the Vite dev server and inside Capacitor's local file server, where a
// path like "/live" would not resolve to index.html. The bare "/live" path is
// accepted too (Vite falls back to index.html for it).
export type Route = { kind: "home" } | { kind: "session"; id: string } | { kind: "live" };

export function parseRoute(hash: string, pathname = "/"): Route {
  const h = hash.replace(/^#/, "").replace(/\/+$/, "");
  if (h === "/live" || (h === "" && pathname.replace(/\/+$/, "") === "/live")) return { kind: "live" };
  const m = h.match(/^\/session\/(.+)$/);
  if (m) return { kind: "session", id: decodeURIComponent(m[1]) };
  return { kind: "home" };
}

export function routeHash(route: Route): string {
  switch (route.kind) {
    case "live":
      return "#/live";
    case "session":
      return `#/session/${encodeURIComponent(route.id)}`;
    default:
      return "#/";
  }
}

export function navigate(route: Route): void {
  window.location.hash = routeHash(route);
}
