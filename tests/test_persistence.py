import json
import sys
import pytest

from visionforge.persistence import get_backend, persist_run
from visionforge.persistence.local_backend import LocalJsonBackend
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph


# ---------------------------------------------------------------------------
# LocalJsonBackend: full coverage
# ---------------------------------------------------------------------------

@pytest.fixture
def local_backend(tmp_path):
    return LocalJsonBackend(outputs_root=tmp_path)


def test_local_save_and_list_session(local_backend):
    local_backend.save_session("sess-1", input_type="synthetic", video_name="room.mp4", status="success")

    sessions = local_backend.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"
    assert sessions[0]["input_type"] == "synthetic"
    assert sessions[0]["video_name"] == "room.mp4"
    assert sessions[0]["status"] == "success"
    assert "created_at" in sessions[0]


def test_local_save_session_preserves_created_at_on_update(local_backend):
    local_backend.save_session("sess-1", input_type="synthetic", video_name=None, status="partial")
    first = local_backend.list_sessions()[0]

    local_backend.save_session("sess-1", input_type="synthetic", video_name=None, status="success")
    second = local_backend.list_sessions()[0]

    assert second["created_at"] == first["created_at"]
    assert second["status"] == "success"


def test_local_room_model_versioning(local_backend):
    v1 = local_backend.save_room_model("sess-1", {"room": {"length": 4.0}})
    v2 = local_backend.save_room_model("sess-1", {"room": {"length": 4.5}})

    assert v1 == 1
    assert v2 == 2

    path_v2 = local_backend._session_dir("sess-1") / "room_models" / "v2.json"
    assert path_v2.exists()
    with open(path_v2) as f:
        record = json.load(f)
    assert record["version"] == 2
    assert record["payload"]["room"]["length"] == 4.5


def test_local_scene_graph_versioning(local_backend):
    v1 = local_backend.save_scene_graph("sess-1", {"nodes": [], "edges": []})
    assert v1 == 1
    v2 = local_backend.save_scene_graph("sess-1", {"nodes": [1], "edges": []})
    assert v2 == 2


def test_local_twin_versioning_and_get_twin(local_backend):
    assert local_backend.get_twin("sess-1") is None  # nothing saved yet

    local_backend.save_twin("sess-1", {"provenance": {"input_type": "synthetic"}, "room_model": None})
    local_backend.save_twin("sess-1", {"provenance": {"input_type": "synthetic"}, "room_model": {"x": 1}})

    latest = local_backend.get_twin("sess-1")
    assert latest["room_model"] == {"x": 1}


def test_local_save_measurements(local_backend):
    measurements = [
        {"name": "length", "value": 4.0, "units": "m", "metric": True, "method": "floor_extent"},
        {"name": "height", "value": None, "units": None, "metric": True, "method": None}
    ]
    local_backend.save_measurements("sess-1", measurements)

    path = local_backend._session_dir("sess-1") / "measurements.json"
    with open(path) as f:
        record = json.load(f)
    assert record["measurements"] == measurements


def test_local_save_experiment_result(local_backend):
    local_backend.save_experiment_result("sess-1", "trial-a", {"score": 0.9})

    path = local_backend._session_dir("sess-1") / "experiment_results" / "trial-a.json"
    with open(path) as f:
        record = json.load(f)
    assert record["key"] == "trial-a"
    assert record["json"] == {"score": 0.9}


def test_local_save_processing_status(local_backend):
    local_backend.save_processing_status("sess-1", {"p0_frame_extraction": "success", "p1_reconstruction": "running"})

    path = local_backend._session_dir("sess-1") / "processing_status.json"
    with open(path) as f:
        record = json.load(f)
    assert record["stages"]["p1_reconstruction"] == "running"


def test_local_list_sessions_empty_when_nothing_persisted(tmp_path):
    backend = LocalJsonBackend(outputs_root=tmp_path)
    assert backend.list_sessions() == []


def test_local_list_sessions_ignores_run_dirs_without_persistence(tmp_path):
    (tmp_path / "some_run" / "p2").mkdir(parents=True)
    backend = LocalJsonBackend(outputs_root=tmp_path)
    assert backend.list_sessions() == []


# ---------------------------------------------------------------------------
# SupabaseBackend, tested against a fake postgrest-like client -- no network.
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []
        self._order = None
        self._limit = None
        self._mode = None
        self._payload = None
        self._on_conflict = None

    def select(self, cols="*"):
        self._mode = "select"
        return self

    def insert(self, data):
        self._mode = "insert"
        self._payload = data if isinstance(data, list) else [data]
        return self

    def upsert(self, data, on_conflict=None):
        self._mode = "upsert"
        self._payload = data
        self._on_conflict = on_conflict or "id"
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._mode == "insert":
            inserted = []
            for row in self._payload:
                record = dict(row)
                record.setdefault("id", len(self._rows) + 1)
                self._rows.append(record)
                inserted.append(record)
            return _FakeResult(inserted)

        if self._mode == "upsert":
            key = self._on_conflict
            existing = next((r for r in self._rows if r.get(key) == self._payload.get(key)), None)
            if existing:
                existing.update(self._payload)
                return _FakeResult([existing])
            record = dict(self._payload)
            self._rows.append(record)
            return _FakeResult([record])

        # select
        results = list(self._rows)
        for col, val in self._filters:
            results = [r for r in results if r.get(col) == val]
        if self._order:
            col, desc = self._order
            results = sorted(results, key=lambda r: r.get(col), reverse=desc)
        if self._limit is not None:
            results = results[: self._limit]
        return _FakeResult(results)


