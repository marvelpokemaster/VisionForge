import json
import os
from pathlib import Path
from typing import Any, Dict

from visionforge.persistence.backend import PersistenceBackend
from visionforge.persistence.local_backend import LocalJsonBackend


def get_backend(outputs_root: "Path | None" = None) -> PersistenceBackend:
    """Selects the persistence backend from SUPABASE_URL / SUPABASE_KEY.
    supabase-py is only imported when both env vars are present -- the
    offline pipeline and LocalJsonBackend-only tests never trigger it.
    `outputs_root` lets callers (the API, tests) point LocalJsonBackend at a
    specific directory instead of the "outputs/" default."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        from visionforge.persistence.supabase_backend import SupabaseBackend
        print("Persistence: SUPABASE_URL/SUPABASE_KEY set, using SupabaseBackend.")
        return SupabaseBackend(url, key)

    print("Persistence: SUPABASE_URL/SUPABASE_KEY not set, using LocalJsonBackend (outputs/).")
    return LocalJsonBackend(outputs_root=outputs_root or Path("outputs"))


def persist_run(backend: PersistenceBackend, session_id: str, run_dir: Path) -> Dict[str, Any]:
    """Saves a run directory's room model, scene graph, twin, measurements,
    and processing status through `backend`. Shared by the API's
    POST /sessions/{id}/persist and the `visionforge persist` CLI command,
    so the two never drift."""
    from visionforge.twin.digital_twin import DigitalTwin
    from visionforge.spatial.queries import SpatialQueryEngine

    run_dir = Path(run_dir)
    twin = DigitalTwin.build_from_run_dir(run_dir)

    video_name = None
    status_path = run_dir / "run_status.json"
    if status_path.exists():
        with open(status_path, "r") as f:
            run_status = json.load(f)
        video_name = run_status.get("video")

    stage_status = twin.provenance.get("stage_status", {})
    input_type = twin.provenance.get("input_type", "unknown")
    overall_status = "success" if stage_status and all(v == "success" for v in stage_status.values()) else "partial"

    saved = []

    backend.save_session(session_id, input_type=input_type, video_name=video_name, status=overall_status)
    saved.append("session")

    if twin.room_model is not None:
        backend.save_room_model(session_id, twin.room_model)
        saved.append("room_model")

    if twin.scene_graph is not None:
        backend.save_scene_graph(session_id, twin.scene_graph)
        saved.append("scene_graph")

        sqe = SpatialQueryEngine(twin.scene_graph)
        dims = sqe.get_room_dimensions()
        records = [
            {"name": name, "value": m["value"], "units": m["units"], "metric": m["metric"], "method": m.get("method")}
            for name, m in dims.items()
            if m is not None
        ]
        backend.save_measurements(session_id, records)
        saved.append("measurements")

    backend.save_twin(session_id, twin.to_dict())
    saved.append("twin")

    if stage_status:
        backend.save_processing_status(session_id, stage_status)
        saved.append("processing_status")

    return {"session_id": session_id, "saved": saved}
