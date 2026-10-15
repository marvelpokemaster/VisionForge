import { describe, expect, it } from "vitest";
import { liveCloudUrl, liveSocketOrigin, liveSocketUrl } from "./wsUrl";

const httpPage = { protocol: "http:", host: "localhost:5173" };
const httpsPage = { protocol: "https:", host: "twin.example.com" };

describe("liveSocketUrl", () => {
  it("maps an absolute http base to ws on the same host (the Android build's 10.0.2.2)", () => {
    expect(liveSocketUrl("http://10.0.2.2:8000", "abc", httpPage)).toBe("ws://10.0.2.2:8000/live/abc");
    expect(liveSocketUrl("http://192.168.1.20:8000/", "abc", httpsPage)).toBe("ws://192.168.1.20:8000/live/abc");
  });

  it("maps an absolute https base to wss", () => {
    expect(liveSocketUrl("https://api.example.com/vf", "s 1", httpPage)).toBe("wss://api.example.com/vf/live/s%201");
  });

  it("resolves the relative /api base against the current page, keeping its scheme", () => {
    expect(liveSocketUrl("/api", "x", httpPage)).toBe("ws://localhost:5173/api/live/x");
    expect(liveSocketUrl("/api", "x", httpsPage)).toBe("wss://twin.example.com/api/live/x");
    expect(liveSocketOrigin("api/", httpPage)).toBe("ws://localhost:5173/api");
    expect(liveSocketOrigin("", httpPage)).toBe("ws://localhost:5173");
  });

  it("leaves an explicit ws(s) base alone", () => {
    expect(liveSocketOrigin("wss://x.y/z", httpPage)).toBe("wss://x.y/z");
  });

  it("derives the live cloud URL from the same base", () => {
    expect(liveCloudUrl("/api", "a/b")).toBe("/api/live/a%2Fb/cloud");
    expect(liveCloudUrl("http://10.0.2.2:8000/", "s")).toBe("http://10.0.2.2:8000/live/s/cloud");
  });
});
