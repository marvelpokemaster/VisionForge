import { useSyncExternalStore } from "react";
import { parseRoute, type Route } from "./route";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener("popstate", onChange);
  };
}

function snapshot(): string {
  return `${window.location.pathname}|${window.location.hash}`;
}

export function useRoute(): Route {
  const key = useSyncExternalStore(subscribe, snapshot, snapshot);
  const [pathname, hash] = key.split("|");
  return parseRoute(hash ?? "", pathname);
}
