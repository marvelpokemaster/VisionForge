import { useState } from "react";
import type { RoomMeasurementsResponse } from "../lib/api";
import { askQuestion } from "../lib/api";
import { calibrateScale } from "../lib/furnitureApi";

interface Props {
  sessionId: string;
  measurements: RoomMeasurementsResponse | null;
  onMeasurementsUpdated: () => void;
}

const QUICK_QUESTIONS = [
  "What is the room height?",
  "Which wall is largest?",
  "Which walls are parallel?",
  "How far is camera from wall?",
  "What are the room dimensions?",
];

export default function MeasureTab({
  sessionId,
  measurements,
  onMeasurementsUpdated,
}: Props) {
  const [queryInput, setQueryInput] = useState("");
  const [queryResult, setQueryResult] = useState<any | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);

  // Calibration state
  const [calibRefType, setCalibRefType] = useState<"room_length" | "room_width">("room_length");
  const [knownDistance, setKnownDistance] = useState<number>(
    measurements?.length?.value ?? 5.0
  );
  const [calibStatus, setCalibStatus] = useState<string | null>(null);

  const handleRunQuery = async (questionText: string) => {
    if (!questionText.trim()) return;
    setQueryLoading(true);
    setQueryResult(null);
    try {
      const res = await askQuestion(sessionId, questionText);
      setQueryResult(res);
    } catch (err) {
      setQueryResult({
        supported: false,
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setQueryLoading(false);
    }
  };

  const handleCalibrate = async () => {
    try {
      const res = await calibrateScale(sessionId, calibRefType, knownDistance);
      if (res.success) {
        setCalibStatus(`✓ Scaled to ${knownDistance}m (factor: ${res.scale.scale_factor})`);
        onMeasurementsUpdated();
        setTimeout(() => setCalibStatus(null), 3000);
      }
    } catch (err) {
      setCalibStatus(err instanceof Error ? err.message : "Calibration failed");
    }
  };

  return (
    <div className="measure-tab-container">
      {/* Metric Dimension Cards */}
      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Room Dimensions</h4>
          <span className="subtitle-text">Metric Scale Calibrated</span>
        </div>

        <div className="dimensions-grid">
          <div className="dim-card">
            <span className="dim-title">Room Length</span>
            <span className="dim-value">
              {measurements?.length?.value ? `${measurements.length.value} m` : "—"}
            </span>
            <span className="dim-method">{measurements?.length?.method ?? "bounding box"}</span>
          </div>

          <div className="dim-card">
            <span className="dim-title">Room Width</span>
            <span className="dim-value">
              {measurements?.width?.value ? `${measurements.width.value} m` : "—"}
            </span>
            <span className="dim-method">{measurements?.width?.method ?? "bounding box"}</span>
          </div>

          <div className="dim-card">
            <span className="dim-title">Ceiling Height</span>
            <span className="dim-value accent">
              {measurements?.height?.value ? `${measurements.height.value} m` : "—"}
            </span>
            <span className="dim-method">{measurements?.height?.method ?? "floor to ceiling"}</span>
          </div>

          <div className="dim-card">
            <span className="dim-title">Floor Area</span>
            <span className="dim-value accent">
              {measurements?.floor_area?.value ? `${measurements.floor_area.value} m²` : "—"}
            </span>
            <span className="dim-method">{measurements?.floor_area?.method ?? "polygon area"}</span>
          </div>
        </div>
      </div>

      {/* Scale Calibration Slider */}
      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Metric Scale Calibration</h4>
          <span className="subtitle-text">Tape Measure Match</span>
        </div>

        <div className="calibration-box">
          <p className="calib-hint">
            Match the 3D twin to a known tape measurement along the room length or width:
          </p>

          <div className="calib-row">
            <select
              value={calibRefType}
              onChange={(e) => setCalibRefType(e.target.value as any)}
              className="studio-select"
            >
              <option value="room_length">Reference: Room Length</option>
              <option value="room_width">Reference: Room Width</option>
            </select>

            <div className="input-with-unit">
              <input
                type="number"
                step="0.1"
                min="1.0"
                max="30.0"
                value={knownDistance}
                onChange={(e) => setKnownDistance(parseFloat(e.target.value))}
                className="calib-num-input"
              />
              <span className="unit-label">meters</span>
            </div>
          </div>

          <button
            type="button"
            className="action-btn apply-scale-btn"
            onClick={handleCalibrate}
          >
            Apply Real Scale
          </button>
          {calibStatus && <p className="calib-status-msg">{calibStatus}</p>}
        </div>
      </div>

      {/* Room Query Assistant */}
      <div className="dock-section">
        <div className="dock-section-title">
          <h4>Room Assistant</h4>
          <span className="subtitle-text">Spatial Scene Graph NLP</span>
        </div>

        {/* Quick query tags */}
        <div className="quick-query-tags">
          {QUICK_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              className="query-chip"
              onClick={() => {
                setQueryInput(q);
                handleRunQuery(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>

        <form
          className="query-input-form"
          onSubmit={(e) => {
            e.preventDefault();
            handleRunQuery(queryInput);
          }}
        >
          <input
            type="text"
            placeholder="Ask anything about this room..."
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            className="query-text-input"
          />
          <button type="submit" className="query-submit-btn" disabled={queryLoading}>
            {queryLoading ? "..." : "Ask"}
          </button>
        </form>

        {queryResult && (
          <div className="query-answer-card">
            <div className="answer-header">
              <span className="answer-badge">
                {queryResult.supported ? "Spatial Result" : "Notice"}
              </span>
            </div>
            {queryResult.answer ? (
              <pre className="answer-pre">
                {typeof queryResult.answer === "object"
                  ? JSON.stringify(queryResult.answer, null, 2)
                  : String(queryResult.answer)}
              </pre>
            ) : (
              <p className="answer-text">{queryResult.message ?? "No result found."}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
