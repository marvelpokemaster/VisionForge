import type { Provenance } from "../types/twin";

interface Props {
  provenance: Provenance;
}

export default function ProvenanceFooter({ provenance }: Props) {
  const files = [
    provenance.source_files.room_model,
    provenance.source_files.cameras,
    provenance.source_files.scene_graph,
    provenance.source_files.sparse_cloud
  ]
    .filter((f): f is string => f !== null)
    .join(", ");

  return (
    <footer className="provenance-footer">
      <span>
        <strong>Source files:</strong> {files || "—"}
      </span>
      <span>
        <strong>Metric available:</strong> {provenance.scale.metric_available ? "yes" : "no"}
      </span>
      <span>
        <strong>Input type:</strong> {provenance.input_type}
      </span>
    </footer>
  );
}
