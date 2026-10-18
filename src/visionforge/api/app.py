import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from visionforge.twin.digital_twin import DigitalTwin
from visionforge.spatial.queries import SpatialQueryEngine
from visionforge.spatial.clearance import FURNITURE_CATALOG, FloorClearanceEngine, PlacementItem
from visionforge.spatial.calibration import apply_scale_to_session
from visionforge.api.store import SessionStore
from visionforge.api.live import install_live_routes
from visionforge.persistence import get_backend, persist_run, persist_artifacts

# Vite's default dev server origin. Override with a comma-separated list via
# VISIONFORGE_CORS_ORIGINS for a different frontend dev port/host.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,https://localhost,http://localhost,capacitor://localhost,https://visionforge-spatial.web.app,https://visionforge-spatial.firebaseapp.com"

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


class ValidatePlacementRequest(BaseModel):
    furniture_id: str
    center_x: float
    center_z: float
    angle_deg: float = 0.0
    placed_items: Optional[List[PlacementItem]] = None
    custom_length: Optional[float] = None
    custom_width: Optional[float] = None


class AutoPackRequest(BaseModel):
    furniture_id: str
    spacing: float = 0.3
    max_items: int = 50
    custom_length: Optional[float] = None
    custom_width: Optional[float] = None


class CalibrateScaleRequest(BaseModel):
    reference_type: str
    known_distance_meters: float
    pt_a: Optional[List[float]] = None
    pt_b: Optional[List[float]] = None


class SaveFurnitureLayoutRequest(BaseModel):
    placed_items: List[Dict[str, Any]]
    pack_spacing: Optional[float] = 0.3