class FakeSupabaseClient:
    """Minimal in-memory stand-in for supabase-py's Client, supporting only
    the chain patterns SupabaseBackend actually uses. No network I/O."""

    def __init__(self):
        self.tables = {}

    def table(self, name):
        self.tables.setdefault(name, [])
        return _FakeQuery(self.tables[name])


@pytest.fixture
def fake_client():
    return FakeSupabaseClient()


@pytest.fixture
def supabase_backend(fake_client):
    from visionforge.persistence.supabase_backend import SupabaseBackend
    return SupabaseBackend(url="https://example.supabase.co", key="fake-key", client=fake_client)


def test_supabase_save_session_upserts(supabase_backend, fake_client):
    supabase_backend.save_session("sess-1", input_type="synthetic", video_name="room.mp4", status="success")
    supabase_backend.save_session("sess-1", input_type="synthetic", video_name="room.mp4", status="partial")

    rows = fake_client.tables["sessions"]
    assert len(rows) == 1  # upsert, not a second insert
    assert rows[0]["status"] == "partial"


def test_supabase_room_model_versioning(supabase_backend, fake_client):
    v1 = supabase_backend.save_room_model("sess-1", {"room": {"length": 4.0}})
    v2 = supabase_backend.save_room_model("sess-1", {"room": {"length": 4.5}})

    assert v1 == 1
    assert v2 == 2
    assert len(fake_client.tables["room_models"]) == 2


def test_supabase_versioning_is_scoped_per_session(supabase_backend, fake_client):
    supabase_backend.save_room_model("sess-1", {"a": 1})
    v1_other = supabase_backend.save_room_model("sess-2", {"a": 2})
    assert v1_other == 1  # independent version sequence per session


def test_supabase_scene_graph_and_twin_versioning(supabase_backend):
    assert supabase_backend.save_scene_graph("sess-1", {"nodes": [], "edges": []}) == 1
    assert supabase_backend.save_scene_graph("sess-1", {"nodes": [1], "edges": []}) == 2
    assert supabase_backend.save_twin("sess-1", {"room_model": None}) == 1


def test_supabase_get_twin_returns_latest_payload(supabase_backend):
    assert supabase_backend.get_twin("sess-1") is None

    supabase_backend.save_twin("sess-1", {"room_model": {"v": 1}})
    supabase_backend.save_twin("sess-1", {"room_model": {"v": 2}})

    assert supabase_backend.get_twin("sess-1")["room_model"] == {"v": 2}


def test_supabase_save_measurements_bulk_inserts(supabase_backend, fake_client):
    measurements = [
        {"name": "length", "value": 4.0, "units": "m", "metric": True, "method": "floor_extent"},
        {"name": "height", "value": 2.5, "units": "m", "metric": True, "method": "floor_to_ceiling"}
    ]
    supabase_backend.save_measurements("sess-1", measurements)

    rows = fake_client.tables["measurements"]
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"length", "height"}


def test_supabase_save_measurements_noop_on_empty_list(supabase_backend, fake_client):
    supabase_backend.save_measurements("sess-1", [])
    assert fake_client.tables.get("measurements", []) == []


def test_supabase_save_experiment_result(supabase_backend, fake_client):
    supabase_backend.save_experiment_result("sess-1", "trial-a", {"score": 0.9})
    rows = fake_client.tables["experiment_results"]
    assert rows[0]["key"] == "trial-a"
    assert rows[0]["json"] == {"score": 0.9}


def test_supabase_save_processing_status_bulk_inserts(supabase_backend, fake_client):
    supabase_backend.save_processing_status("sess-1", {"p0_frame_extraction": "success", "p1_reconstruction": "running"})
    rows = fake_client.tables["processing_status"]
    assert len(rows) == 2
    assert {r["stage"]: r["status"] for r in rows} == {"p0_frame_extraction": "success", "p1_reconstruction": "running"}


def test_supabase_list_sessions(supabase_backend, fake_client):
    supabase_backend.save_session("sess-1", input_type="synthetic", video_name=None, status="success")
    supabase_backend.save_session("sess-2", input_type="real", video_name=None, status="partial")

    sessions = supabase_backend.list_sessions()
    assert {s["id"] for s in sessions} == {"sess-1", "sess-2"}


# ---------------------------------------------------------------------------
# get_backend(): selection logic and the "never import supabase-py unless
# selected" guarantee.
# ---------------------------------------------------------------------------

