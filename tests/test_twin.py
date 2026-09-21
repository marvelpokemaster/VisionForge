import json
import pytest

from visionforge.twin.digital_twin import DigitalTwin


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def full_run_dir(tmp_path):
    room_model = {
        "coordinate_system": {"up_axis": [0, 1, 0], "horizontal_axes": [[1, 0, 0], [0, 0, 1]], "origin": [0, 0, 0]},
        "scale": {"metric_available": True, "scale_factor": 0.5},
        "room": {
            "length": 4.0, "width": 3.0, "height": 2.5, "floor_area": 12.0,
            "length_method": "floor_extent", "width_method": "floor_extent",
            "height_method": "floor_to_ceiling", "floor_area_method": "floor_extent",
            "bounding_polygon_room": [[0, 0], [4, 0], [4, 3], [0, 3]]
        },
        "planes": [],
        "intersections": []
    }
    cameras = [{"id": 1, "name": "frame_000001.jpg", "rotation_quat": [0, 0, 0, 1], "translation": [0, 0, 0],
                "camera_model": "SIMPLE_RADIAL", "camera_params": [900, 400, 300, 0]}]
    scene_graph = {"nodes": [{"id": "room_001", "type": "room", "properties": room_model["room"]}], "edges": []}
    status = {"input_type": "synthetic", "video": "data/input/synthetic_box_room.mp4",
              "stages": {"p0_frame_extraction": "success", "p1_reconstruction": "success",
                         "p2_room_geometry": "success", "scene_graph": "success"}}

    _write_json(tmp_path / "p2" / "room_model.json", room_model)
    _write_json(tmp_path / "p1" / "reconstruction" / "cameras.json", cameras)
    _write_json(tmp_path / "scene_graph.json", scene_graph)
    _write_json(tmp_path / "run_status.json", status)

    ply_path = tmp_path / "p1" / "reconstruction" / "sparse_cloud.ply"
    ply_path.parent.mkdir(parents=True, exist_ok=True)
    ply_path.write_text("ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")

    return tmp_path


def test_build_from_run_dir_loads_all_sources(full_run_dir):
    twin = DigitalTwin.build_from_run_dir(full_run_dir)

    assert twin.room_model["room"]["length"] == 4.0
    assert twin.cameras[0]["name"] == "frame_000001.jpg"
    assert twin.scene_graph["nodes"][0]["id"] == "room_001"
    assert twin.sparse_cloud_path == "p1/reconstruction/sparse_cloud.ply"


def test_provenance_source_files_and_stage_status(full_run_dir):
    twin = DigitalTwin.build_from_run_dir(full_run_dir)
    prov = twin.provenance

    assert prov["source_files"]["room_model"] == "p2/room_model.json"
    assert prov["source_files"]["cameras"] == "p1/reconstruction/cameras.json"
    assert prov["source_files"]["scene_graph"] == "scene_graph.json"
    assert prov["source_files"]["sparse_cloud"] == "p1/reconstruction/sparse_cloud.ply"
    assert prov["stage_status"] == {
        "p0_frame_extraction": "success", "p1_reconstruction": "success",
        "p2_room_geometry": "success", "scene_graph": "success"
    }


def test_provenance_input_type_and_scale(full_run_dir):
    twin = DigitalTwin.build_from_run_dir(full_run_dir)
    prov = twin.provenance

    assert prov["input_type"] == "synthetic"
    assert prov["scale"] == {"metric_available": True, "scale_factor": 0.5}


def test_provenance_measurement_methods(full_run_dir):
    twin = DigitalTwin.build_from_run_dir(full_run_dir)
    assert twin.provenance["measurement_methods"] == {
        "length_method": "floor_extent",
        "width_method": "floor_extent",
        "height_method": "floor_to_ceiling",
        "floor_area_method": "floor_extent",
    }


def test_input_type_defaults_to_unknown_without_run_status(full_run_dir):
    (full_run_dir / "run_status.json").unlink()
    twin = DigitalTwin.build_from_run_dir(full_run_dir)

    assert twin.provenance["input_type"] == "unknown"
    assert twin.provenance["stage_status"] == {}


def test_missing_sources_are_none_not_fabricated(tmp_path):
    # Completely empty run dir -- nothing exists yet.
    twin = DigitalTwin.build_from_run_dir(tmp_path)

    assert twin.room_model is None
    assert twin.cameras is None
    assert twin.scene_graph is None
    assert twin.sparse_cloud_path is None
    assert twin.provenance["source_files"]["room_model"] is None
    assert twin.provenance["input_type"] == "unknown"
    assert twin.provenance["scale"] == {"metric_available": False, "scale_factor": 1.0}


def test_round_trip_build_export_import_equal(full_run_dir, tmp_path):
    twin = DigitalTwin.build_from_run_dir(full_run_dir)

    twin_json_path = tmp_path / "out" / "twin.json"
    twin.save(twin_json_path)
    assert twin_json_path.exists()

    loaded = DigitalTwin.load(twin_json_path)

    assert loaded == twin
    assert loaded.to_dict() == twin.to_dict()
    assert loaded.room_model == twin.room_model
    assert loaded.cameras == twin.cameras
    assert loaded.scene_graph == twin.scene_graph
    assert loaded.sparse_cloud_path == twin.sparse_cloud_path
    assert loaded.provenance == twin.provenance


def test_twin_json_is_single_self_contained_file(full_run_dir, tmp_path):
    """The frontend should be able to load twin.json alone (aside from the
    PLY, which stays a path reference) without touching the other files."""
    twin = DigitalTwin.build_from_run_dir(full_run_dir)
    twin_json_path = tmp_path / "twin.json"
    twin.save(twin_json_path)

    with open(twin_json_path) as f:
        data = json.load(f)

    # room_model / cameras / scene_graph are fully embedded, not just referenced
    assert data["room_model"] is not None
    assert data["cameras"] is not None
    assert data["scene_graph"] is not None
    # the PLY is the one exception: a path, never embedded point data
    assert data["sparse_cloud_path"] == "p1/reconstruction/sparse_cloud.ply"
    assert "points" not in data
