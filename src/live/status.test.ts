import { describe, expect, it } from "vitest";
import type { Plane, Twin } from "../types/twin";
import { addClientSkips, initialSummary, noGeometryReason, reduceStatus, twinForRedraw, type LiveStatusMessage } from "./status";

function msg(over: Partial<LiveStatusMessage> & { frame_index: number }): LiveStatusMessage {
  return {
    session_id: "s",
    state: "TRACKING",
    n_tracked: 200,
    n_inliers: 150,
    reprojection_rms: 0.4,
    is_keyframe: false,
    map_size: 300,
    n_keyframes: 5,
    segment: 0,
    n_segments: 1,
    frames: over.frame_index + 1,
    dropped: 0,
    source_size: [800, 600],
    processed_size: [640, 480],
    intrinsics_source: "guess",
    pose: { rotation_quat: [0, 0, 0, 1], translation: [0, 0, 0] },
    twin_update: null,
    ...over
  };
}

function twin(planes: number, reason: string | null = null): Twin {
  return {
    provenance: {
      run_dir: null,
      source_files: { room_model: null, cameras: null, scene_graph: null, sparse_cloud: null },
      stage_status: { live_tracking: "TRACKING" },
      input_type: "unknown",
      scale: { metric_available: false, scale_factor: 1 },
      measurement_methods: { length_method: null, width_method: null, height_method: null, floor_area_method: null },
      live: true,
      reason
    },
    room_model: {
      coordinate_system: null,
      scale: { metric_available: false, scale_factor: 1 },
      room: {
        length: 0, width: 0, height: 0, floor_area: 0,
        length_method: null, width_method: null, height_method: null, floor_area_method: null,
        bounding_polygon_room: []
      },
      planes: Array.from({ length: planes }, (_, i) => ({ id: `plane_${i}` })) as unknown as Plane[],
      intersections: []
    },
    cameras: [],
    scene_graph: null,
    sparse_cloud_path: null
  };
}

describe("reduceStatus", () => {
  it("copies the per-frame fields and measures fps from arrival times", () => {
    let s = initialSummary();
    expect(s.state).toBe("IDLE");
    s = reduceStatus(s, msg({ frame_index: 0, state: "INITIALIZING", n_tracked: 210, map_size: 0, n_keyframes: 0, segment: null, pose: null }), 1000);
    expect(s.state).toBe("INITIALIZING");
    expect(s.fpsMeasured).toBeNull();
    s = reduceStatus(s, msg({ frame_index: 1 }), 1100);
    s = reduceStatus(s, msg({ frame_index: 2 }), 1200);
    expect(s.fpsMeasured).toBeCloseTo(10, 5);
    expect(s).toMatchObject({ state: "TRACKING", frameIndex: 2, nTracked: 200, nInliers: 150, mapSize: 300, nKeyframes: 5, segment: 0, frames: 3, processedSize: [640, 480], intrinsicsSource: "guess" });
  });

  it("records a LOST episode with start and end frames, and a segment change on re-initialisation", () => {
    let s = initialSummary();
    for (let i = 0; i < 5; i++) s = reduceStatus(s, msg({ frame_index: i }), i * 100);
    for (let i = 5; i < 9; i++) s = reduceStatus(s, msg({ frame_index: i, state: "LOST", pose: null, segment: null, map_size: 0 }), i * 100);
    expect(s.state).toBe("LOST");
    expect(s.lostEpisodes).toEqual([{ start: 5, end: null }]);
    s = reduceStatus(s, msg({ frame_index: 9, state: "INITIALIZING", pose: null, segment: null, map_size: 0 }), 900);
    expect(s.lostEpisodes).toEqual([{ start: 5, end: 8 }]);
    expect(s.segmentChanges).toBe(0);
    s = reduceStatus(s, msg({ frame_index: 10, segment: 1, n_segments: 2 }), 1000);
    expect(s.segment).toBe(1);
    expect(s.segmentChanges).toBe(1);
    // a second loss opens a second episode
    s = reduceStatus(s, msg({ frame_index: 11, state: "LOST", pose: null, segment: null }), 1100);
    expect(s.lostEpisodes).toHaveLength(2);
    expect(s.lostEpisodes[1]).toEqual({ start: 11, end: null });
  });

  it("counts twin updates and keeps the previous twin object until a new one arrives", () => {
    let s = initialSummary();
    const t1 = twin(0, "199 points < min_points=200");
    s = reduceStatus(s, msg({ frame_index: 0, twin_update: t1 }), 0);
    expect(s.lastTwin).toBe(t1);
    expect(s.twinUpdates).toBe(1);
    expect(noGeometryReason(s.lastTwin)).toBe("199 points < min_points=200");
    s = reduceStatus(s, msg({ frame_index: 1 }), 100);
    expect(s.lastTwin).toBe(t1); // same reference: no redraw
    const t2 = twin(3);
    s = reduceStatus(s, msg({ frame_index: 2, twin_update: t2 }), 200);
    expect(s.lastTwin).toBe(t2);
    expect(s.twinUpdates).toBe(2);
    expect(noGeometryReason(s.lastTwin)).toBeNull();
  });

  it("folds server drops and client skips separately", () => {
    let s = reduceStatus(initialSummary(), msg({ frame_index: 0, dropped: 3 }), 0);
    s = addClientSkips(s, 2);
    expect(s.dropped).toBe(3);
    expect(s.skippedClient).toBe(2);
    expect(addClientSkips(s, 0)).toBe(s);
    s = reduceStatus(s, msg({ frame_index: 1, dropped: 4 }), 100);
    expect(s.skippedClient).toBe(2); // not reset by a status
  });
});

describe("twinForRedraw", () => {
  it("returns a new object only when twin_update is non-null", () => {
    const prev = twin(1);
    expect(twinForRedraw(prev, { twin_update: null })).toBe(prev);
    expect(twinForRedraw(null, { twin_update: null })).toBeNull();
    const next = twin(2);
    expect(twinForRedraw(prev, { twin_update: next })).toBe(next);
  });
});

describe("noGeometryReason", () => {
  it("is null without a twin or with planes, and falls back when no reason is given", () => {
    expect(noGeometryReason(null)).toBeNull();
    expect(noGeometryReason(twin(2))).toBeNull();
    expect(noGeometryReason(twin(0))).toBe("no planes fitted");
  });
});
