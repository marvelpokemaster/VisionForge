import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Filenames a run directory produced by `visionforge reconstruct` is expected
# to contain. Paths inside the saved twin are always relative to run_dir, so
# a twin.json is portable across machines/checkouts as long as the run
# directory travels with it.
ROOM_MODEL_REL = Path("p2") / "room_model.json"
CAMERAS_REL = Path("p1") / "reconstruction" / "cameras.json"
SCENE_GRAPH_REL = Path("scene_graph.json")
SPARSE_CLOUD_REL = Path("p1") / "reconstruction" / "sparse_cloud.ply"
RUN_STATUS_REL = Path("run_status.json")


class DigitalTwin:
    """A single in-memory bundle of a run's room model, cameras, scene graph,
    and provenance, plus a path reference (never an embedded copy) to the
    sparse point cloud. This is the object twin.json serializes."""

    def __init__(
        self,
        provenance: Dict[str, Any],
        room_model: Optional[Dict[str, Any]] = None,
        cameras: Optional[List[Dict[str, Any]]] = None,
        scene_graph: Optional[Dict[str, Any]] = None,
        sparse_cloud_path: Optional[str] = None,
    ):
        self.provenance = provenance
        self.room_model = room_model
        self.cameras = cameras
        self.scene_graph = scene_graph
        self.sparse_cloud_path = sparse_cloud_path

    # ------------------------------------------------------------------
    # Build from in-memory parts (live sessions) or a run directory
    # ------------------------------------------------------------------

    @staticmethod
    def derived_provenance_fields(room_model: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """The provenance entries that follow from the room model itself:
        ``scale`` and the four measurement ``*_method`` tags (None when the
        model has none — never guessed)."""
        scale = (room_model or {}).get("scale") or {"metric_available": False, "scale_factor": 1.0}
        room = (room_model or {}).get("room") or {}
        return {
            "scale": scale,
            "measurement_methods": {
                "length_method": room.get("length_method"),
                "width_method": room.get("width_method"),
                "height_method": room.get("height_method"),
                "floor_area_method": room.get("floor_area_method"),
            },
        }

    @classmethod
    def from_parts(
        cls,
        room_model: Optional[Dict[str, Any]],
        cameras: Optional[List[Dict[str, Any]]],
        scene_graph: Optional[Dict[str, Any]],
        provenance: Dict[str, Any],
        sparse_cloud_path: Optional[str] = None,
    ) -> "DigitalTwin":
        """Assemble a twin from parts already in memory (a live session's
        current segment, or a run directory's files). ``provenance`` is taken
        as given except that ``scale`` and ``measurement_methods`` are filled
        from the room model when the caller did not supply them."""
        prov = dict(provenance)
        for key, value in cls.derived_provenance_fields(room_model).items():
            prov.setdefault(key, value)
        return cls(
            provenance=prov,
            room_model=room_model,
            cameras=cameras,
            scene_graph=scene_graph,
            sparse_cloud_path=sparse_cloud_path,
        )

    @classmethod
    def build_from_run_dir(cls, run_dir: Path) -> "DigitalTwin":
        run_dir = Path(run_dir)

        room_model_path = run_dir / ROOM_MODEL_REL
        cameras_path = run_dir / CAMERAS_REL
        scene_graph_path = run_dir / SCENE_GRAPH_REL
        sparse_cloud_path = run_dir / SPARSE_CLOUD_REL
        status_path = run_dir / RUN_STATUS_REL

        room_model = None
        if room_model_path.exists():
            with open(room_model_path, "r") as f:
                room_model = json.load(f)

        cameras = None
        if cameras_path.exists():
            with open(cameras_path, "r") as f:
                cameras = json.load(f)

        scene_graph = None
        if scene_graph_path.exists():
            with open(scene_graph_path, "r") as f:
                scene_graph = json.load(f)

        run_status: Dict[str, Any] = {}
        if status_path.exists():
            with open(status_path, "r") as f:
                run_status = json.load(f)
        # Never guessed: a run with no status file (e.g. an older run, or one
        # built by hand outside the CLI) is honestly "unknown", not assumed
        # to be either synthetic or real.
        input_type = run_status.get("input_type", "unknown")

        def rel_if_exists(p: Path) -> Optional[str]:
            return p.relative_to(run_dir).as_posix() if p.exists() else None

        provenance = {
            "run_dir": str(run_dir.resolve()),
            "source_files": {
                "room_model": rel_if_exists(room_model_path),
                "cameras": rel_if_exists(cameras_path),
                "scene_graph": rel_if_exists(scene_graph_path),
                "sparse_cloud": rel_if_exists(sparse_cloud_path),
            },
            "stage_status": run_status.get("stages", {}),
            "input_type": input_type,
        }
        provenance.update(cls.derived_provenance_fields(room_model))

        return cls.from_parts(
            room_model=room_model,
            cameras=cameras,
            scene_graph=scene_graph,
            provenance=provenance,
            sparse_cloud_path=rel_if_exists(sparse_cloud_path),
        )

    # ------------------------------------------------------------------
    # twin.json export/import
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provenance": self.provenance,
            "room_model": self.room_model,
            "cameras": self.cameras,
            "scene_graph": self.scene_graph,
            "sparse_cloud_path": self.sparse_cloud_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DigitalTwin":
        return cls(
            provenance=data.get("provenance", {}),
            room_model=data.get("room_model"),
            cameras=data.get("cameras"),
            scene_graph=data.get("scene_graph"),
            sparse_cloud_path=data.get("sparse_cloud_path"),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "DigitalTwin":
        with open(path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DigitalTwin):
            return NotImplemented
        return self.to_dict() == other.to_dict()
