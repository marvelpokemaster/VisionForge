import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from visionforge.persistence.backend import PersistenceBackend


class LocalJsonBackend(PersistenceBackend):
    """Zero-config default: writes each session's persisted artefacts under
    outputs/<session_id>/persistence/ as plain JSON files. No server, no
    credentials -- always available."""

    def __init__(self, outputs_root: Path = Path("outputs")):
        self.outputs_root = Path(outputs_root)

    def _session_dir(self, session_id: str) -> Path:
        return self.outputs_root / session_id / "persistence"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _next_version(self, session_id: str, collection: str) -> int:
        directory = self._session_dir(session_id) / collection
        if not directory.exists():
            return 1
        versions = []
        for f in directory.glob("v*.json"):
            try:
                versions.append(int(f.stem[1:]))
            except ValueError:
                continue
        return (max(versions) + 1) if versions else 1

    def _save_versioned(self, session_id: str, collection: str, payload: Dict[str, Any]) -> int:
        version = self._next_version(session_id, collection)
        directory = self._session_dir(session_id) / collection
        directory.mkdir(parents=True, exist_ok=True)
        record = {"session_id": session_id, "version": version, "payload": payload, "created_at": self._now()}
        with open(directory / f"v{version}.json", "w") as f:
            json.dump(record, f, indent=2)
        return version

    def _latest_versioned(self, session_id: str, collection: str) -> Optional[Dict[str, Any]]:
        directory = self._session_dir(session_id) / collection
        if not directory.exists():
            return None
        best_version, best_record = None, None
        for f in directory.glob("v*.json"):
            try:
                v = int(f.stem[1:])
            except ValueError:
                continue
            if best_version is None or v > best_version:
                with open(f, "r") as fh:
                    record = json.load(fh)
                best_version, best_record = v, record
        return best_record

    # ------------------------------------------------------------------

    def save_session(self, session_id: str, input_type: str, video_name: Optional[str], status: str) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / "session.json"
        created_at = self._now()
        if path.exists():
            with open(path, "r") as f:
                existing = json.load(f)
            created_at = existing.get("created_at", created_at)
        record = {
            "id": session_id,
            "created_at": created_at,
            "input_type": input_type,
            "video_name": video_name,
            "status": status
        }
        with open(path, "w") as f:
            json.dump(record, f, indent=2)

    def save_room_model(self, session_id: str, room_model: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "room_models", room_model)

    def save_scene_graph(self, session_id: str, scene_graph: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "scene_graphs", scene_graph)

    def save_twin(self, session_id: str, twin: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "twins", twin)

    def save_measurements(self, session_id: str, measurements: List[Dict[str, Any]]) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "measurements.json", "w") as f:
            json.dump({"session_id": session_id, "measurements": measurements, "created_at": self._now()}, f, indent=2)

    def save_experiment_result(self, session_id: str, key: str, data: Dict[str, Any]) -> None:
        directory = self._session_dir(session_id) / "experiment_results"
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / f"{key}.json", "w") as f:
            json.dump({"session_id": session_id, "key": key, "json": data, "created_at": self._now()}, f, indent=2)

    def save_processing_status(self, session_id: str, stages: Dict[str, str]) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "processing_status.json", "w") as f:
            json.dump({"session_id": session_id, "stages": stages, "updated_at": self._now()}, f, indent=2)

    def list_sessions(self) -> List[Dict[str, Any]]:
        if not self.outputs_root.exists():
            return []
        sessions = []
        for child in sorted(self.outputs_root.iterdir()):
            session_file = child / "persistence" / "session.json"
            if session_file.exists():
                with open(session_file, "r") as f:
                    sessions.append(json.load(f))
        return sessions

    def get_twin(self, session_id: str) -> Optional[Dict[str, Any]]:
        record = self._latest_versioned(session_id, "twins")
        return record["payload"] if record else None
