import { useState } from "react";
import { parseCamerasJson, type ParsedCameras } from "../live/intrinsics";
import { INTRINSICS_KEY, readStored, writeStored } from "../lib/stored";

interface Props {
  value: ParsedCameras | null;
  onChange: (next: ParsedCameras | null) => void;
  disabled?: boolean;
}

/** Load the persisted calibration, if any (invalid text is dropped). */
export function loadStoredIntrinsics(): ParsedCameras | null {
  const text = readStored(INTRINSICS_KEY);
  if (!text) return null;
  try {
    return parseCamerasJson(text);
  } catch {
    return null;
  }
}

export function describeIntrinsics(p: ParsedCameras | null): string {
  if (!p) return "none: sending phone default (0.8 × longer side, stopgap)";
  const c = p.cameras[0];
  const params = c.camera_params.map((v) => (Number.isInteger(v) ? String(v) : v.toFixed(3))).join(", ");
  return `${c.camera_model} [${params}]${p.size ? ` @ ${p.size[0]}×${p.size[1]}` : ""}${c.name ? ` (${c.name})` : ""}`;
}

/** "Intrinsics" field: paste the JSON `visionforge calibrate` wrote (or a
 * cameras.json), or load the file; persisted in localStorage; sent as
 * intrinsics_from_cameras in the configure message. */
export default function IntrinsicsField({ value, onChange, disabled = false }: Props) {
  const [draft, setDraft] = useState<string>(() => readStored(INTRINSICS_KEY) ?? "");
  const [problem, setProblem] = useState<string | null>(null);

  function apply(text: string) {
    const trimmed = text.trim();
    if (trimmed === "") {
      setProblem(null);
      writeStored(INTRINSICS_KEY, null);
      onChange(null);
      return;
    }
    try {
      const parsed = parseCamerasJson(trimmed);
      setProblem(null);
      writeStored(INTRINSICS_KEY, trimmed);
      onChange(parsed);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  }

  async function loadFile(file: File | null) {
    if (!file) return;
    const text = await file.text();
    setDraft(text);
    apply(text);
  }

  return (
    <div className="intrinsics-field">
      <label>
        Intrinsics{" "}
        <textarea
          value={draft}
          placeholder='paste visionforge calibrate output: [{"camera_model":…,"camera_params":[…],"width":…,"height":…}, …]'
          disabled={disabled}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => apply(draft)}
        />
      </label>
      <input type="file" accept="application/json,.json" disabled={disabled} onChange={(e) => void loadFile(e.target.files?.[0] ?? null)} />
      <button type="button" className="small" onClick={() => apply(draft)} disabled={disabled}>
        Apply
      </button>
      {value && (
        <button
          type="button"
          className="small"
          disabled={disabled}
          onClick={() => {
            setDraft("");
            apply("");
          }}
        >
          Clear
        </button>
      )}
      <span className={`intrinsics-summary${value ? " set" : ""}`} title="what the first configure message will carry">
        {describeIntrinsics(value)}
      </span>
      {problem && <span className="error">{problem}</span>}
    </div>
  );
}
