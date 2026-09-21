import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from visionforge.twin.digital_twin import DigitalTwin
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.api.store import SessionStore
from visionforge.persistence import get_backend, persist_run

# Vite's default dev server origin. Override with a comma-separated list via
# VISIONFORGE_CORS_ORIGINS for a different frontend dev port/host.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

# Query methods the /query endpoint is allowed to dispatch to -- an explicit
# allowlist, not getattr on an arbitrary string, so a request can never reach
# a private method or an unrelated attribute of SpatialQueryEngine.
ALLOWED_QUERY_METHODS = {
    "get_room_length", "get_room_width", "get_room_height", "get_floor_area",
    "get_room_dimensions", "get_wall_area", "get_largest_wall", "get_smallest_wall",
    "get_parallel_surfaces", "get_adjacent_surfaces", "get_perpendicular_surfaces",
    "distance_between_surfaces", "get_surface_intersection",
    "get_camera_position", "get_camera_trajectory", "get_trajectory_length",
    "distance_from_camera_to_surface", "distance_from_camera_to_all_surfaces",
    "get_nearest_wall_to_camera", "check_rectangular_fit",
}


class CreateSessionRequest(BaseModel):
    run_dir: str
    id: Optional[str] = None


class QueryRequest(BaseModel):
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    question: Optional[str] = None


def _validate_id_component(value: str, what: str) -> None:
    """Path parameters that get joined onto a filesystem path must not be
    able to escape the session's own run directory."""
    if not value or "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {what}")


def create_app(outputs_root: Optional[Path] = None) -> FastAPI:
    root = Path(outputs_root) if outputs_root is not None else Path(os.environ.get("VISIONFORGE_OUTPUTS_ROOT", "outputs"))
    store = SessionStore(root)
    backend = get_backend(outputs_root=root)

    app = FastAPI(title="VisionForge API", description="Read-only digital twin API, backed by outputs/<run>/ (see Task G for Supabase persistence).")
    app.state.store = store
    app.state.backend = backend

    cors_origins = [
        o.strip() for o in os.environ.get("VISIONFORGE_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _run_dir_or_404(session_id: str) -> Path:
        run_dir = store.get(session_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return run_dir

    def _json_or_404(path: Path, what: str) -> Any:
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"{what} not available for this session")
        with open(path, "r") as f:
            return json.load(f)

    def _query_engine_for(session_id: str) -> SpatialQueryEngine:
        run_dir = _run_dir_or_404(session_id)
        scene_graph = _json_or_404(run_dir / "scene_graph.json", "scene_graph.json")
        return SpatialQueryEngine(scene_graph)

    def _session_summary(session_id: str, run_dir: Path) -> Dict[str, Any]:
        twin = DigitalTwin.build_from_run_dir(run_dir)
        return {"id": session_id, "run_dir": str(run_dir), "provenance": twin.provenance}

    def _persisted_only_summary(record: Dict[str, Any]) -> Dict[str, Any]:
        """A session known to the backend (e.g. Supabase) but with no local
        run directory -- a reduced provenance, since there's no room_model/
        scene_graph on disk to derive the rest from."""
        return {
            "id": record["id"],
            "run_dir": None,
            "provenance": {
                "run_dir": None,
                "source_files": {"room_model": None, "cameras": None, "scene_graph": None, "sparse_cloud": None},
                "stage_status": {},
                "input_type": record.get("input_type", "unknown"),
                "scale": {"metric_available": False, "scale_factor": 1.0},
                "measurement_methods": {
                    "length_method": None, "width_method": None, "height_method": None, "floor_area_method": None
                }
            }
        }

    @app.get("/sessions")
    def list_sessions():
        merged = {sid: _session_summary(sid, run_dir) for sid, run_dir in store.list_sessions().items()}
        # When the backend is Supabase, this also surfaces sessions with no
        # local run directory at all -- for LocalJsonBackend it's typically
        # a subset of what's already discovered above, deduplicated by id.
        for record in backend.list_sessions():
            sid = record["id"]
            if sid not in merged:
                merged[sid] = _persisted_only_summary(record)
        return list(merged.values())

    @app.post("/sessions", status_code=201)
    def create_session(req: CreateSessionRequest):
        try:
            sid = store.register(Path(req.run_dir), req.id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _session_summary(sid, store.get(sid))

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        return _session_summary(session_id, run_dir)

    @app.get("/sessions/{session_id}/room_model")
    def get_room_model(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "p2" / "room_model.json", "room_model.json")

    @app.get("/sessions/{session_id}/scene_graph")
    def get_scene_graph(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "scene_graph.json", "scene_graph.json")

    @app.get("/sessions/{session_id}/cameras")
    def get_cameras(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "p1" / "reconstruction" / "cameras.json", "cameras.json")

    @app.get("/sessions/{session_id}/twin")
    def get_twin(session_id: str):
        run_dir = store.get(session_id)
        if run_dir is not None and run_dir.exists():
            return DigitalTwin.build_from_run_dir(run_dir).to_dict()
        persisted = backend.get_twin(session_id)
        if persisted is not None:
            return persisted
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found (no run directory, nothing persisted)")

    @app.post("/sessions/{session_id}/persist")
    def persist_session(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        return persist_run(backend, session_id, run_dir)

    @app.get("/sessions/{session_id}/measurements")
    def get_measurements(session_id: str):
        sqe = _query_engine_for(session_id)
        return sqe.get_room_dimensions()

    @app.post("/sessions/{session_id}/query")
    def run_query(session_id: str, req: QueryRequest):
        sqe = _query_engine_for(session_id)

        if req.question is not None:
            return sqe.answer_question(req.question)

        if req.method is None:
            raise HTTPException(status_code=400, detail="Provide either 'method' or 'question'.")
        if req.method not in ALLOWED_QUERY_METHODS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown query method '{req.method}'. Supported: {sorted(ALLOWED_QUERY_METHODS)}"
            )

        method = getattr(sqe, req.method)
        params = req.params or {}
        try:
            return method(**params)
        except TypeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid params for '{req.method}': {e}")

    @app.get("/sessions/{session_id}/cloud")
    def get_cloud(session_id: str):
        run_dir = _run_dir_or_404(session_id)
        ply_path = run_dir / "p1" / "reconstruction" / "sparse_cloud.ply"
        if not ply_path.exists():
            raise HTTPException(status_code=404, detail="sparse_cloud.ply not available for this session")
        return FileResponse(str(ply_path), media_type="application/octet-stream", filename="sparse_cloud.ply")

    @app.get("/sessions/{session_id}/planes/{plane_id}")
    def get_plane_ply(session_id: str, plane_id: str):
        _validate_id_component(plane_id, "plane id")
        run_dir = _run_dir_or_404(session_id)
        ply_path = run_dir / "p2" / "planes" / f"{plane_id}.ply"
        if not ply_path.exists():
            raise HTTPException(status_code=404, detail=f"Plane PLY '{plane_id}' not available for this session")
        return FileResponse(str(ply_path), media_type="application/octet-stream", filename=f"{plane_id}.ply")

    return app


app = create_app()
