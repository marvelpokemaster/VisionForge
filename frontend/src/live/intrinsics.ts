// Intrinsics the Live screen sends in the configure message (docs/live_tracking.md §9).
//
// Without a calibration the phone's lens is unknown to the WebView, so the
// client sends `phoneDefaultIntrinsics` for the size it SENDS: focal =
// 0.8 × the longer side (~64° field of view along that side), principal
// point at the centre, source "phone_default". The server scales it with
// its own downscale like any other intrinsics. This is a STOPGAP — the
// first real-phone run showed the server's max(w, h) guess over-estimates
// a phone's focal — and `visionforge calibrate` is the real fix: its output
// (a cameras.json-style list, median first, each entry tagged with the
// width/height it was measured at) is pasted into the Intrinsics field and
// sent as `intrinsics_from_cameras` + `intrinsics_size`; the server rescales
// it to the frames it receives.
export interface ClientIntrinsics {
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  k1: number;
  source: "phone_default";
}

export interface CamerasEntry {
  camera_model: string;
  camera_params: number[];
  width?: number;
  height?: number;
  name?: string;
}

export interface ParsedCameras {
  cameras: CamerasEntry[];
  /** [width, height] the intrinsics were measured at, when the entries say so. */
  size: [number, number] | null;
}

export const PHONE_DEFAULT_FOCAL_FACTOR = 0.8;

export function phoneDefaultIntrinsics(width: number, height: number): ClientIntrinsics {
  const f = PHONE_DEFAULT_FOCAL_FACTOR * Math.max(width, height);
  return { fx: f, fy: f, cx: width / 2, cy: height / 2, k1: 0, source: "phone_default" };
}

/** Parse the Intrinsics field: a cameras.json / `visionforge calibrate`
 * list, or one entry object. Throws an Error with a message the field shows. */
export function parseCamerasJson(text: string): ParsedCameras {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    throw new Error(`not JSON: ${err instanceof Error ? err.message : String(err)}`);
  }
  const list = Array.isArray(data) ? data : [data];
  if (list.length === 0) throw new Error("the list is empty");
  const cameras: CamerasEntry[] = list.map((e, i) => {
    if (typeof e !== "object" || e === null) throw new Error(`entry ${i} is not an object`);
    const o = e as Record<string, unknown>;
    if (typeof o.camera_model !== "string") throw new Error(`entry ${i} has no camera_model`);
    if (!Array.isArray(o.camera_params) || !o.camera_params.every((v) => typeof v === "number" && Number.isFinite(v))) {
      throw new Error(`entry ${i} has no numeric camera_params`);
    }
    const out: CamerasEntry = { camera_model: o.camera_model, camera_params: o.camera_params as number[] };
    if (typeof o.width === "number" && typeof o.height === "number" && o.width > 0 && o.height > 0) {
      out.width = o.width;
      out.height = o.height;
    }
    if (typeof o.name === "string") out.name = o.name;
    return out;
  });
  const first = cameras[0];
  const size: [number, number] | null = first.width && first.height ? [first.width, first.height] : null;
  return { cameras, size };
}

export interface ConfigureOptions {
  cameras: ParsedCameras | null; // from the Intrinsics field, or null -> phone default
  record: boolean;
}

/** The configure message for frames sent at `sent` size. Only the first
 * cameras entry (the median, for a calibrate output) travels. */
export function configureMessage(sent: { width: number; height: number }, opts: ConfigureOptions): Record<string, unknown> {
  const msg: Record<string, unknown> = { width: sent.width, height: sent.height };
  if (opts.record) msg.record = true;
  if (opts.cameras) {
    msg.intrinsics_from_cameras = [opts.cameras.cameras[0]];
    if (opts.cameras.size) msg.intrinsics_size = opts.cameras.size;
  } else {
    msg.intrinsics = phoneDefaultIntrinsics(sent.width, sent.height);
  }
  return msg;
}
