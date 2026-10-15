"""DigitalTwin.from_parts: build_from_run_dir goes through it, and a twin
assembled from the same parts in memory equals the run-dir-built one."""
import json
import shutil
from pathlib import Path

import pytest

from visionforge.spatial.scene_graph import build_scene_graph
from visionforge.twin.digital_twin import DigitalTwin

FIXTURE = Path(__file__).parent / "fixtures" / "p2" / "live_synth_30"
REAL_RUN = Path(__file__).resolve().parents[1] / "outputs" / "live_synth_30"


def make_run_dir(tmp_path: Path) -> Path:
    """A live_synth_30-shaped run dir from the frozen P2 fixture."""
    run = tmp_path / "live_synth_30"
    (run / "p1" / "reconstruction").mkdir(parents=True)
    (run / "p2").mkdir()
    shutil.copy(FIXTURE / "cameras.json", run / "p1" / "reconstruction" / "cameras.json")
    shutil.copy(FIXTURE / "sparse_cloud.ply", run / "p1" / "reconstruction" / "sparse_cloud.ply")
    shutil.copy(FIXTURE / "room_model_reference.json", run / "p2" / "room_model.json")
    room_model = json.loads((FIXTURE / "room_model_reference.json").read_text())
    cameras = json.loads((FIXTURE / "cameras.json").read_text())
    (run / "scene_graph.json").write_text(json.dumps(build_scene_graph(room_model, cameras=cameras)))
    (run / "run_status.json").write_text(json.dumps({"input_type": "synthetic", "mode": "live",
                                                     "stages": {"live_tracking": "success", "p2_room_geometry": "success",
                                                                "scene_graph": "success", "twin": "success"}}))
    return run


def _parts(run_dir: Path):
    room_model = json.loads((run_dir / "p2" / "room_model.json").read_text())
    cameras = json.loads((run_dir / "p1" / "reconstruction" / "cameras.json").read_text())
    scene_graph = json.loads((run_dir / "scene_graph.json").read_text())
    status = json.loads((run_dir / "run_status.json").read_text())
    provenance = {
        "run_dir": str(run_dir.resolve()),
        "source_files": {"room_model": "p2/room_model.json", "cameras": "p1/reconstruction/cameras.json",
                         "scene_graph": "scene_graph.json", "sparse_cloud": "p1/reconstruction/sparse_cloud.ply"},
        "stage_status": status["stages"],
        "input_type": status["input_type"],
    }
    return room_model, cameras, scene_graph, provenance


def _roundtrip(run_dir: Path, tmp_path: Path):
    from_dir = DigitalTwin.build_from_run_dir(run_dir)
    room_model, cameras, scene_graph, provenance = _parts(run_dir)
    from_parts = DigitalTwin.from_parts(room_model, cameras, scene_graph, provenance,
                                        sparse_cloud_path="p1/reconstruction/sparse_cloud.ply")
    assert from_parts == from_dir
    assert from_parts.to_dict() == from_dir.to_dict()
    # scale / measurement methods were derived from the room model, not supplied
    assert from_parts.provenance["measurement_methods"]["height_method"] == room_model["room"]["height_method"]
    assert from_parts.provenance["scale"] == room_model["scale"]
    # and survive a save/load round trip
    p = tmp_path / "twin.json"
    from_parts.save(p)
    assert DigitalTwin.load(p) == from_dir


def test_from_parts_equals_run_dir_twin_on_fixture(tmp_path):
    _roundtrip(make_run_dir(tmp_path), tmp_path)


@pytest.mark.skipif(not (REAL_RUN / "scene_graph.json").exists(), reason="outputs/live_synth_30 not present")
def test_from_parts_equals_run_dir_twin_on_outputs_live_synth_30(tmp_path):
    _roundtrip(REAL_RUN, tmp_path)


def test_from_parts_keeps_supplied_scale_and_methods_and_handles_no_model():
    prov = {"run_dir": None, "stage_status": {"live_tracking": "failed"}, "input_type": "real",
            "scale": {"metric_available": True, "scale_factor": 2.0}}
    twin = DigitalTwin.from_parts(None, None, None, prov)
    assert twin.provenance["scale"] == {"metric_available": True, "scale_factor": 2.0}
    assert twin.provenance["measurement_methods"] == {"length_method": None, "width_method": None,
                                                      "height_method": None, "floor_area_method": None}
    assert twin.room_model is None and twin.to_dict()["sparse_cloud_path"] is None
