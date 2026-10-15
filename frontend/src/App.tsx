import { useEffect, useMemo, useState } from "react";
import { listSessions, getTwin, getMeasurements, type RoomMeasurementsResponse } from "./lib/api";
import type { Session, Twin } from "./types/twin";
import Viewer3D, { type Toggles } from "./components/Viewer3D";
import SessionList from "./components/SessionList";
import InspectPanel from "./components/InspectPanel";
import MeasurementsPanel from "./components/MeasurementsPanel";
import QueryBox from "./components/QueryBox";
import ProvenanceFooter from "./components/ProvenanceFooter";
import LiveScreen from "./components/LiveScreen";
import { useRoute } from "./lib/useRoute";
import { navigate } from "./lib/route";

export default function App() {
  const route = useRoute();
  if (route.kind === "live") return <LiveScreen />;
  return <SessionsApp routeSessionId={route.kind === "session" ? route.id : null} />;
}

function SessionsApp({ routeSessionId }: { routeSessionId: string | null }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(routeSessionId);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [measurements, setMeasurements] = useState<RoomMeasurementsResponse | null>(null);
  const [selectedPlaneId, setSelectedPlaneId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [toggles, setToggles] = useState<Toggles>({
    pointCloud: true,
    geometry: true,
    labels: true,
    cameras: true
  });

  // (Re)load the session list on mount and whenever the route names a session
  // (e.g. a live session that just finished), selecting the routed id if given.
  useEffect(() => {
    listSessions()
      .then((s) => {
        setSessions(s);
        setSelectedSessionId((current) => routeSessionId ?? current ?? (s.length > 0 ? s[0].id : null));
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [routeSessionId]);

  function selectSession(id: string) {
    setSelectedSessionId(id);
    navigate({ kind: "session", id });
  }

  useEffect(() => {
    if (!selectedSessionId) return;
    setTwin(null);
    setMeasurements(null);
    setSelectedPlaneId(null);
    Promise.all([getTwin(selectedSessionId), getMeasurements(selectedSessionId)])
      .then(([t, m]) => {
        setTwin(t);
        setMeasurements(m);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedSessionId]);

  const selectedPlane = useMemo(() => {
    if (!twin?.room_model || !selectedPlaneId) return null;
    return twin.room_model.planes.find((p) => p.id === selectedPlaneId) ?? null;
  }, [twin, selectedPlaneId]);

  function toggle(key: keyof Toggles) {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <button className="live-link" onClick={() => navigate({ kind: "live" })}>
          ● Live tracking
        </button>
        <SessionList sessions={sessions} selectedId={selectedSessionId} onSelect={selectSession} />
        {measurements && <MeasurementsPanel measurements={measurements} />}
        {selectedSessionId && <QueryBox sessionId={selectedSessionId} />}
        {twin && <InspectPanel plane={selectedPlane} sceneGraph={twin.scene_graph} />}
      </aside>

      <main className="viewer">
        {twin?.provenance.input_type === "synthetic" && (
          <div className="synthetic-banner">synthetic input — not physical-camera footage</div>
        )}

        <div className="toggles">
          <label>
            <input type="checkbox" checked={toggles.pointCloud} onChange={() => toggle("pointCloud")} /> Point cloud
          </label>
          <label>
            <input type="checkbox" checked={toggles.geometry} onChange={() => toggle("geometry")} /> Geometry
          </label>
          <label>
            <input type="checkbox" checked={toggles.labels} onChange={() => toggle("labels")} /> Labels
          </label>
          <label>
            <input type="checkbox" checked={toggles.cameras} onChange={() => toggle("cameras")} /> Cameras
          </label>
        </div>

        {error && <p className="error">{error}</p>}

        {selectedSessionId && twin ? (
          <Viewer3D
            sessionId={selectedSessionId}
            twin={twin}
            toggles={toggles}
            selectedPlaneId={selectedPlaneId}
            onSelectPlane={setSelectedPlaneId}
          />
        ) : (
          <p className="muted">Select a session to load its digital twin.</p>
        )}
      </main>

      {twin && <ProvenanceFooter provenance={twin.provenance} />}
    </div>
  );
}
