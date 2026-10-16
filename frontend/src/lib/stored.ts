// Per-device conveniences kept in localStorage (the Record-frames checkbox,
// the pasted calibration). Every access is wrapped: storage can be absent
// (node tests), throw (private mode / blocked site data) or be read-only, and
// the UI must work without it.
export const RECORD_KEY = "visionforge.recordFrames";
export const INTRINSICS_KEY = "visionforge.intrinsics";

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function storage(): StorageLike | null {
  try {
    return (globalThis as { localStorage?: StorageLike }).localStorage ?? null;
  } catch {
    return null;
  }
}

export function readStored(key: string): string | null {
  const s = storage();
  if (!s) return null;
  try {
    return s.getItem(key);
  } catch {
    return null;
  }
}

/** Store `value`, or remove the key with null / "". Never throws. */
export function writeStored(key: string, value: string | null): void {
  const s = storage();
  if (!s) return;
  try {
    if (value === null || value === "") s.removeItem(key);
    else s.setItem(key, value);
  } catch {
    // quota / read-only: the in-memory state still applies for this session
  }
}
