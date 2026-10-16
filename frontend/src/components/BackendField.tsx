import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  DEFAULT_API_BASE,
  apiBase,
  probeBackend,
  readApiBaseOverride,
  setApiBaseOverride,
  subscribeApiBase,
  validateApiBase,
  type ProbeResult
} from "../lib/backend";

/** The backend base URL in effect; re-renders when the override changes. */
export function useApiBase(): string {
  return useSyncExternalStore(subscribeApiBase, apiBase, apiBase);
}

interface Props {
  /** While a live session runs the socket is already bound: no edits. */
  disabled?: boolean;
}

/** "Backend" field: the runtime override of VITE_API_BASE_URL (persisted in
 * localStorage) + the effective URL + a GET /sessions probe, so a phone user
 * sees at once whether the PC is reachable. */
export default function BackendField({ disabled = false }: Props) {
  const effective = useApiBase();
  const [draft, setDraft] = useState<string>(() => readApiBaseOverride() ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const [probe, setProbe] = useState<ProbeResult | "checking" | null>(null);
  const [probeSeq, setProbeSeq] = useState(0);

  // probe on mount, whenever the effective base changes, and on Retry
  useEffect(() => {
    let cancelled = false;
    setProbe("checking");
    void probeBackend(effective).then((r) => {
      if (!cancelled) setProbe(r);
    });
    return () => {
      cancelled = true;
    };
  }, [effective, probeSeq]);

  const apply = useCallback(() => {
    const err = validateApiBase(draft);
    setProblem(err);
    if (err) return;
    const now = setApiBaseOverride(draft);
    setDraft(readApiBaseOverride() ?? "");
    if (now === effective) setProbeSeq((n) => n + 1); // same URL: still re-check
  }, [draft, effective]);

  const reset = useCallback(() => {
    setProblem(null);
    setApiBaseOverride(null);
    setDraft("");
  }, []);

  const overridden = readApiBaseOverride() !== null;

  return (
    <div className="backend-field">
      <label>
        Backend{" "}
        <input
          value={draft}
          placeholder={DEFAULT_API_BASE}
          disabled={disabled}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          inputMode="url"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={apply}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply();
          }}
        />
      </label>
      <button type="button" className="small" onClick={apply} disabled={disabled}>
        Apply
      </button>
      {overridden && (
        <button type="button" className="small" onClick={reset} disabled={disabled} title={`back to ${DEFAULT_API_BASE}`}>
          Reset
        </button>
      )}
      <span className="backend-effective" title="the URL every request and the live socket use right now">
        using {effective}
        {!overridden && <small> (build default)</small>}
      </span>
      <span className={`backend-probe backend-probe-${probe === null || probe === "checking" ? "checking" : probe.ok ? "ok" : "failed"}`}>
        connection:{" "}
        {probe === null || probe === "checking"
          ? "checking…"
          : probe.ok
            ? `ok (${probe.sessions} sessions, ${probe.ms} ms)`
            : `failed: ${probe.error}`}
      </span>
      <button type="button" className="small" onClick={() => setProbeSeq((n) => n + 1)} disabled={probe === "checking"}>
        Retry
      </button>
      {problem && <span className="error">{problem}</span>}
    </div>
  );
}
