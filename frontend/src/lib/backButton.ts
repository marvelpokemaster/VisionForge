// Android hardware/gesture back. Without a listener Capacitor falls back to
// WebView.goBack() / finishing the activity, which is how back from the Live
// screen's file picker left the app on the emulator. With a listener on the
// App plugin's `backButton` event Capacitor hands the key to us, and we route
// it: a live session still running is stopped (its `finished` reply then
// opens the session view), the Live screen and a selected session go back to
// the sessions list, and only the sessions list itself leaves the app.
import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
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
  else if (action.kind === "exit") void App.exitApp();
  return action;
}

/** Call once at startup. No-op on the web, where the browser owns back. */
export function installBackButton(): void {
  if (!Capacitor.isNativePlatform()) return;
  void App.addListener("backButton", () => {
    handleBack();
  });
}
