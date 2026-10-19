import { describe, expect, it } from "vitest";
import { registerBackGuard, resolveBack } from "./backButton";

describe("resolveBack", () => {
  it("goes from the Live screen or a session back to the sessions list", () => {
    expect(resolveBack({ kind: "live" }, [])).toEqual({ kind: "navigate", route: { kind: "home" } });
    expect(resolveBack({ kind: "session", id: "live-1" }, [])).toEqual({ kind: "navigate", route: { kind: "home" } });
  });

  it("leaves the app only from the sessions list", () => {
    expect(resolveBack({ kind: "home" }, [])).toEqual({ kind: "exit" });
  });

  it("lets a running live session claim the press (back = Stop) until it unregisters", () => {
    let running = true;
    const off = registerBackGuard(() => running);
    expect(resolveBack({ kind: "live" })).toEqual({ kind: "handled" });
    running = false;
    expect(resolveBack({ kind: "live" })).toEqual({ kind: "navigate", route: { kind: "home" } });
    running = true;
    off();
    expect(resolveBack({ kind: "live" })).toEqual({ kind: "navigate", route: { kind: "home" } });
  });
});
