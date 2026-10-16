import { describe, expect, it } from "vitest";
import { ApiError, type RoomMeasurementsResponse } from "./api";
import { hasGeometry, loadSessionView, noGeometryNotice } from "./sessionLoad";
import type { Twin } from "../types/twin";

function twinWith(stage_status: Record<string, string>, planes = 0): Twin {
  const plane = { id: "plane_000", type: "floor", boundary_room: [], centroid_room: [0, 0, 0] };
  return {
    provenance: { stage_status, input_type: "real", run_dir: "outputs/x" },
    room_model: planes > 0 ? { planes: Array.from({ length: planes }, () => plane) } : null,
    cameras: null,
    scene_graph: null,
    sparse_cloud_path: null
  } as unknown as Twin;
}

const measurements: RoomMeasurementsResponse = { length: null, width: null, height: null, floor_area: null };

describe("noGeometryNotice", () => {
  it("names a live session that never initialised", () => {
    expect(noGeometryNotice(twinWith({ live_tracking: "failed", geometry: "skipped", twin: "success" }))).toBe(
      "no geometry: live tracking failed (never initialised)"
    );
  });

  it("names other failed or still-running stages, and is null when there are planes", () => {
    expect(noGeometryNotice(twinWith({ reconstruction: "failed", geometry: "failed" }))).toBe(
      "no geometry: reconstruction, geometry failed"
    );
    expect(noGeometryNotice(twinWith({ reconstruction: "running" }))).toBe("no geometry yet: reconstruction still running");
    expect(noGeometryNotice(twinWith({}))).toBe("no geometry: this session has no room model");
    expect(noGeometryNotice(twinWith({ live_tracking: "success" }, 3))).toBeNull();
    expect(hasGeometry(twinWith({}, 1))).toBe(true);
  });
});

describe("loadSessionView", () => {
  it("keeps the twin when the measurements 404 (failed live session)", async () => {
    const twin = twinWith({ live_tracking: "failed", twin: "success" });
    const calls: string[] = [];
    const view = await loadSessionView("live-1", {
      getTwin: async (id) => {
        calls.push(`twin:${id}`);
        return twin;
      },
      getMeasurements: async (id) => {
        calls.push(`measurements:${id}`);
        throw new ApiError("GET /sessions/live-1/measurements failed: 404 Not Found", 404);
      }
    });
    expect(calls).toEqual(["twin:live-1", "measurements:live-1"]); // twin first, then measurements
    expect(view.twin).toBe(twin);
    expect(view.measurements).toBeNull();
    expect(view.notice).toBe("no geometry: live tracking failed (never initialised)");
  });

  it("returns both for a normal session, with no notice", async () => {
    const view = await loadSessionView("demo", {
      getTwin: async () => twinWith({ geometry: "success" }, 3),
      getMeasurements: async () => measurements
    });
    expect(view.measurements).toBe(measurements);
    expect(view.notice).toBeNull();
  });

  it("still says so when measurements are missing but the twin has planes", async () => {
    const view = await loadSessionView("odd", {
      getTwin: async () => twinWith({ geometry: "success" }, 2),
      getMeasurements: async () => {
        throw new ApiError("404", 404);
      }
    });
    expect(view.notice).toBe("measurements not available for this session");
  });

  it("propagates non-404 measurement errors and twin errors", async () => {
    await expect(
      loadSessionView("x", {
        getTwin: async () => twinWith({}, 1),
        getMeasurements: async () => {
          throw new ApiError("500", 500);
        }
      })
    ).rejects.toThrow("500");
    await expect(
      loadSessionView("x", {
        getTwin: async () => {
          throw new ApiError("GET /sessions/x/twin failed: 404 Not Found", 404);
        },
        getMeasurements: async () => measurements
      })
    ).rejects.toThrow(/twin failed: 404/);
  });
});
