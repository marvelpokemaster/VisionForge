import { useCallback, useEffect, useRef, useState } from "react";
import Viewer3D, { type Toggles } from "./Viewer3D";
import { navigate } from "../lib/route";
import { registerBackGuard } from "../lib/backButton";
import BackendField from "./BackendField";
import { CameraSource, FileSource, type FrameSource } from "../live/source";
import { FramePump } from "../live/pump";
import { makeJpegEncoder, encodedSize } from "../live/encode";
import { currentLiveSocketUrl, currentLiveCloudUrl } from "../live/wsUrl";
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
  const [toggles] = useState<Toggles>({ pointCloud: true, geometry: true, labels: true, cameras: true });

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

    const url = currentLiveSocketUrl(sessionId, window.location);
    const ws = new WebSocket(url);
    socketRef.current = ws;
    const pump = new FramePump(ws, makeJpegEncoder(source, MAX_WIDTH, JPEG_QUALITY), { fps: FPS });
    pump.onSkip = () => {
      skipsRef.current += 1;
    };
    pumpRef.current = pump;

    ws.onopen = () => {
      pump.start(sent.width, sent.height);
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
    ws.onerror = () => setError(`WebSocket error (${url}) — is the backend running and reachable?`);
    ws.onclose = (ev) => {
      if (ev.code !== 1000 && ev.code !== 1005) {
        setError(`Socket closed: ${ev.code} ${ev.reason || ""}`.trim());
      }
      teardown();
    };
  }

  function stop() {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    setStopping(true);
    pumpRef.current?.stop(); // sends {"cmd":"finish"}; the finished reply closes the loop
    sourceRef.current?.stop();
  }

  const twin = summary.lastTwin;
  const reason = noGeometryReason(twin);
  const viewerTwin = twin && twin.room_model && twin.room_model.planes.length > 0 ? twin : null;

  return (
    <div className="live-screen">
      <header className="live-header">
        <button className="link" onClick={() => navigate({ kind: "home" })}>
          ← Sessions
        </button>
        <h2>Live tracking</h2>
        <BackendField disabled={running || stopping} />
      </header>

      <div className="live-controls">
        <label>
          Session id{" "}
          <input value={sessionId} disabled={running} onChange={(e) => setSessionId(e.target.value)} />
        </label>
        <label>
          Source{" "}
          <select value={sourceKind} disabled={running} onChange={(e) => setSourceKind(e.target.value as SourceKind)}>
            <option value="camera">camera</option>
            <option value="file">video file</option>
          </select>
        </label>
        {sourceKind === "file" && (
          <input type="file" accept="video/*" disabled={running} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        )}
        {!running ? (
          <button className="primary" onClick={() => void start()} disabled={stopping}>
            Start
          </button>
        ) : (
          <button className="danger" onClick={stop} disabled={stopping}>
            {stopping ? "Finishing…" : "Stop"}
          </button>
        )}
      </div>

      <div className={`live-state live-state-${summary.state.toLowerCase()}`} role="status" aria-live="polite">
        {summary.state === "IDLE" ? "IDLE" : summary.state}
        {summary.state === "LOST" && <span className="live-state-sub">pose unknown — move the camera back to known area</span>}
        {summary.state === "INITIALIZING" && <span className="live-state-sub">translate the camera sideways (parallax needed)</span>}
      </div>

      {error && <p className="error">{error}</p>}

      <div className="live-status-strip">
        <span>frame {summary.frameIndex ?? "–"}</span>
        <span>tracked {summary.nTracked}</span>
        <span>inliers {summary.nInliers}</span>
        <span>map {summary.mapSize}</span>
        <span>keyframes {summary.nKeyframes}</span>
        <span>segment {summary.segment ?? "–"}</span>
        <span title="frames the server dropped (backpressure)">dropped {summary.dropped}</span>
        <span title={`frames this client chose not to send (${skipBreakdown || "no skips yet"})`}>
          skipped {summary.skippedClient}
          {skipBreakdown && <small> ({skipBreakdown})</small>}
        </span>
        {sourceEnded && <span className="live-ended">video ended — finishing</span>}
        <span>{summary.fpsMeasured !== null ? `${summary.fpsMeasured.toFixed(1)} fps` : "– fps"}</span>
        <span>twin updates {summary.twinUpdates}</span>
        <span>lost episodes {summary.lostEpisodes.length}</span>
        {sendSize && (
          <span>
            sending {sendSize.width}×{sendSize.height}
            {summary.processedSize ? ` → tracked at ${summary.processedSize[0]}×${summary.processedSize[1]}` : ""}
          </span>
        )}
        {summary.intrinsicsSource && <span>intrinsics: {summary.intrinsicsSource}</span>}
      </div>

      <div className="live-body">
        <div className="live-preview">
          <video ref={videoRef} playsInline muted />
        </div>
        <div className="live-viewer">
          {viewerTwin ? (
            <Viewer3D
              sessionId={sessionId}
              twin={viewerTwin}
              toggles={toggles}
              selectedPlaneId={null}
              onSelectPlane={() => undefined}
              cloudUrl={currentLiveCloudUrl(sessionId)}
            />
          ) : (
            <p className="muted live-placeholder">
              {reason ? `no geometry yet: ${reason}` : running ? "waiting for the first twin update…" : "not running"}
            </p>
          )}
        </div>
      </div>

      {finished && (
        <p className="muted">
          finished: {finished.frames} frames processed, {finished.dropped} dropped, {finished.twin_updates} twin updates →{" "}
          {Object.entries(finished.stage_status)
            .map(([k, v]) => `${k}: ${v}`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}
