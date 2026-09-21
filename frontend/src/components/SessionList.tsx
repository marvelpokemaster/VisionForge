import type { Session } from "../types/twin";

interface Props {
  sessions: Session[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function statusSymbol(status: string): string {
  if (status === "success") return "✓";
  if (status === "running") return "…";
  return "✗";
}

export default function SessionList({ sessions, selectedId, onSelect }: Props) {
  return (
    <div className="panel">
      <h3>Sessions</h3>
      {sessions.length === 0 ? (
        <p className="muted">No sessions found.</p>
      ) : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li
              key={s.id}
              className={s.id === selectedId ? "session selected" : "session"}
              onClick={() => onSelect(s.id)}
            >
              <span className="session-id">{s.id}</span>
              <span className={`badge badge-${s.provenance.input_type}`}>{s.provenance.input_type}</span>
              <span className="stage-status">
                {Object.entries(s.provenance.stage_status).map(([stage, status]) => (
                  <span key={stage} className={`stage stage-${status}`} title={`${stage}: ${status}`}>
                    {statusSymbol(status)}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
