import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  listSessions,
  getTwin,
  getMeasurements,
  type RoomMeasurementsResponse,
} from "./lib/api";
import { hasGeometry, loadSessionView } from "./lib/sessionLoad";
import type { Session, Twin } from "./types/twin";
import type { PlacedFurniture } from "./types/furniture";
import StudioViewer, { type StudioViewerRef } from "./components/StudioViewer";
import FurnishTab from "./components/FurnishTab";
import MeasureTab from "./components/MeasureTab";
import SurfaceInspectorTab from "./components/SurfaceInspectorTab";
import UploadStudio from "./components/UploadStudio";
import BackendField, { useApiBase } from "./components/BackendField";
import AuthPanel from "./components/AuthPanel";
import LiveScreen from "./components/LiveScreen";
import { useRoute } from "./lib/useRoute";
import { navigate } from "./lib/route";
import { getCurrentUser, getSupabaseClient } from "./lib/supabase";
import type { User } from "@supabase/supabase-js";

export type StudioTab = "viewer" | "furnish" | "measure" | "upload";

export default function App() {
  const route = useRoute();
  if (route.kind === "live") return <LiveScreen />;
  return <StudioApp />;
}

function StudioApp() {
  const route = useRoute();
  const backend = useApiBase();

  const [activeTab, setActiveTab] = useState<StudioTab>("viewer");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>("final_demo");
  const [twin, setTwin] = useState<Twin | null>(null);
  const [measurements, setMeasurements] = useState<RoomMeasurementsResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedPlaneId, setSelectedPlaneId] = useState<string | null>(null);
  const [selectedFurnitureId, setSelectedFurnitureId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [placedFurniture, setPlacedFurniture] = useState<PlacedFurniture[]>([]);
  const [reloadTrigger, setReloadTrigger] = useState(0);
  const [authUser, setAuthUser] = useState<User | null>(null);

  // Studio viewer ref for snapshots & gizmos
  const viewerRef = useRef<StudioViewerRef>(null);

  // Settings / Backend drawer toggle
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    void getCurrentUser().then(setAuthUser);
    const c = getSupabaseClient();
    if (!c) return;
    const { data: listener } = c.auth.onAuthStateChange((_event, session) => {
      setAuthUser(session?.user ?? null);
    });
    return () => {
      listener.subscription.unsubscribe();
    };
  }, []);

  const reloadSession = useCallback(() => {
    setReloadTrigger((n) => n + 1);
  }, []);

  // Load session list on mount and on route change
  useEffect(() => {
    setError(null);
    listSessions()
      .then((s) => {
        setSessions(s);
        if (s.length > 0) {
          const routeId = route.kind === "session" ? route.id : null;
          setSelectedSessionId((current) => routeId ?? current ?? s[0].id);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [route, backend, reloadTrigger]);

  // Load twin and measurements whenever selectedSessionId changes
  useEffect(() => {
    if (!selectedSessionId) return;
    setTwin(null);
    setMeasurements(null);
    setNotice(null);
    setSelectedPlaneId(null);
    setSelectedFurnitureId(null);
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

  const selectSession = (id: string) => {
    setSelectedSessionId(id);
    navigate({ kind: "session", id });
  };

  const handleUploadComplete = (newSessionId: string) => {
    setSelectedSessionId(newSessionId);
    setActiveTab("viewer");
    reloadSession();
  };

  const activeSessionTitle =
    selectedSessionId === "final_demo"
      ? "Scandinavian Living Room"
      : selectedSessionId === "live_synth_30"
      ? "Modern Studio Loft"
      : selectedSessionId;

  // 1-Click Snapshot Handler
  const handleSnapshot = () => {
    if (viewerRef.current) {
      viewerRef.current.takeSnapshot(`visionforge-${selectedSessionId}-snapshot.png`);
    }
  };

  // 1-Click JSON Export Handler
  const handleExportJSON = () => {
    const exportData = {
      app: "VisionForge Studio",
      session_id: selectedSessionId,
      exported_at: new Date().toISOString(),
      room_name: activeSessionTitle,
      room_measurements: measurements,
      room_model: twin?.room_model,
      placed_furniture: placedFurniture,
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.download = `visionforge-${selectedSessionId}-layout.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="studio-app">
      {/* Top Architectural Navigation Bar */}
      <header className="studio-navbar">
        <div className="navbar-left">
          <div className="brand-group" onClick={() => setActiveTab("viewer")}>
            <div className="brand-logo-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                <line x1="12" y1="22.08" x2="12" y2="12" />
              </svg>
            </div>
            <div className="brand-title">
              <span className="brand-main">VisionForge</span>
              <span className="brand-tag">3D Room Studio</span>
            </div>
          </div>

          {/* Active Room Dropdown Selector */}
          <div className="active-room-dropdown-wrapper">
            <span className="room-status-dot" />
            <select
              value={selectedSessionId}
              onChange={(e) => selectSession(e.target.value)}
              className="room-select-dropdown"
            >
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id === "final_demo"
                    ? "Scandinavian Living Room (Real 5.4m × 3.9m)"
                    : s.id === "live_synth_30"
                    ? "Modern Studio Loft (6.2m × 4.5m)"
                    : `Room Scan: ${s.id}`}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 4 Core Workflow Tabs */}
        <nav className="navbar-tabs">
          <button
            type="button"
            className={`nav-tab ${activeTab === "viewer" ? "active" : ""}`}
            onClick={() => setActiveTab("viewer")}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.12 6.4-6.05-4.06a2 2 0 0 0-2.17-.05L2.9 8.4a2 2 0 0 0-.9 1.66v7.88a2 2 0 0 0 .93 1.7l6.05 4.06a2 2 0 0 0 2.17.05l9.95-6.1a2 2 0 0 0 .9-1.66V9.1c0-.7-.37-1.35-.98-1.7z" />
              <polyline points="3.29 7 12 12 20.71 7" />
            </svg>
            <span>3D Room</span>
          </button>

          <button
            type="button"
            className={`nav-tab ${activeTab === "furnish" ? "active" : ""}`}
            onClick={() => setActiveTab("furnish")}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19v-9a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9" />
              <path d="M2 19h20" />
              <path d="M6 8V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v3" />
            </svg>
            <span>Furnish & Fit</span>
          </button>

          <button
            type="button"
            className={`nav-tab ${activeTab === "measure" ? "active" : ""}`}
            onClick={() => setActiveTab("measure")}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <span>Measure & Insights</span>
          </button>

          <button
            type="button"
            className={`nav-tab upload-tab-btn ${activeTab === "upload" ? "active" : ""}`}
            onClick={() => setActiveTab("upload")}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span>Scan / Upload</span>
          </button>
        </nav>

        {/* 1-Click Snapshot & Export Actions */}
        <div className="navbar-right">
          <button
            type="button"
            className="navbar-action-btn snapshot-btn"
            onClick={handleSnapshot}
            title="Export High-Res PNG Floor Plan"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
            <span>Snapshot</span>
          </button>

          <button
            type="button"
            className="navbar-action-btn export-json-btn"
            onClick={handleExportJSON}
            title="Download Digital Twin & Layout JSON"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            <span>Export</span>
          </button>

          <button
            type="button"
            className={`settings-toggle-btn ${authUser ? "authenticated" : ""}`}
            onClick={() => setShowSettings(!showSettings)}
            title="Supabase Cloud & Backend Settings"
          >
            <span className={`supabase-status-dot ${authUser ? "online" : "ready"}`} />
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            <span className="settings-btn-text">
              {authUser ? authUser.email?.split("@")[0] : "Supabase Cloud"}
            </span>
          </button>
        </div>
      </header>

      {/* Main Studio Viewport & Docks */}
      <main className="studio-main-stage">
        {/* Persistent 3D Three.js Studio Viewer */}
        <div className="viewer-viewport-pane">
          {twin && hasGeometry(twin) ? (
            <StudioViewer
              ref={viewerRef}
              sessionId={selectedSessionId}
              twin={twin}
              selectedPlaneId={selectedPlaneId}
              onSelectPlane={(id) => {
                setSelectedPlaneId(id);
                if (id) {
                  setSelectedFurnitureId(null);
                  setActiveTab("viewer");
                }
              }}
              placedFurniture={placedFurniture}
              onPlacedFurnitureChange={setPlacedFurniture}
              selectedFurnitureId={selectedFurnitureId}
              onSelectFurniture={(id) => {
                setSelectedFurnitureId(id);
                if (id) {
                  setSelectedPlaneId(null);
                  setActiveTab("furnish");
                }
              }}
            />
          ) : (
            <div className="studio-empty-notice">
              <h3>{activeSessionTitle}</h3>
              <p>{notice ?? "No architectural geometry generated yet."}</p>
              <button
                type="button"
                className="action-btn"
                onClick={() => setActiveTab("upload")}
              >
                Scan or Upload Video
              </button>
            </div>
          )}

          {error && <div className="studio-error-toast">{error}</div>}
        </div>

        {/* Dynamic Studio Dock (Right Sidebar) */}
        {activeTab !== "upload" && (
          <aside className="studio-dock">
            {activeTab === "viewer" && (
              <SurfaceInspectorTab
                plane={selectedPlane}
                sceneGraph={twin?.scene_graph ?? null}
                onClearSelection={() => setSelectedPlaneId(null)}
              />
            )}

            {activeTab === "furnish" && twin && hasGeometry(twin) && (
              <FurnishTab
                sessionId={selectedSessionId}
                twin={twin}
                placedFurniture={placedFurniture}
                onPlacedFurnitureChange={setPlacedFurniture}
                onSessionUpdated={reloadSession}
                selectedFurnitureId={selectedFurnitureId}
                onSelectFurniture={setSelectedFurnitureId}
              />
            )}

            {activeTab === "measure" && (
              <MeasureTab
                sessionId={selectedSessionId}
                measurements={measurements}
                onMeasurementsUpdated={reloadSession}
              />
            )}
          </aside>
        )}

        {/* Full-Screen Scan / Upload Experience */}
        {activeTab === "upload" && (
          <div className="upload-studio-overlay">
            <UploadStudio
              onSessionReady={handleUploadComplete}
              onCancel={() => setActiveTab("viewer")}
            />
          </div>
        )}

        {/* Settings & Auth Slide-over */}
        {showSettings && (
          <div className="settings-backdrop" onClick={() => setShowSettings(false)}>
            <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
              <div className="settings-header">
                <h3>Studio Configuration</h3>
                <button
                  type="button"
                  className="close-settings-btn"
                  onClick={() => setShowSettings(false)}
                >
                  ✕
                </button>
              </div>
              <button type="button" className="live-link" onClick={() => { setShowSettings(false); navigate({ kind: "live" }); }}>
                ● Live tracking
              </button>
              <AuthPanel onAuthChange={reloadSession} />
              <BackendField />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
