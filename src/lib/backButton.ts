// Browser and mobile hardware/gesture back button handling.
import { navigate, parseRoute, type Route } from "./route";

export type BackAction = { kind: "navigate"; route: Route } | { kind: "exit" } | { kind: "handled" };

/** A screen can claim the next back press (return true) -- the Live screen
 * does while a session is running, turning back into Stop. */
export type BackGuard = () => boolean;

const guards = new Set<BackGuard>();

export function registerBackGuard(guard: BackGuard): () => void {
  guards.add(guard);
  return () => {
    guards.delete(guard);
  };
}

/** Pure: what back does from a route, given the active guards. */
export function resolveBack(route: Route, activeGuards: Iterable<BackGuard> = guards): BackAction {
  for (const g of activeGuards) {
    if (g()) return { kind: "handled" };
  }
  switch (route.kind) {
    case "live":
    case "session":
      return { kind: "navigate", route: { kind: "home" } };
    default:
      return { kind: "exit" };
  }
}

export function handleBack(): BackAction {
  const action = resolveBack(parseRoute(window.location.hash, window.location.pathname));
  if (action.kind === "navigate") navigate(action.route);
  return action;
}

/** Call once at startup. Safely binds popstate in web browsers and handles back button. */
export function installBackButton(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("popstate", () => {
    handleBack();
  });
}
