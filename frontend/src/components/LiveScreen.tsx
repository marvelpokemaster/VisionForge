import { useCallback, useEffect, useRef, useState } from "react";
import Viewer3D, { type Toggles } from "./Viewer3D";
import { navigate } from "../lib/route";
import { registerBackGuard } from "../lib/backButton";
import AuthPanel from "./AuthPanel";
import { loadStoredIntrinsics } from "./IntrinsicsField";
import { configureMessage, type ParsedCameras } from "../live/intrinsics";
import { RECORD_KEY, readStored, writeStored } from "../lib/stored";
import { CameraSource, FileSource, type FrameSource } from "../live/source";
import { FramePump } from "../live/pump";
import { makeJpegEncoder, encodedSize } from "../live/encode";
import { currentLiveSocketUrl, currentLiveCloudUrl } from "../live/wsUrl";
import { getCurrentSession, getCurrentUser } from "../lib/supabase";
import { readAuthToken } from "../lib/backend";
import {
  addClientSkips,
  initialSummary,
  noGeometryReason,
  reduceStatus,
  type LiveStatusMessage,
  type LiveSummary
} from "../live/status";

type SourceKind = "camera" | "file";

interface FinishedReply {
  finished: true;
  session_id: string;
  run_dir: string;
  stage_status: Record<string, string>;
  frames: number;
  received: number;
  dropped: number;
  twin_updates: number;
  recording: { dir: string; index: string; received: number; processed: number; not_processed: number } | null;
}

const FPS = 10;
const MAX_WIDTH = 640;
const JPEG_QUALITY = 0.7;

function defaultSessionId(): string {
  return `live-${Date.now()}`;
}

