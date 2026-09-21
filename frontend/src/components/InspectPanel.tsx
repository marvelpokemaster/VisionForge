import type { Plane, SceneGraph } from "../types/twin";
import { getRelationsForNode, formatRelationValue } from "../lib/selectors";

interface Props {
  plane: Plane | null;
  sceneGraph: SceneGraph | null;
}

export default function InspectPanel({ plane, sceneGraph }: Props) {
  if (!plane) {
    return (
      <div className="panel">
        <h3>Inspect</h3>
        <p className="muted">Click a plane in the viewer to inspect it.</p>
      </div>
    );
  }

  const relations = sceneGraph ? getRelationsForNode(sceneGraph, plane.id) : [];

  return (
    <div className="panel">
      <h3>Inspect: {plane.id}</h3>
      <table className="kv">
        <tbody>
          <tr>
            <td>Type</td>
            <td>{plane.type}</td>
          </tr>
          <tr>
            <td>Support</td>
            <td>{plane.support} points</td>
          </tr>
          <tr>
            <td>Extent</td>
            <td>
              {plane.extent.width.toFixed(3)} &times; {plane.extent.height.toFixed(3)}
            </td>
          </tr>
          <tr>
            <td>Area</td>
            <td>{plane.area.toFixed(3)}</td>
          </tr>
          <tr>
            <td>Normal</td>
            <td>[{plane.normal.map((n) => n.toFixed(3)).join(", ")}]</td>
          </tr>
        </tbody>
      </table>

      <h4>Relations</h4>
      {relations.length === 0 ? (
        <p className="muted">No relations.</p>
      ) : (
        <ul className="relations">
          {relations.map((r, i) => {
            const value = formatRelationValue(r.edge);
            return (
              <li key={i}>
                <span className="relation-type">{r.relation}</span>{" "}
                <span className="relation-target">
                  {r.direction === "outgoing" ? "→" : "←"} {r.otherId}
                </span>
                {value && <span className="relation-value"> ({value})</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
