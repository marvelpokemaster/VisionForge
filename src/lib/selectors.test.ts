import { describe, it, expect } from "vitest";
import { getRelationsForNode, formatRelationValue } from "./selectors";
import type { SceneGraph } from "../types/twin";

const sceneGraph: SceneGraph = {
  nodes: [],
  edges: [
    { source: "room_001", target: "plane_000", relation: "contains" },
    { source: "plane_000", target: "plane_001", relation: "perpendicular_to", angle_deg: 89.6 },
    { source: "plane_000", target: "plane_001", relation: "adjacent_to", distance: 0.03 },
    { source: "plane_002", target: "plane_000", relation: "parallel_to", angle_deg: 1.2 },
    { source: "camera_001", target: "plane_000", relation: "above", height_difference: 18.09 },
    { source: "plane_000", target: "plane_003", relation: "intersects", point: [0, 0, 0], direction: [0, 1, 0], segment: [[0, 0, 0], [0, 1, 0]] }
  ]
};

describe("getRelationsForNode", () => {
  it("excludes contains edges", () => {
    const relations = getRelationsForNode(sceneGraph, "plane_000");
    expect(relations.every((r) => r.relation !== "contains")).toBe(true);
  });

  it("includes edges where the node is the source, tagged outgoing", () => {
    const relations = getRelationsForNode(sceneGraph, "plane_000");
    const perp = relations.find((r) => r.relation === "perpendicular_to");
    expect(perp).toBeDefined();
    expect(perp?.direction).toBe("outgoing");
    expect(perp?.otherId).toBe("plane_001");
  });

  it("includes edges where the node is the target, tagged incoming", () => {
    const relations = getRelationsForNode(sceneGraph, "plane_000");
    const parallel = relations.find((r) => r.relation === "parallel_to");
    expect(parallel).toBeDefined();
    expect(parallel?.direction).toBe("incoming");
    expect(parallel?.otherId).toBe("plane_002");

    const above = relations.find((r) => r.relation === "above");
    expect(above?.direction).toBe("incoming");
    expect(above?.otherId).toBe("camera_001");
  });

  it("returns every non-contains edge touching the node, in either direction", () => {
    const relations = getRelationsForNode(sceneGraph, "plane_000");
    // perpendicular_to, adjacent_to, parallel_to, above, intersects = 5
    expect(relations).toHaveLength(5);
  });

  it("returns an empty list for a node with no relations", () => {
    expect(getRelationsForNode(sceneGraph, "plane_999")).toEqual([]);
  });
});

describe("formatRelationValue", () => {
  it("formats angle_deg with a degree sign", () => {
    expect(formatRelationValue({ source: "a", target: "b", relation: "perpendicular_to", angle_deg: 89.6321 })).toBe("89.63°");
  });

  it("formats distance to 3 decimal places", () => {
    expect(formatRelationValue({ source: "a", target: "b", relation: "adjacent_to", distance: 0.030333 })).toBe("0.030");
  });

  it("formats height_difference to 3 decimal places", () => {
    expect(formatRelationValue({ source: "a", target: "b", relation: "above", height_difference: 18.087857 })).toBe("18.088");
  });

  it("returns null when there is no single scalar to show (e.g. intersects)", () => {
    expect(
      formatRelationValue({
        source: "a",
        target: "b",
        relation: "intersects",
        point: [0, 0, 0],
        direction: [0, 1, 0],
        segment: [[0, 0, 0], [0, 1, 0]]
      })
    ).toBeNull();
  });
});
