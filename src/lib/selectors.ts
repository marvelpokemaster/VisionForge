import type { SceneGraph, SceneGraphEdge, RelationType } from "../types/twin";

export interface NodeRelation {
  relation: RelationType;
  otherId: string;
  direction: "outgoing" | "incoming";
  edge: SceneGraphEdge;
}

/**
 * Every edge touching `nodeId`, in either direction, excluding `contains`
 * (a structural room->child edge, not a spatial relation worth surfacing
 * in an inspect panel). Used by the inspect panel to show a selected
 * plane's parallel/perpendicular/adjacent/intersects/above/below relations.
 */
export function getRelationsForNode(sceneGraph: SceneGraph, nodeId: string): NodeRelation[] {
  const relations: NodeRelation[] = [];
  for (const edge of sceneGraph.edges) {
    if (edge.relation === "contains") continue;
    if (edge.source === nodeId) {
      relations.push({ relation: edge.relation, otherId: edge.target, direction: "outgoing", edge });
    } else if (edge.target === nodeId) {
      relations.push({ relation: edge.relation, otherId: edge.source, direction: "incoming", edge });
    }
  }
  return relations;
}

/** The human-readable supporting number for one relation edge, matching
 * whichever field that relation type actually carries. Returns null for
 * relations with no single scalar (e.g. intersects, whose "number" is a
 * segment, not a scalar). */
export function formatRelationValue(edge: SceneGraphEdge): string | null {
  if (edge.angle_deg !== undefined) return `${edge.angle_deg.toFixed(2)}°`;
  if (edge.distance !== undefined) return edge.distance.toFixed(3);
  if (edge.height_difference !== undefined) return edge.height_difference.toFixed(3);
  if (edge.distance_to_boundary !== undefined) return edge.distance_to_boundary.toFixed(3);
  return null;
}