def test_get_backend_defaults_to_local_without_env_vars(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    backend = get_backend()
    assert isinstance(backend, LocalJsonBackend)


def test_get_backend_does_not_import_supabase_module_without_env_vars(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    sys.modules.pop("visionforge.persistence.supabase_backend", None)

    get_backend()

    assert "visionforge.persistence.supabase_backend" not in sys.modules


def test_get_backend_selects_supabase_when_env_vars_set(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    # Avoid any real network call inside create_client.
    monkeypatch.setattr(
        "visionforge.persistence.supabase_backend.create_client",
        lambda url, key: FakeSupabaseClient()
    )

    backend = get_backend()

    from visionforge.persistence.supabase_backend import SupabaseBackend
    assert isinstance(backend, SupabaseBackend)


def test_get_backend_missing_one_env_var_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert isinstance(get_backend(), LocalJsonBackend)


# ---------------------------------------------------------------------------
# persist_run(): shared logic used by both the API and the CLI.
# ---------------------------------------------------------------------------

def _plane(id_, ptype, normal, d, centroid, boundary, area=1.0):
    return {
        "id": id_, "type": ptype,
        "equation": [normal[0], normal[1], normal[2], d],
        "normal": normal, "centroid": centroid, "centroid_room": centroid,
        "support": 500, "extent": {"width": 1.0, "height": 1.0}, "area": area,
        "boundary": boundary, "boundary_room": boundary,
        "in_plane_axes": {"axis_u": [0, 0, 1], "axis_v": [0, 1, 0]}, "ply_path": None
    }


@pytest.fixture
def run_dir(tmp_path):
    floor = _plane("floor", "floor", [0, 1, 0], 0.0, [2, 0, 1.5],
                    [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]], area=12.0)
    room_model = {
        "coordinate_system": {"up_axis": [0, 1, 0], "horizontal_axes": [[1, 0, 0], [0, 0, 1]], "origin": [0, 0, 0]},
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": 4.0, "width": 3.0, "height": 0.0, "floor_area": 12.0,
            "length_method": "floor_extent", "width_method": "floor_extent",
            "height_method": None, "floor_area_method": "floor_extent",
            "bounding_polygon_room": [[0, 0], [4, 0], [4, 3], [0, 3]]
        },
        "planes": [floor],
        "intersections": []
    }

    run = tmp_path / "final_demo"
    (run / "p2").mkdir(parents=True)
    (run / "p1" / "reconstruction").mkdir(parents=True)

    with open(run / "p2" / "room_model.json", "w") as f:
        json.dump(room_model, f)
    with open(run / "p1" / "reconstruction" / "cameras.json", "w") as f:
        json.dump([], f)

    sg = build_scene_graph(room_model, cameras=None)
    save_scene_graph(sg, run / "scene_graph.json")

    (run / "p1" / "reconstruction" / "sparse_cloud.ply").write_text("ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")

    status = {
        "input_type": "synthetic", "video": "data/input/synthetic_box_room.mp4",
        "stages": {"p0_frame_extraction": "success", "p1_reconstruction": "success",
                   "p2_room_geometry": "success", "scene_graph": "success", "twin": "success"}
    }
    with open(run / "run_status.json", "w") as f:
        json.dump(status, f)

    return run


def test_persist_run_saves_everything_through_local_backend(run_dir, tmp_path):
    backend = LocalJsonBackend(outputs_root=tmp_path / "persisted")

    summary = persist_run(backend, "final_demo", run_dir)

    assert summary["session_id"] == "final_demo"
    assert set(summary["saved"]) == {"session", "room_model", "scene_graph", "measurements", "twin", "processing_status"}

    sessions = backend.list_sessions()
    assert sessions[0]["input_type"] == "synthetic"
    assert sessions[0]["video_name"] == "data/input/synthetic_box_room.mp4"
    assert sessions[0]["status"] == "success"

    twin_payload = backend.get_twin("final_demo")
    assert twin_payload["room_model"]["room"]["length"] == 4.0

    measurements_path = backend._session_dir("final_demo") / "measurements.json"
    with open(measurements_path) as f:
        record = json.load(f)
    names = {m["name"] for m in record["measurements"]}
    # height_method is None (no ceiling/walls) -> height must be excluded, never a fabricated 0.
    assert "height" not in names
    assert {"length", "width", "floor_area"} <= names


def test_persist_run_through_fake_supabase_backend(run_dir):
    from visionforge.persistence.supabase_backend import SupabaseBackend
    fake_client = FakeSupabaseClient()
    backend = SupabaseBackend(url="https://example.supabase.co", key="fake-key", client=fake_client)

    summary = persist_run(backend, "final_demo", run_dir)

    assert "room_model" in summary["saved"]
    assert len(fake_client.tables["sessions"]) == 1
    assert len(fake_client.tables["room_models"]) == 1
    assert len(fake_client.tables["scene_graphs"]) == 1
    assert len(fake_client.tables["twins"]) == 1
    assert len(fake_client.tables["measurements"]) >= 1
    assert len(fake_client.tables["processing_status"]) == 5
