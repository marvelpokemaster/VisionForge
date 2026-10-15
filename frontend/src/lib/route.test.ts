import { describe, expect, it } from "vitest";
import { parseRoute, routeHash } from "./route";

describe("route", () => {
  it("parses the live route from the hash or the bare /live path", () => {
    expect(parseRoute("#/live")).toEqual({ kind: "live" });
    expect(parseRoute("#/live/")).toEqual({ kind: "live" });
    expect(parseRoute("", "/live")).toEqual({ kind: "live" });
    expect(parseRoute("", "/")).toEqual({ kind: "home" });
  });

  it("parses and formats session routes with encoded ids", () => {
    expect(parseRoute("#/session/live-123")).toEqual({ kind: "session", id: "live-123" });
    expect(parseRoute(routeHash({ kind: "session", id: "a b/c" }))).toEqual({ kind: "session", id: "a b/c" });
    expect(routeHash({ kind: "live" })).toBe("#/live");
    expect(routeHash({ kind: "home" })).toBe("#/");
    expect(parseRoute("#/nonsense")).toEqual({ kind: "home" });
  });
});
