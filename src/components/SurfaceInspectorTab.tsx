import type { Plane, SceneGraph } from "../types/twin";

interface Props {
  plane: Plane | null;
  sceneGraph: SceneGraph | null;
  onClearSelection: () => void;
}

export default function SurfaceInspectorTab({
  plane,
  sceneGraph,
  onClearSelection,
}: Props) {
  if (!plane) {
    return (
      <div className="inspector-empty-state">
        <div className="empty-icon-circle">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h6v6" />
            <path d="M10 14 21 3" />
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          </svg>
        </div>
        <h4>No Surface Selected</h4>
        <p>Click any wall, floor, or ceiling directly in the 3D studio viewer to inspect its architectural properties.</p>
      </div>
    );
  }

  // Relations from scene graph
  const edges = sceneGraph?.edges ?? [];
  const parallelEdges = edges.filter(
    (e) => (e.source === plane.id || e.target === plane.id) && e.relation === "parallel_to"
  );
  const perpendicularEdges = edges.filter(
    (e) => (e.source === plane.id || e.target === plane.id) && e.relation === "perpendicular_to"
  );

  const getOtherId = (e: { source: string; target: string }) =>
    e.source === plane.id ? e.target : e.source;

  return (
    <div className="surface-inspector-container">
      <div className="inspector-header">
        <div>
          <span className="surface-type-badge">{plane.type.toUpperCase()}</span>
          <h3>{plane.id}</h3>
        </div>
        <button
          type="button"
          className="clear-select-btn"
          onClick={onClearSelection}
          title="Deselect surface"
        >
          ✕
        </button>
      </div>

      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Surface Dimensions</h4>
        </div>
        <div className="surface-meta-grid">
          <div className="meta-card">
            <span className="meta-label">Surface Area</span>
            <span className="meta-val">
              {plane.area ? `${plane.area.toFixed(2)} m²` : plane.extent ? `${(plane.extent.width * plane.extent.height).toFixed(2)} m²` : "—"}
            </span>
          </div>

          {plane.extent && (
            <>
              <div className="meta-card">
                <span className="meta-label">Span Width</span>
                <span className="meta-val">{plane.extent.width.toFixed(2)} m</span>
              </div>
              <div className="meta-card">
                <span className="meta-label">Span Height</span>
                <span className="meta-val">{plane.extent.height.toFixed(2)} m</span>
              </div>
            </>
          )}

          <div className="meta-card">
            <span className="meta-label">Point Support</span>
            <span className="meta-val">{plane.support} points</span>
          </div>
        </div>
      </div>

      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Architectural Orientation</h4>
        </div>
        <div className="normal-row">
          <span className="normal-label">Normal Vector:</span>
          <span className="normal-val">
            [{plane.normal.map((n) => n.toFixed(2)).join(", ")}]
          </span>
        </div>
      </div>

      {(parallelEdges.length > 0 || perpendicularEdges.length > 0) && (
        <div className="dock-section">
          <div className="dock-section-title">
            <h4>Spatial Relationships</h4>
          </div>
          <div className="relations-tags-list">
            {parallelEdges.map((e, idx) => (
              <span key={idx} className="relation-tag parallel">
                Parallel to {getOtherId(e)}
              </span>
            ))}
            {perpendicularEdges.map((e, idx) => (
              <span key={idx} className="relation-tag perpendicular">
                Perpendicular to {getOtherId(e)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
