import json
import pytest
from fastapi.testclient import TestClient

from visionforge.api.app import create_app
from visionforge.spatial.scene_graph import build_scene_graph, save_scene_graph


def _plane(id_, ptype, normal, d, centroid, boundary, area, axis_u, axis_v, support=500):
    return {
        "id": id_, "type": ptype,
        "equation": [normal[0], normal[1], normal[2], d],
        "normal": normal, "centroid": centroid, "centroid_room": centroid,
        "support": support, "extent": {"width": 1.0, "height": 1.0}, "area": area,
        "boundary": boundary, "boundary_room": boundary,
        "in_plane_axes": {"axis_u": axis_u, "axis_v": axis_v}, "ply_path": None
    }


@pytest.fixture
def run_dir(tmp_path):
    floor = _plane("floor", "floor", [0, 1, 0], 0.0, [2, 0, 1.5],
                    [[0, 0, 0], [4, 0, 0], [4, 0, 3], [0, 0, 3]], 12.0, [0, 0, -1], [1, 0, 0])
    ceiling = _plane("ceiling", "ceiling", [0, 1, 0], -2.5, [2, 2.5, 1.5],
                      [[0, 2.5, 0], [4, 2.5, 0], [4, 2.5, 3], [0, 2.5, 3]], 12.0, [0, 0, -1], [1, 0, 0])
    wall_west = _plane("wall_west", "wall", [1, 0, 0], 0.0, [0, 1.25, 1.5],
                        [[0, 0, 0], [0, 0, 3], [0, 2.5, 3], [0, 2.5, 0]], 7.5, [0, 0, 1], [0, 1, 0])
    wall_south = _plane("wall_south", "wall", [0, 0, 1], 0.0, [2, 1.25, 0],
                         [[0, 0, 0], [4, 0, 0], [4, 2.5, 0], [0, 2.5, 0]], 10.0, [-1, 0, 0], [0, 1, 0])

    room_model = {
        "coordinate_system": {"up_axis": [0, 1, 0], "horizontal_axes": [[1, 0, 0], [0, 0, 1]], "origin": [0, 0, 0]},
        "scale": {"metric_available": False, "scale_factor": 1.0},
        "room": {
            "length": 4.0, "width": 3.0, "height": 2.5, "floor_area": 12.0,
            "length_method": "floor_extent", "width_method": "floor_extent",
            "height_method": "floor_to_ceiling", "floor_area_method": "floor_extent",
            "bounding_polygon_room": [[0, 0], [4, 0], [4, 3], [0, 3]]
        },
        "planes": [floor, ceiling, wall_west, wall_south],
        "intersections": [
            {"plane_a": "floor", "plane_b": "wall_west", "point": [0, 0, 0], "direction": [0, 0, 1],
             "segment": [[0, 0, 0], [0, 0, 3]], "point_room": [0, 0, 0], "segment_room": [[0, 0, 0], [0, 0, 3]]}
        ]
    }

    cameras = [
        {"id": 1, "name": "frame_000001.jpg", "rotation_quat": [0.0, 0.0, 0.0, 1.0], "translation": [-2.0, -1.25, -1.5],
         "camera_model": "SIMPLE_RADIAL", "camera_params": [900.0, 400.0, 300.0, 0.0]}
    ]

    run = tmp_path / "final_demo"
    (run / "p2" / "planes").mkdir(parents=True)
    (run / "p1" / "reconstruction").mkdir(parents=True)

    with open(run / "p2" / "room_model.json", "w") as f:
        json.dump(room_model, f)
    with open(run / "p1" / "reconstruction" / "cameras.json", "w") as f:
        json.dump(cameras, f)

    sg = build_scene_graph(room_model, cameras=cameras)
    save_scene_graph(sg, run / "scene_graph.json")

    (run / "p1" / "reconstruction" / "sparse_cloud.ply").write_text("ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")
    (run / "p2" / "planes" / "floor.ply").write_text("ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")

    status = {
        "input_type": "synthetic", "video": "data/input/synthetic_box_room.mp4",
        "stages": {"p0_frame_extraction": "success", "p1_reconstruction": "success",
                   "p2_room_geometry": "success", "scene_graph": "success"}
    }
    with open(run / "run_status.json", "w") as f:
        json.dump(status, f)

    return run


@pytest.fixture
def client(tmp_path, run_dir):
    # run_dir lives directly under tmp_path (as "final_demo"), so tmp_path
    # itself is the outputs root for auto-discovery.
    app = create_app(outputs_root=tmp_path)
    return TestClient(app)


def test_list_sessions_auto_discovers_run_dir(client):
    resp = client.get("/sessions")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert "final_demo" in ids


