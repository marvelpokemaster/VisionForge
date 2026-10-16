// The frame pump: at `fps`, encode the current frame (the encoder is injected:
// in the app it draws the <video> to a canvas at <= maxWidth and JPEG-encodes
// it) and send it as one binary WebSocket message. It never queues: a frame
// is skipped (and counted in skippedClient) when the previous send was less
// than one period ago, when the socket still has more than one frame's worth
// of bytes buffered (the network is behind), when an encode is still in
// flight, or when the source has no frame yet. Mirrors scripts/replay_live.py:
// {"width","height"} first, binary frames, {"cmd":"finish"} on stop.
export interface PumpSocket {
  readonly bufferedAmount: number;
  readonly readyState: number; // 1 = OPEN
  send(data: string | ArrayBuffer): void;
}

export type FrameEncoder = () => Promise<ArrayBuffer | null>;

export type SkipReason = "rate" | "buffer" | "busy" | "no-frame" | "closed";

export interface PumpStats {
  sent: number;
  skippedClient: number;
  skipped: Record<SkipReason, number>;
  lastFrameBytes: number;
  lastSentAt: number | null;
}

export interface PumpOptions {
  fps?: number; // default 10
}

export interface Clock {
  now(): number; // ms
}

export interface Timers {
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

const OPEN = 1;

export class FramePump {
  readonly fps: number;
  readonly stats: PumpStats = { sent: 0, skippedClient: 0, skipped: { rate: 0, buffer: 0, busy: 0, "no-frame": 0, closed: 0 }, lastFrameBytes: 0, lastSentAt: null };
  onSkip?: (reason: SkipReason) => void;
  private handle: unknown = null;
  private busy = false;
  private stopped = false;

  constructor(
    private readonly socket: PumpSocket,
    private readonly encode: FrameEncoder,
    opts: PumpOptions = {},
    private readonly clock: Clock = { now: () => Date.now() },
    private readonly timers: Timers = {
      setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
      clearInterval: (h) => globalThis.clearInterval(h as number)
    }
  ) {
    this.fps = opts.fps ?? 10;
  }

  get periodMs(): number {
    return 1000 / this.fps;
  }

  /** Send the configuration text message (frame size plus any extra
   * fields: intrinsics, record — see live/intrinsics.ts) and start ticking. */
  start(width: number, height: number, extra: Record<string, unknown> = {}): void {
    this.socket.send(JSON.stringify({ ...extra, width, height }));
    this.handle = this.timers.setInterval(() => void this.tick(), this.periodMs);
  }

  /** One scheduling decision; returns what happened (exposed for tests). */
  async tick(): Promise<"sent" | SkipReason> {
    if (this.stopped || this.socket.readyState !== OPEN) return this.skip("closed");
    if (this.busy) return this.skip("busy");
    const now = this.clock.now();
    // "< 1/fps ago": allow a 1 ms tolerance for timer jitter
    if (this.stats.lastSentAt !== null && now - this.stats.lastSentAt < this.periodMs - 1) return this.skip("rate");
    if (this.stats.lastFrameBytes > 0 && this.socket.bufferedAmount > this.stats.lastFrameBytes) return this.skip("buffer");

    this.busy = true;
    try {
      const frame = await this.encode();
      if (!frame) return this.skip("no-frame");
      if (this.stopped || this.socket.readyState !== OPEN) return this.skip("closed");
      this.socket.send(frame);
      this.stats.sent += 1;
      this.stats.lastFrameBytes = frame.byteLength;
      // the frame's capture time, not the send completion: an encode that takes
      // 50 ms must not push the next 100 ms tick inside the rate window
      this.stats.lastSentAt = now;
      return "sent";
    } finally {
      this.busy = false;
    }
  }

  /** Stop ticking and ask the server to finish. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    if (this.handle !== null) this.timers.clearInterval(this.handle);
    this.handle = null;
    if (this.socket.readyState === OPEN) this.socket.send(JSON.stringify({ cmd: "finish" }));
  }

  private skip(reason: SkipReason): SkipReason {
    this.stats.skipped[reason] += 1;
    if (reason !== "closed") this.stats.skippedClient += 1;
    this.onSkip?.(reason);
    return reason;
  }
}