export default function LiveScreen() {
  const [sessionId, setSessionId] = useState(defaultSessionId);
  const [sourceKind, setSourceKind] = useState<SourceKind>("camera");
  const [file, setFile] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [summary, setSummary] = useState<LiveSummary>(initialSummary);
  const [finished, setFinished] = useState<FinishedReply | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendSize, setSendSize] = useState<{ width: number; height: number } | null>(null);
  const [skipBreakdown, setSkipBreakdown] = useState<string>("");
  const [sourceEnded, setSourceEnded] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [toggles] = useState<Toggles>({ pointCloud: true, geometry: true, labels: true, cameras: true });
  // "Record frames": the server keeps every received JPEG for offline replay (default off, persisted)
  const [record, setRecord] = useState<boolean>(() => readStored(RECORD_KEY) === "1");
  // calibration from `visionforge calibrate` (persisted); null -> the phone-default stopgap
  const [cameras] = useState<ParsedCameras | null>(loadStoredIntrinsics);

  useEffect(() => {
    void getCurrentUser().then((u) => {
      setIsAuthenticated(Boolean(u) || Boolean(readAuthToken()));
    });
  }, []);

  function toggleRecord(on: boolean) {
    setRecord(on);
    writeStored(RECORD_KEY, on ? "1" : null);
  }

  const videoRef = useRef<HTMLVideoElement>(null);
  const sourceRef = useRef<FrameSource | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const pumpRef = useRef<FramePump | null>(null);
  const skipsRef = useRef(0);
  const stoppingRef = useRef(false);

  const teardown = useCallback(() => {
    pumpRef.current?.stop();
    pumpRef.current = null;
    sourceRef.current?.stop();
    sourceRef.current = null;
    const ws = socketRef.current;
    socketRef.current = null;
    if (ws && ws.readyState <= 1) ws.close();
    stoppingRef.current = false;
    setRunning(false);
    setStopping(false);
  }, []);

  useEffect(() => teardown, [teardown]);

  // Android back while a session runs = Stop (the finished reply then opens
  // the session view); otherwise lib/backButton.ts returns to the sessions list.
  useEffect(() => {
    if (!running) return;
    return registerBackGuard(() => {
      stop();
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  // fold the pump's client-side skips into the summary a few times a second,
  // and stop by itself when a file source has played to its end
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => {
      const n = skipsRef.current;
      if (n > 0) {
        skipsRef.current = 0;
        setSummary((s) => addClientSkips(s, n));
      }
      const pump = pumpRef.current;
      if (pump) {
        const k = pump.stats.skipped;
        setSkipBreakdown(`busy ${k.busy} / rate ${k.rate} / buffer ${k.buffer} / no-frame ${k["no-frame"]}`);
      }
      if (sourceRef.current?.ended && !stoppingRef.current) {
        setSourceEnded(true);
        stop();
      }
    }, 500);
    return () => clearInterval(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  async function start() {
    setError(null);
    setFinished(null);
    setSourceEnded(false);
    setSkipBreakdown("");
    setSummary(initialSummary());

    // Verify authentication before attempting connection
    const currentSession = await getCurrentSession();
    const token = currentSession?.access_token ?? readAuthToken();
    if (!token) {
      setError("Please sign in to your Supabase account to start live tracking.");
      setShowAdvanced(true);
      return;
    }

    const video = videoRef.current;
    if (!video) return;
    if (sourceKind === "file" && !file) {
      setError("Choose a video file first.");
      return;
    }

    const source: FrameSource = sourceKind === "camera" ? new CameraSource(video) : new FileSource(video, file as File);
    sourceRef.current = source;
    let size;
    try {
      size = await source.start();
    } catch (err) {
      setError(`Could not start ${sourceKind}: ${err instanceof Error ? err.message : String(err)}`);
      source.stop();
      sourceRef.current = null;
      return;
    }
    const sent = encodedSize(size, MAX_WIDTH);
    setSendSize(sent);

    const url = currentLiveSocketUrl(sessionId, window.location, token);
    const ws = new WebSocket(url);
    socketRef.current = ws;
    const pump = new FramePump(ws, makeJpegEncoder(source, MAX_WIDTH, JPEG_QUALITY), { fps: FPS });
    pump.onSkip = () => {
      skipsRef.current += 1;
    };
    pumpRef.current = pump;

    ws.onopen = () => {
      pump.start(sent.width, sent.height, configureMessage(sent, { cameras, record }));
      setRunning(true);
    };

    ws.onmessage = (ev) => {
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      const m = msg as Record<string, unknown>;
      if (m.finished === true) {
        const reply = m as unknown as FinishedReply;
        setFinished(reply);
        teardown();
        navigate({ kind: "session", id: reply.session_id });
        return;
      }
      if (typeof m.error === "string") {
        setError(m.error);
        return;
      }
      if (typeof m.state === "string") {
        setSummary((s) => reduceStatus(s, m as unknown as LiveStatusMessage, performance.now()));
      }
    };

    ws.onerror = () => {
      if (!token) {
        setError("Authentication required: Please sign in to connect to live tracking.");
      } else {
        setError(`WebSocket connection error — please ensure cloud backend is reachable.`);
      }
    };

    ws.onclose = (ev) => {
      if (ev.code !== 1000 && ev.code !== 1005) {
        if (ev.code === 4401) {
          setError("Authentication required or expired. Please sign in to your account.");
        } else if (ev.code === 1006) {
          // 1006 is abnormal closure, commonly triggered by 401 handshake rejection behind proxies
          const hasToken = Boolean(readAuthToken());
          setError(
            !hasToken
              ? "Authentication required (1006). Please sign in before starting live tracking."
              : "Live socket connection closed unexpectedly (1006). Please check network and retry."
          );
        } else if (ev.code === 4409) {
          setError(`Session '${sessionId}' is already active. Please generate a new session ID.`);
        } else {
          setError(`Socket closed: ${ev.code} ${ev.reason || ""}`.trim());
        }
      }
      teardown();
    };
  }

  function stop() {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    setStopping(true);
    pumpRef.current?.stop();
    sourceRef.current?.stop();
  }

  const twin = summary.lastTwin;
  const reason = noGeometryReason(twin);
  const viewerTwin = twin?.room_model?.planes && twin.room_model.planes.length > 0 ? twin : null;

  return (
    <div className="live-screen">
      {/* Sleek App Navigation Bar */}
      <header className="live-header">
        <button type="button" className="nav-back-btn" onClick={() => navigate({ kind: "home" })} title="Back to Sessions">
          ← Spaces
        </button>
        <div className="live-header-title">
          <h2>Live Spatial Scanner</h2>
          <span className={`status-dot-badge status-${summary.state.toLowerCase()}`}>
            <span className="dot" /> {running ? summary.state : "Ready to scan"}
          </span>
        </div>
        <button
          type="button"
          className="settings-toggle-btn"
          onClick={() => setShowAdvanced(!showAdvanced)}
          title="Toggle settings & backend"
        >
          ⚙ Settings
        </button>
      </header>

      {/* Collapsible Settings Drawer */}
      {showAdvanced && (
        <div className="live-settings-drawer">
          <div style={{ marginBottom: "12px" }}>
            <AuthPanel onAuthChange={(u) => setIsAuthenticated(Boolean(u) || Boolean(readAuthToken()))} />
          </div>
          <div className="settings-grid">
            <label className="field-group">
              <span className="field-label">Session ID</span>
              <input value={sessionId} disabled={running} onChange={(e) => setSessionId(e.target.value)} />
            </label>
            <label className="field-group">
              <span className="field-label">Input Source</span>
              <select value={sourceKind} disabled={running} onChange={(e) => setSourceKind(e.target.value as SourceKind)}>
                <option value="camera">Live Phone Camera</option>
                <option value="file">Pre-recorded Video</option>
              </select>
            </label>
            {sourceKind === "file" && (
              <label className="field-group">
                <span className="field-label">Choose File</span>
                <input type="file" accept="video/*" disabled={running} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            )}
            <label className="checkbox-group">
              <input type="checkbox" checked={record} disabled={running} onChange={(e) => toggleRecord(e.target.checked)} />
              <span>Record raw video frames</span>
            </label>
            {sendSize && (
              <div className="field-hint muted" style={{ fontSize: "11px" }}>
                Resolution: {sendSize.width}×{sendSize.height}
              </div>
            )}
            {skipBreakdown && (
              <div className="field-hint muted" style={{ fontSize: "11px" }}>
                Client skips: {skipBreakdown}
              </div>
            )}
            {sourceEnded && (
              <div className="field-hint muted" style={{ fontSize: "11px" }}>
                Source video stream completed
              </div>
            )}
          </div>
        </div>
      )}

      {/* Auth Prompt Banner if not signed in */}
      {isAuthenticated === false && (
        <div className="auth-alert-banner">
          <div style={{ width: "100%" }}>
            <div style={{ marginBottom: "6px", fontSize: "0.85em", fontWeight: 500 }}>
              🔒 Sign in to save and stream 3D digital twins to your cloud storage:
            </div>
            <AuthPanel onAuthChange={(u) => setIsAuthenticated(Boolean(u) || Boolean(readAuthToken()))} />
          </div>
        </div>
      )}

      {/* Error Banner with helpful action */}
      {error && (
        <div className="live-error-banner" role="alert">
          <span className="error-icon">⚠️</span>
          <span className="error-text">{error}</span>
        </div>
      )}

      {/* AR Scanning Viewport */}
      <div className="live-viewport-card">
        <div className="viewfinder-container">
          <video ref={videoRef} playsInline muted className="viewfinder-video" />
          
          {/* Subtle AR Reticle Overlay */}
          <div className={`ar-reticle-overlay ${running ? "active" : ""}`}>
            <div className="reticle-corner top-left" />
            <div className="reticle-corner top-right" />
            <div className="reticle-corner bottom-left" />
            <div className="reticle-corner bottom-right" />
            {!running && (
              <div className="ar-guidance-pill">
                <span>Point camera at walls & walk sideways slowly for depth parallax</span>
              </div>
            )}
          </div>

          {/* Minimal Live Stats Pill Bar */}
          {running && (
            <div className="live-hud-pill-bar">
              <div className="hud-pill">
                <span className="hud-label">Tracked</span>
                <span className="hud-val">{summary.nTracked}</span>
              </div>
              <div className="hud-pill">
                <span className="hud-label">Map Pts</span>
                <span className="hud-val">{summary.mapSize}</span>
              </div>
              <div className="hud-pill">
                <span className="hud-label">Keyframes</span>
                <span className="hud-val">{summary.nKeyframes}</span>
              </div>
              <div className="hud-pill">
                <span className="hud-label">FPS</span>
                <span className="hud-val">{summary.fpsMeasured !== null ? summary.fpsMeasured.toFixed(0) : "10"}</span>
              </div>
            </div>
          )}
        </div>

        {/* 3D Geometry Map Preview */}
        {viewerTwin ? (
          <div className="live-viewer-sidecar">
            <Viewer3D
              sessionId={sessionId}
              twin={viewerTwin}
              toggles={toggles}
              selectedPlaneId={null}
              onSelectPlane={() => undefined}
              cloudUrl={currentLiveCloudUrl(sessionId)}
            />
          </div>
        ) : running && reason ? (
          <div className="live-sidecar-placeholder" title={reason}>
            <span className="placeholder-icon">📐</span>
            <span className="placeholder-text">{reason}</span>
          </div>
        ) : null}
      </div>

      {/* Floating Tactical Bottom Bar */}
      <div className="live-action-dock">
        {!running ? (
          <button
            type="button"
            className="action-pill-btn start-scan-btn"
            onClick={() => void start()}
            disabled={stopping}
          >
            <span className="btn-icon">▶</span> Start Scanning
          </button>
        ) : (
          <button
            type="button"
            className="action-pill-btn stop-scan-btn"
            onClick={stop}
            disabled={stopping}
          >
            <span className="btn-icon">⏹</span> {stopping ? "Processing 3D Twin…" : "Finish & Save Space"}
          </button>
        )}
      </div>

      {/* Completion Toast */}
      {finished && (
        <div className="live-guidance-toast finished">
          🎉 Scan complete! Processed {finished.frames} frames ({finished.twin_updates} spatial updates) for {finished.session_id}.
        </div>
      )}

      {/* Live Status Guidance Notice */}
      {running && summary.state === "INITIALIZING" && (
        <div className="live-guidance-toast initializing">
          🚶 Move camera sideways 1–2 meters while facing the room to establish depth parallax.
        </div>
      )}
      {running && summary.state === "LOST" && (
        <div className="live-guidance-toast lost">
          🔄 Tracking lost: pan slowly across the room to re-localize camera.
        </div>
      )}
    </div>
  );
}