def test_get_session_provenance(client):
    resp = client.get("/sessions/final_demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "final_demo"
    assert data["provenance"]["input_type"] == "synthetic"
    assert data["provenance"]["scale"] == {"metric_available": False, "scale_factor": 1.0}


def test_get_session_not_found(client):
    resp = client.get("/sessions/does-not-exist")
    assert resp.status_code == 404


def test_create_session_registers_explicit_run_dir(tmp_path, run_dir):
    app = create_app(outputs_root=tmp_path / "empty_root")  # nothing auto-discovered here
    client = TestClient(app)

    resp = client.post("/sessions", json={"run_dir": str(run_dir), "id": "my-session"})
    assert resp.status_code == 201
    assert resp.json()["id"] == "my-session"

    resp2 = client.get("/sessions/my-session/room_model")
    assert resp2.status_code == 200
    assert resp2.json()["room"]["length"] == 4.0


def test_create_session_missing_dir_returns_400(tmp_path):
    app = create_app(outputs_root=tmp_path)
    client = TestClient(app)
    resp = client.post("/sessions", json={"run_dir": str(tmp_path / "nope")})
    assert resp.status_code == 400


def test_get_room_model(client):
    resp = client.get("/sessions/final_demo/room_model")
    assert resp.status_code == 200
    assert resp.json()["room"]["height_method"] == "floor_to_ceiling"


def test_get_scene_graph(client):
    resp = client.get("/sessions/final_demo/scene_graph")
    assert resp.status_code == 200
    data = resp.json()
    assert any(n["type"] == "camera" for n in data["nodes"])


def test_get_cameras(client):
    resp = client.get("/sessions/final_demo/cameras")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "frame_000001.jpg"


def test_get_twin(client):
    resp = client.get("/sessions/final_demo/twin")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"provenance", "room_model", "cameras", "scene_graph", "sparse_cloud_path"}
    assert data["sparse_cloud_path"] == "p1/reconstruction/sparse_cloud.ply"


def test_get_measurements(client):
    resp = client.get("/sessions/final_demo/measurements")
    assert resp.status_code == 200
    data = resp.json()
    assert data["height"] == {"value": 2.5, "metric": False, "units": "reconstruction_units", "method": "floor_to_ceiling"}
    assert data["length"]["value"] == 4.0


def test_query_by_method(client):
    resp = client.post("/sessions/final_demo/query", json={"method": "get_room_height"})
    assert resp.status_code == 200
    assert resp.json()["value"] == 2.5


def test_query_by_method_with_params(client):
    resp = client.post("/sessions/final_demo/query", json={
        "method": "get_wall_area", "params": {"wall_id": "wall_west"}
    })
    assert resp.status_code == 200
    assert resp.json()["value"] == 7.5


def test_query_by_question(client):
    resp = client.post("/sessions/final_demo/query", json={"question": "Which wall is largest?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["supported"] is True
    assert data["answer"]["wall_id"] == "wall_south"  # area 10.0 > wall_west's 7.5


def test_query_unsupported_question_not_a_500(client):
    resp = client.post("/sessions/final_demo/query", json={"question": "What color is the floor?"})
    assert resp.status_code == 200
    assert resp.json()["supported"] is False


def test_query_requires_method_or_question(client):
    resp = client.post("/sessions/final_demo/query", json={})
    assert resp.status_code == 400


def test_query_rejects_unknown_method(client):
    # Must not be able to reach an arbitrary attribute via getattr.
    resp = client.post("/sessions/final_demo/query", json={"method": "__class__"})
    assert resp.status_code == 400
    resp2 = client.post("/sessions/final_demo/query", json={"method": "not_a_real_method"})
    assert resp2.status_code == 400


def test_query_invalid_params_returns_400_not_500(client):
    resp = client.post("/sessions/final_demo/query", json={
        "method": "get_wall_area", "params": {"nonexistent_kwarg": "x"}
    })
    assert resp.status_code == 400


def test_get_cloud_serves_file(client, run_dir):
    resp = client.get("/sessions/final_demo/cloud")
    assert resp.status_code == 200
    expected = (run_dir / "p1" / "reconstruction" / "sparse_cloud.ply").read_bytes()
    assert resp.content == expected


def test_get_plane_ply_serves_file(client, run_dir):
    resp = client.get("/sessions/final_demo/planes/floor")
    assert resp.status_code == 200
    expected = (run_dir / "p2" / "planes" / "floor.ply").read_bytes()
    assert resp.content == expected


def test_get_plane_ply_missing_404(client):
    resp = client.get("/sessions/final_demo/planes/does_not_exist")
    assert resp.status_code == 404


def test_get_plane_ply_rejects_path_traversal(client):
    resp = client.get("/sessions/final_demo/planes/..%2F..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)  # never a raw file read outside planes/


def test_cors_allows_default_vite_dev_origin(client):
    resp = client.get("/sessions", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_origins_configurable_via_env_var(tmp_path, run_dir, monkeypatch):
    monkeypatch.setenv("VISIONFORGE_CORS_ORIGINS", "http://example.com:1234")
    app = create_app(outputs_root=tmp_path)
    client = TestClient(app)

    resp = client.get("/sessions", headers={"Origin": "http://example.com:1234"})
    assert resp.headers.get("access-control-allow-origin") == "http://example.com:1234"

    # The default Vite origin is no longer allowed once the env var overrides it.
    resp2 = client.get("/sessions", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in resp2.headers
