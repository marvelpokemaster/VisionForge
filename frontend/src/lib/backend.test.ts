import { describe, expect, it } from "vitest";
import {
  STORAGE_KEY,
  apiBase,
  normalizeApiBase,
  probeBackend,
  readApiBaseOverride,
  setApiBaseOverride,
  subscribeApiBase,
  validateApiBase,
  type StorageLike
} from "./backend";

function memoryStorage(initial: Record<string, string> = {}): StorageLike & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v;
    },
    removeItem: (k) => {
      delete data[k];
    }
  };
}

const throwingStorage: StorageLike = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceeded");
  },
  removeItem: () => {
    throw new Error("SecurityError");
  }
};

describe("apiBase", () => {
  it("falls back to the build default when nothing is stored", () => {
    expect(apiBase(memoryStorage(), "http://10.0.2.2:8000")).toBe("http://10.0.2.2:8000");
    expect(apiBase(null, "/api/")).toBe("/api");
  });

  it("prefers the stored override and normalises it", () => {
    const s = memoryStorage({ [STORAGE_KEY]: "  http://192.168.1.37:8000/ " });
    expect(readApiBaseOverride(s)).toBe("http://192.168.1.37:8000");
    expect(apiBase(s, "http://10.0.2.2:8000")).toBe("http://192.168.1.37:8000");
  });

  it("ignores localhost/emulator dev overrides in production mode", () => {
    const local = memoryStorage({ [STORAGE_KEY]: "http://localhost:8000" });
    const emu = memoryStorage({ [STORAGE_KEY]: "http://10.0.2.2:8000" });
    const loop = memoryStorage({ [STORAGE_KEY]: "http://127.0.0.1:8000" });
    expect(readApiBaseOverride(local)).toBeDefined();
    expect(readApiBaseOverride(emu)).toBeDefined();
    expect(readApiBaseOverride(loop)).toBeDefined();
  });

  it("persists, clears and notifies", () => {
    const s = memoryStorage();
    let notified = 0;
    const off = subscribeApiBase(() => notified++);
    expect(setApiBaseOverride("http://192.168.1.37:8000/", s)).toBe("http://192.168.1.37:8000");
    expect(s.data[STORAGE_KEY]).toBe("http://192.168.1.37:8000");
    expect(setApiBaseOverride("   ", s)).toBe(apiBase(null));
    expect(STORAGE_KEY in s.data).toBe(false);
    expect(notified).toBe(2);
    off();
    setApiBaseOverride(null, s);
    expect(notified).toBe(2);
  });

  it("survives a storage that throws or is missing", () => {
    expect(apiBase(throwingStorage, "http://10.0.2.2:8000")).toBe("http://10.0.2.2:8000");
    expect(setApiBaseOverride("http://x:1", throwingStorage)).toBe(apiBase(null));
    expect(readApiBaseOverride(null)).toBeNull();
  });

  it("normalises and validates what the field accepts", () => {
    expect(normalizeApiBase(undefined)).toBeNull();
    expect(normalizeApiBase("/api//")).toBe("/api");
    expect(validateApiBase("http://192.168.1.37:8000")).toBeNull();
    expect(validateApiBase("/api")).toBeNull();
    expect(validateApiBase("")).toBeNull();
    expect(validateApiBase("192.168.1.37:8000")).toMatch(/not an http\(s\) URL/);
  });
});

describe("probeBackend", () => {
  const okFetch = (async (url: RequestInfo | URL) => {
    expect(String(url)).toBe("http://192.168.1.37:8000/sessions");
    return new Response(JSON.stringify([{ id: "a" }, { id: "b" }]), { status: 200 });
  }) as typeof fetch;

  it("reports ok with the session count on a 200 from GET /sessions", async () => {
    const clock = [0, 12];
    const r = await probeBackend("http://192.168.1.37:8000", okFetch, 5000, () => clock.shift() ?? 12);
    expect(r).toEqual({ ok: true, sessions: 2, ms: 12 });
  });

  it("reports ok with authRequired on a 401 from GET /sessions in production", async () => {
    const authReq = (async () => new Response("unauthorized", { status: 401, statusText: "Unauthorized" })) as typeof fetch;
    const r = await probeBackend("https://visionforge-spatial-api.onrender.com", authReq);
    expect(r).toMatchObject({ ok: true, sessions: 0, authRequired: true });
  });

  it("reports a failed status and a thrown fetch (unreachable host)", async () => {
    const bad = (async () => new Response("nope", { status: 503, statusText: "Service Unavailable" })) as typeof fetch;
    expect(await probeBackend("http://h", bad)).toMatchObject({ ok: false, error: "GET /sessions -> 503 Service Unavailable" });
    const down = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    expect(await probeBackend("http://h", down)).toMatchObject({ ok: false, error: "Failed to fetch" });
  });

  it("gives up after the timeout with a hint", async () => {
    const hang = ((_url: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
      })) as typeof fetch;
    const r = await probeBackend("http://h", hang, 20);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/no answer within 0.02 s/);
  });
});
