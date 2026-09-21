# Supabase persistence

VisionForge's offline pipeline and API work fully without Supabase — the
default `LocalJsonBackend` writes the same project-level data as plain JSON
under `outputs/<session_id>/persistence/`. Supabase is an optional, opt-in
backend for the same data, selected only by environment variables.

## Enabling it

Set both environment variables before running the API or CLI:

```bash
export SUPABASE_URL="https://<project-ref>.supabase.co"
export SUPABASE_KEY="<service-role-or-anon-key>"
```

`src/visionforge/persistence/get_backend()` checks these two variables (and
only these — no other config source, and the values are never hardcoded
anywhere in the repo). If both are set, it returns `SupabaseBackend`; if
either is missing, it returns `LocalJsonBackend` and prints one line saying
so. `supabase-py` is only imported (`from supabase import create_client`,
inside `persistence/supabase_backend.py`) once `SupabaseBackend` is actually
selected — the offline pipeline, `LocalJsonBackend`, and every test that
doesn't explicitly select Supabase never trigger that import.

## Applying the migration

The schema lives in `supabase/migrations/0001_init.sql`. Apply it with the
Supabase CLI against your project:

```bash
supabase link --project-ref <project-ref>
supabase db push
```

(or paste the file's contents into the Supabase SQL editor, if you're not
using the CLI). Re-running it is safe — every statement is
`create table if not exists` / `create index if not exists`.

## What is stored

| Table | Contents |
|---|---|
| `sessions` | `id`, `created_at`, `input_type` (`synthetic`\|`real`\|`unknown`), `video_name`, `status` |
| `room_models` | `session_id`, `version`, `payload` (jsonb — the full `room_model.json`), `created_at` |
| `scene_graphs` | `session_id`, `version`, `payload` (jsonb — the full `scene_graph.json`), `created_at` |
| `twins` | `session_id`, `version`, `payload` (jsonb — the full `twin.json`, sparse cloud referenced by path, never embedded), `created_at` |
| `measurements` | `session_id`, `name`, `value`, `units`, `metric`, `method` — one row per room measurement (length/width/height/floor_area), not a jsonb blob, so individual fields are directly queryable |
| `experiment_results` | `session_id`, `key`, `json` (jsonb) — reserved for future experiment tracking; not yet written by the pipeline or API |
| `processing_status` | `session_id`, `stage`, `status`, `updated_at` — one row per pipeline stage, mirroring `run_status.json`'s `stages` |

`room_models`, `scene_graphs`, and `twins` are **append-only and versioned**:
every persist call inserts a new row with `version = max(existing) + 1`
rather than overwriting, so history is preserved. `get_twin(session_id)`
reads back the highest version.

## What is never stored

- Video frames (`p0/frames/*.jpg`)
- The sparse point cloud's actual point data (`sparse_cloud.ply`) — only its
  **path** is stored, inside the `twins.payload.sparse_cloud_path` field
- Per-plane point cloud data (`p2/planes/*.ply`)
- Per-frame camera poses as a separate persisted artifact — camera poses
  live inside the `scene_graphs`/`twins` JSON payloads (as part of the scene
  graph's camera nodes and `cameras.json`'s contents), not as their own
  high-frequency table; there is no frame-by-frame Android tracking
  round-trip through this schema (see `PROJECT_STATE.md` §11)

This matches the project's existing Supabase boundary: persist project state
and JSON artefacts, never raw frames or high-frequency per-frame data.

## Using it

- **API**: `POST /sessions/{id}/persist` saves the room model, scene graph,
  twin, measurements, and processing status for a session that has a local
  run directory, through whichever backend is configured.
  `GET /sessions` also lists Supabase-known sessions that have no local run
  directory (a reduced record — no `room_model`/`scene_graph`, since those
  only exist as `payload` history in the DB, not surfaced through this
  endpoint). `GET /sessions/{id}/twin` falls back to the persisted copy if
  the local run directory is gone.
- **CLI**: `visionforge persist --run-dir <dir> [--session-id <id>]` persists
  an existing run directory standalone. `visionforge reconstruct --persist
  ...` persists automatically as the pipeline's last step (after building
  `twin.json`).

## Testing

`tests/test_persistence.py` covers `LocalJsonBackend` fully (every method,
versioning, `list_sessions`, fallback behavior) and `SupabaseBackend` against
an in-memory fake Postgrest-style client (`FakeSupabaseClient`) — no network
access happens in the test suite. `get_backend()`'s selection logic and the
"supabase-py is never imported unless selected" guarantee are tested
directly (asserting `visionforge.persistence.supabase_backend` is absent
from `sys.modules` after a `get_backend()` call with no env vars set).

No Supabase MCP was configured in the environment this was built in, so no
real database round-trip was performed against an actual Supabase project —
see `PROJECT_STATE.md` §25 for what that means for verification status.