def _extract_user_id(request: Request, backend: Any) -> Optional[str]:
    """Derives user ownership server-side from verified auth tokens.
    Never trusts client-supplied user ID query params or bodies.
    In production and for FirebaseBackend, strictly enforces verified tokens and never falls back."""
    auth_header = request.headers.get("Authorization")
    require_auth = os.environ.get("VISIONFORGE_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
    is_prod = (
        os.environ.get("VISIONFORGE_ENV", "").lower() == "production"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
    )

    if not auth_header:
        if require_auth or is_prod:
            raise HTTPException(status_code=401, detail="Authentication required")
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Expected 'Bearer <token>'")
    token = parts[1]

    # If connected to FirebaseBackend, strictly verify Firebase ID token
    if backend.__class__.__name__ == "FirebaseBackend":
        try:
            from firebase_admin import auth as fb_auth
            decoded = fb_auth.verify_id_token(token)
            return decoded.get("uid")
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Firebase authentication failed: {e}")

    # If connected to real SupabaseBackend with a client, verify token
    client = getattr(backend, "client", None)
    if client is not None and hasattr(client, "auth") and hasattr(client.auth, "get_user"):
        try:
            user_resp = client.auth.get_user(token)
            if user_resp and hasattr(user_resp, "user") and user_resp.user:
                return str(user_resp.user.id)
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Authentication failed: {e}")

    # In production, reject tokens that cannot be verified by a real cloud backend
    if is_prod:
        raise HTTPException(status_code=401, detail="Authentication token could not be verified by production backend")

    # Local development / unit tests with LocalJsonBackend:
    try:
        import base64
        parts_jwt = token.split(".")
        if len(parts_jwt) != 3:
            raise ValueError("Invalid JWT format")
        payload_b64 = parts_jwt[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        sub = claims.get("sub")
        if not sub and require_auth:
            raise HTTPException(status_code=401, detail="Invalid token claims: sub missing")
        return sub
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token format")


ValidatePlacementRequest.model_rebuild()
AutoPackRequest.model_rebuild()
CalibrateScaleRequest.model_rebuild()
SaveFurnitureLayoutRequest.model_rebuild()



def _validate_id_component(value: str, what: str) -> None:
    """Path parameters that get joined onto a filesystem path must not be
    able to escape the session's own run directory."""
    if not value or "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {what}")


def create_app(outputs_root: Optional[Path] = None, backend: Optional[Any] = None) -> FastAPI:
    root = Path(outputs_root) if outputs_root is not None else Path(os.environ.get("VISIONFORGE_OUTPUTS_ROOT", "outputs"))
    store = SessionStore(root)
    if backend is None:
        backend = get_backend(outputs_root=root)

    app = FastAPI(title="VisionForge API", description="Read-only digital twin API, backed by outputs/<run>/ (see Task G for Supabase persistence).")
    app.state.store = store
    app.state.backend = backend
    install_live_routes(app)  # WS /live/{id}, GET /live, DELETE /live/{id}

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

    def _enforce_session_ownership(session_id: str, request: Request) -> Optional[str]:
        user_id = _extract_user_id(request, backend)
        owner_id = backend.get_session_owner(session_id)
        if owner_id is not None:
            if user_id is None or user_id != owner_id:
                raise HTTPException(status_code=403, detail="Forbidden: You do not own this session")
        elif os.environ.get("VISIONFORGE_REQUIRE_AUTH", "").lower() in ("1", "true", "yes"):
            if user_id is None:
                raise HTTPException(status_code=401, detail="Authentication required")
        return user_id

    @app.get("/health")
    def health_check():
        active_live = len(getattr(app.state, "live_sessions", {}))
        return {
            "status": "ok",
            "version": "1.0.0",
            "backend": backend.__class__.__name__,
            "active_live_sessions": active_live,
        }

    @app.get("/sessions")
    def list_sessions(request: Request):
        user_id = _extract_user_id(request, backend)
        merged = {}
        for sid, run_dir in store.list_sessions().items():
            owner = backend.get_session_owner(sid)
            if owner is not None and owner != user_id:
                continue
            merged[sid] = _session_summary(sid, run_dir)
        # When the backend is Supabase/Firebase, this also surfaces sessions with no
        # local run directory at all -- for LocalJsonBackend it's typically
        # a subset of what's already discovered above, deduplicated by id.
        for record in backend.list_sessions(user_id=user_id):
            sid = record["id"]
            if sid not in merged:
                merged[sid] = _persisted_only_summary(record)
        return list(merged.values())

    @app.post("/sessions", status_code=201)
    def create_session(req: CreateSessionRequest, request: Request):
        _extract_user_id(request, backend)
        try:
            sid = store.register(Path(req.run_dir), req.id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _session_summary(sid, store.get(sid))

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        return _session_summary(session_id, run_dir)

    @app.get("/sessions/{session_id}/room_model")
    def get_room_model(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "p2" / "room_model.json", "room_model.json")

    @app.get("/sessions/{session_id}/scene_graph")
    def get_scene_graph(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "scene_graph.json", "scene_graph.json")

    @app.get("/sessions/{session_id}/cameras")
    def get_cameras(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        return _json_or_404(run_dir / "p1" / "reconstruction" / "cameras.json", "cameras.json")

    @app.get("/sessions/{session_id}/twin")
    def get_twin(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = store.get(session_id)
        if run_dir is not None and run_dir.exists():
            return DigitalTwin.build_from_run_dir(run_dir).to_dict()
        persisted = backend.get_twin(session_id)
        if persisted is not None:
            return persisted
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found (no run directory, nothing persisted)")

    @app.post("/sessions/{session_id}/persist")
    def persist_session(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        user_id = _extract_user_id(request, backend)
        result = persist_run(backend, session_id, run_dir, user_id=user_id)
        try:
            persisted_arts = persist_artifacts(backend, session_id, run_dir, user_id=user_id)
            if persisted_arts:
                result["saved"].extend([f"artifact_{a}" for a in persisted_arts if f"artifact_{a}" not in result["saved"]])
        except Exception:
            pass
        return result

    @app.get("/sessions/{session_id}/measurements")
    def get_measurements(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        sqe = _query_engine_for(session_id)
        return sqe.get_room_dimensions()

    @app.post("/sessions/{session_id}/query")
    def run_query(session_id: str, req: QueryRequest, request: Request):
        _enforce_session_ownership(session_id, request)
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
    def get_cloud(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = store.get(session_id)
        if run_dir is not None:
            ply_path = run_dir / "p1" / "reconstruction" / "sparse_cloud.ply"
            if ply_path.exists():
                return FileResponse(str(ply_path), media_type="application/octet-stream", filename="sparse_cloud.ply")
        # Fall back to durable persistence artifact
        cloud_bytes = backend.get_artifact(session_id, "sparse_cloud")
        if cloud_bytes is not None:
            return Response(content=cloud_bytes, media_type="application/octet-stream",
                            headers={"Content-Disposition": 'inline; filename="sparse_cloud.ply"'})
        raise HTTPException(status_code=404, detail="sparse_cloud.ply not available for this session")

    @app.get("/sessions/{session_id}/planes/{plane_id}")
    def get_plane_ply(session_id: str, plane_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        _validate_id_component(plane_id, "plane id")
        run_dir = store.get(session_id)
        if run_dir is not None:
            ply_path = run_dir / "p2" / "planes" / f"{plane_id}.ply"
            if ply_path.exists():
                return FileResponse(str(ply_path), media_type="application/octet-stream", filename=f"{plane_id}.ply")
        # Fall back to durable persistence artifact
        plane_bytes = backend.get_artifact(session_id, f"plane_{plane_id}")
        if plane_bytes is not None:
            return Response(content=plane_bytes, media_type="application/octet-stream",
                            headers={"Content-Disposition": f'inline; filename="{plane_id}.ply"'})
        raise HTTPException(status_code=404, detail=f"Plane PLY '{plane_id}' not available for this session")

    @app.post("/sessions/{session_id}/furniture/layout")
    def save_furniture_layout(session_id: str, req: SaveFurnitureLayoutRequest, request: Request):
        _enforce_session_ownership(session_id, request)
        user_id = _extract_user_id(request, backend)
        backend.save_furniture_layout(session_id, req.model_dump(), user_id=user_id)
        run_dir = store.get(session_id)
        if run_dir is not None and run_dir.exists():
            (run_dir / "furniture_layout.json").write_text(json.dumps(req.model_dump(), indent=2))
        return {"status": "saved", "session_id": session_id}

    @app.get("/sessions/{session_id}/furniture/layout")
    def get_furniture_layout(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        layout = backend.get_furniture_layout(session_id)
        if layout is not None:
            return layout
        run_dir = store.get(session_id)
        if run_dir is not None and run_dir.exists():
            for p in [run_dir / "furniture_layout.json", run_dir / "persistence" / "furniture_layout.json"]:
                if p.exists():
                    try:
                        return json.loads(p.read_text())
                    except Exception:
                        pass
        return {"placed_items": [], "pack_spacing": 0.3}

    # ------------------------------------------------------------------
    # Furniture & Metric Scale Endpoints (Phase 4)
    # ------------------------------------------------------------------

    @app.get("/furniture/catalog")
    def get_furniture_catalog():
        return FURNITURE_CATALOG

    @app.get("/sessions/{session_id}/furniture/catalog")
    def get_session_furniture_catalog(session_id: str, request: Request):
        _enforce_session_ownership(session_id, request)
        return FURNITURE_CATALOG

    @app.post("/sessions/{session_id}/furniture/validate")
    def validate_furniture_placement(session_id: str, req: ValidatePlacementRequest, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        room_model_path = run_dir / "p2" / "room_model.json"
        if not room_model_path.exists():
            room_model_path = run_dir / "room_model.json"
        room_model = _json_or_404(room_model_path, "room_model.json")
        engine = FloorClearanceEngine(room_model)
        return engine.validate_placement(
            furniture_id=req.furniture_id,
            center_x=req.center_x,
            center_z=req.center_z,
            angle_deg=req.angle_deg,
            placed_items=req.placed_items,
            custom_length=req.custom_length,
            custom_width=req.custom_width,
        )

    @app.post("/sessions/{session_id}/furniture/auto_pack")
    def auto_pack_furniture(session_id: str, req: AutoPackRequest, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        room_model_path = run_dir / "p2" / "room_model.json"
        if not room_model_path.exists():
            room_model_path = run_dir / "room_model.json"
        room_model = _json_or_404(room_model_path, "room_model.json")
        engine = FloorClearanceEngine(room_model)
        return engine.auto_pack(
            furniture_id=req.furniture_id,
            spacing=req.spacing,
            max_items=req.max_items,
            custom_length=req.custom_length,
            custom_width=req.custom_width,
        )

    @app.post("/sessions/{session_id}/scale/calibrate")
    def calibrate_scale(session_id: str, req: CalibrateScaleRequest, request: Request):
        _enforce_session_ownership(session_id, request)
        run_dir = _run_dir_or_404(session_id)
        try:
            scaled_model = apply_scale_to_session(
                session_dir=run_dir,
                reference_type=req.reference_type,
                known_distance_meters=req.known_distance_meters,
                pt_a=req.pt_a,
                pt_b=req.pt_b,
            )
            return {
                "success": True,
                "scale": scaled_model["scale"],
                "room": scaled_model["room"],
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return app


app = create_app()
