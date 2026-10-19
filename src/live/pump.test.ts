import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FramePump, type PumpSocket } from "./pump";

class MockSocket implements PumpSocket {
  bufferedAmount = 0;
  readyState = 1;
  sent: (string | ArrayBuffer)[] = [];
  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }
  get binaryFrames() {
    return this.sent.filter((d) => d instanceof ArrayBuffer) as ArrayBuffer[];
  }
  get texts() {
    return this.sent.filter((d) => typeof d === "string") as string[];
  }
}

const frame = (bytes = 1000) => new ArrayBuffer(bytes);

describe("FramePump", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sends the size message first, then one frame per period", async () => {
    const ws = new MockSocket();
    const pump = new FramePump(ws, async () => frame(), { fps: 10 });
    pump.start(640, 480);
    expect(ws.texts[0]).toBe(JSON.stringify({ width: 640, height: 480 }));
    expect(ws.binaryFrames).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(ws.binaryFrames).toHaveLength(10);
    expect(pump.stats.sent).toBe(10);
    expect(pump.stats.skippedClient).toBe(0);
    expect(pump.stats.lastFrameBytes).toBe(1000);
  });

  it("skips while the socket has more than one frame buffered, and counts it", async () => {
    const ws = new MockSocket();
    const pump = new FramePump(ws, async () => frame(1000), { fps: 10 });
    const skips: string[] = [];
    pump.onSkip = (r) => skips.push(r);
    pump.start(1, 1);
    await vi.advanceTimersByTimeAsync(100); // first frame -> lastFrameBytes = 1000
    expect(pump.stats.sent).toBe(1);
    ws.bufferedAmount = 1500; // network behind by more than one frame
    await vi.advanceTimersByTimeAsync(300);
    expect(pump.stats.sent).toBe(1);
    expect(pump.stats.skipped.buffer).toBe(3);
    expect(pump.stats.skippedClient).toBe(3);
    expect(skips).toEqual(["buffer", "buffer", "buffer"]);
    ws.bufferedAmount = 900; // less than one frame: allowed again
    await vi.advanceTimersByTimeAsync(100);
    expect(pump.stats.sent).toBe(2);
  });

  it("skips a tick that comes less than one period after the previous send", async () => {
    const ws = new MockSocket();
    const pump = new FramePump(ws, async () => frame(), { fps: 10 });
    pump.start(1, 1);
    await vi.advanceTimersByTimeAsync(100);
    expect(pump.stats.sent).toBe(1);
    expect(await pump.tick()).toBe("rate"); // manual early tick, 0 ms later
    expect(pump.stats.skipped.rate).toBe(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(pump.stats.sent).toBe(2);
  });

  it("never overlaps encodes: a slow encoder makes later ticks skip as busy", async () => {
    const ws = new MockSocket();
    let release: (() => void) | null = null;
    const encode = () =>
      new Promise<ArrayBuffer | null>((resolve) => {
        release = () => resolve(frame());
      });
    const pump = new FramePump(ws, encode, { fps: 10 });
    pump.start(1, 1);
    await vi.advanceTimersByTimeAsync(350); // first tick starts an encode that never finishes...
    expect(pump.stats.skipped.busy).toBe(2);
    expect(pump.stats.sent).toBe(0);
    release!();
    await vi.advanceTimersByTimeAsync(0);
    expect(pump.stats.sent).toBe(1);
  });

  it("skips when the source has no frame yet, counts it, and sends finish on stop", async () => {
    const ws = new MockSocket();
    let ready = false;
    const pump = new FramePump(ws, async () => (ready ? frame() : null), { fps: 10 });
    pump.start(1, 1);
    await vi.advanceTimersByTimeAsync(200);
    expect(pump.stats.skipped["no-frame"]).toBe(2);
    ready = true;
    await vi.advanceTimersByTimeAsync(100);
    expect(pump.stats.sent).toBe(1);
    pump.stop();
    expect(ws.texts.at(-1)).toBe(JSON.stringify({ cmd: "finish" }));
    await vi.advanceTimersByTimeAsync(500);
    expect(pump.stats.sent).toBe(1); // nothing after stop
    pump.stop(); // idempotent: no second finish
    expect(ws.texts.filter((t) => t.includes("finish"))).toHaveLength(1);
  });

  it("does not send on a socket that is not open", async () => {
    const ws = new MockSocket();
    ws.readyState = 3;
    const pump = new FramePump(ws, async () => frame(), { fps: 10 });
    expect(await pump.tick()).toBe("closed");
    expect(pump.stats.skippedClient).toBe(0); // 'closed' is not a client skip
    pump.stop();
    expect(ws.sent).toHaveLength(0);
  });
});

describe("configure message extras", () => {
  it("merges intrinsics / record into the first text message, size winning", () => {
    const texts: string[] = [];
    const ws = { bufferedAmount: 0, readyState: 1, send: (d: string | ArrayBuffer) => void (typeof d === "string" && texts.push(d)) };
    const timers = { setInterval: () => 1, clearInterval: () => undefined };
    const pump = new FramePump(ws, async () => null, { fps: 10 }, { now: () => 0 }, timers);
    pump.start(640, 1138, { record: true, intrinsics: { fx: 1, fy: 1, cx: 2, cy: 3, k1: 0, source: "phone_default" }, width: 1 });
    expect(JSON.parse(texts[0])).toEqual({
      record: true,
      intrinsics: { fx: 1, fy: 1, cx: 2, cy: 3, k1: 0, source: "phone_default" },
      width: 640,
      height: 1138
    });
  });
});
