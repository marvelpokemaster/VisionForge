import { useCallback, useEffect, useMemo, useState } from "react";
import { listSessions, getTwin, getMeasurements, type RoomMeasurementsResponse, ApiError } from "./lib/api";
import { hasGeometry, loadSessionView } from "./lib/sessionLoad";
import type { Session, Twin } from "./types/twin";
import Viewer3D, { type Toggles } from "./components/Viewer3D";
import SessionList from "./components/SessionList";
import InspectPanel from "./components/InspectPanel";
import MeasurementsPanel from "./components/MeasurementsPanel";
import QueryBox from "./components/QueryBox";
import ProvenanceFooter from "./components/ProvenanceFooter";
import LiveScreen from "./components/LiveScreen";
import { useApiBase } from "./components/BackendField";
import FurniturePanel from "./components/FurniturePanel";
import AuthPanel from "./components/AuthPanel";
import type { PlacedFurniture } from "./types/furniture";
import { useRoute } from "./lib/useRoute";
import { navigate } from "./lib/route";

export default function App() {
  const route = useRoute();
  if (route.kind === "live") return <LiveScreen />;
  return <SessionsApp routeSessionId={route.kind === "session" ? route.id : null} />;
}

function SessionsApp({ routeSessionId }: { routeSessionId: string | null }) {
  const backend = useApiBase();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(routeSessionId);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [measurements, setMeasurements] = useState<RoomMeasurementsResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedPlaneId, setSelectedPlaneId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [placedFurniture, setPlacedFurniture] = useState<PlacedFurniture[]>([]);
  const [reloadTrigger, setReloadTrigger] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const reloadSession = useCallback(() => {
    setReloadTrigger((n) => n + 1);
  }, []);

  const [toggles, setToggles] = useState<Toggles>({
    pointCloud: true,
    geometry: true,
    labels: true,
    cameras: true,
    furniture: true,
  });

  useEffect(() => {
    setError(null);
    listSessions()
      .then((s) => {
        setSessions(s);
        setSelectedSessionId((current) => routeSessionId ?? current ?? (s.length > 0 ? s[0].id : null));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setSessions([]);
          setSelectedSessionId(null);
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [routeSessionId, backend, reloadTrigger]);

  function selectSession(id: string) {
    setSelectedSessionId(id);
    navigate({ kind: "session", id });
    setSidebarOpen(false); // Auto-close drawer on mobile when session selected
  }

  useEffect(() => {
    if (!selectedSessionId) return;
    setTwin(null);
    setMeasurements(null);
    setNotice(null);
    setSelectedPlaneId(null);
    let stale = false;
    loadSessionView(selectedSessionId, { getTwin, getMeasurements })
      .then((view) => {
        if (stale) return;
        setTwin(view.twin);
        setMeasurements(view.measurements);
        setNotice(view.notice);
      })
      .catch((err) => {
        if (!stale) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [selectedSessionId, backend, reloadTrigger]);

  const selectedPlane = useMemo(() => {
    if (!twin?.room_model?.planes || !selectedPlaneId) return null;
    return twin.room_model.planes.find((p) => p.id === selectedPlaneId) ?? null;
  }, [twin, selectedPlaneId]);

  function toggle(key: keyof Toggles) {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const stageStatus = twin ? Object.entries(twin.provenance.stage_status) : [];

  return (
    <div className="app-container">
      {/* Sleek Modern App Header */}
      <header className="app-header">
        <div className="header-brand">
          <span className="brand-logo-icon">📐</span>
          <div className="brand-text">
            <h1>VisionForge</h1>
            <span className="brand-badge">Spatial Twin</span>
          </div>
        </div>

        {/* Top Navigation Tabs */}
        <nav className="header-nav">
          <button type="button" className="nav-tab active">
            🏛️ 3D Spaces
          </button>
          <button type="button" className="nav-tab live-tab" onClick={() => navigate({ kind: "live" })}>
            <span className="live-dot" /> Live Scan
          </button>
        </nav>

        {/* Right Action Tools */}
        <div className="header-actions">
          <button
            type="button"
            className="header-icon-btn mobile-menu-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title="Toggle spaces sidebar"
          >
            {sidebarOpen ? "✕ Close" : "📁 Spaces"}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="app-body">
        {/* Collapsible Clean Sidebar */}
        <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
          <div className="sidebar-header">
            <h3>Saved Spaces ({sessions.length})</h3>
            <button type="button" className="sidebar-close-btn" onClick={() => setSidebarOpen(false)}>
              ✕
            </button>
          </div>

          <AuthPanel onAuthChange={reloadSession} />

          <SessionList sessions={sessions} selectedId={selectedSessionId} onSelect={selectSession} />

          {measurements && <MeasurementsPanel measurements={measurements} />}

          {selectedSessionId && twin && hasGeometry(twin) && (
            <FurniturePanel
              sessionId={selectedSessionId}
              twin={twin}
              placedFurniture={placedFurniture}
              onPlacedFurnitureChange={setPlacedFurniture}
              onSessionUpdated={reloadSession}
            />
          )}

          {selectedSessionId && <QueryBox sessionId={selectedSessionId} />}
          {twin && <InspectPanel plane={selectedPlane} sceneGraph={twin.scene_graph} />}
        </aside>

        {/* 3D Digital Twin Viewport */}
        <main className="viewer">
          {twin?.provenance.input_type === "synthetic" && (
            <div className="synthetic-banner">synthetic input — not physical-camera footage</div>
          )}

          {/* Floating Glassmorphism Layer Controls */}
          <div className="toggles-pill-bar">
            <label className="toggle-chip">
              <input type="checkbox" checked={toggles.pointCloud} onChange={() => toggle("pointCloud")} />
              <span>Point Cloud</span>
            </label>
            <label className="toggle-chip">
              <input type="checkbox" checked={toggles.geometry} onChange={() => toggle("geometry")} />
              <span>Planes</span>
            </label>
            <label className="toggle-chip">
              <input type="checkbox" checked={toggles.furniture ?? true} onChange={() => toggle("furniture" as any)} />
              <span>Furniture</span>
            </label>
            <label className="toggle-chip desktop-only">
              <input type="checkbox" checked={toggles.cameras} onChange={() => toggle("cameras")} />
              <span>Cameras</span>
            </label>
          </div>

          {error && <div className="viewer-error-toast">{error}</div>}

          {selectedSessionId && twin ? (
            hasGeometry(twin) ? (
              <>
                {notice && <p className="session-notice">{notice}</p>}
                <Viewer3D
                  sessionId={selectedSessionId}
                  twin={twin}
                  toggles={toggles}
                  selectedPlaneId={selectedPlaneId}
                  onSelectPlane={setSelectedPlaneId}
                  placedFurniture={placedFurniture}
                />
              </>
            ) : (
              <div className="session-notice session-notice-block" role="status">
                <p>
                  <strong>{selectedSessionId}</strong>: {notice ?? "no geometry"}
                </p>
                <ul className="stage-list">
                  {stageStatus.map(([stage, status]) => (
                    <li key={stage} className={`stage-${status}`}>
                      {stage}: {status}
                    </li>
                  ))}
                </ul>
                {twin.provenance.live && (
                  <p className="muted">
                    live session: {twin.provenance.frames ?? "?"} frames, {twin.provenance.keyframes ?? 0} keyframes,{" "}
                    {twin.provenance.map_size ?? 0} map points.
                  </p>
                )}
              </div>
            )
          ) : (
            <div className="empty-viewport-placeholder">
              <div className="placeholder-icon">📐</div>
              <h3>No Space Selected</h3>
              <p>Select a digital twin from Spaces or start a Live AR Scan.</p>
              <div className="placeholder-actions">
                <button type="button" className="primary-pill-btn" onClick={() => navigate({ kind: "live" })}>
                  ▶ Start Live Scan
                </button>
                <button type="button" className="secondary-pill-btn" onClick={() => setSidebarOpen(true)}>
                  📁 View Saved Spaces
                </button>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Floating Bottom Nav for Mobile */}
      <nav className="mobile-bottom-dock">
        <button
          type="button"
          className={`dock-btn ${sidebarOpen ? "active" : ""}`}
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          📁 <span className="dock-label">Spaces</span>
        </button>
        <button
          type="button"
          className="dock-btn live-dock-btn"
          onClick={() => navigate({ kind: "live" })}
        >
          📹 <span className="dock-label">Live Scan</span>
        </button>
      </nav>

      {twin && <ProvenanceFooter provenance={twin.provenance} />}
    </div>
  );
}
