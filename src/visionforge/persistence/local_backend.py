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

    def save_session(
        self,
        session_id: str,
        input_type: str,
        video_name: Optional[str],
        status: str,
        user_id: Optional[str] = None,
        scale_factor: float = 1.0,
        metric_available: bool = False,
    ) -> None:
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
            "status": status,
            "user_id": user_id,
            "scale_factor": scale_factor,
            "metric_available": metric_available,
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

    def save_furniture_layout(self, session_id: str, layout: Dict[str, Any], user_id: Optional[str] = None) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / "furniture_layout.json"
        data = {
            "session_id": session_id,
            "user_id": user_id,
            "layout": layout,
            "updated_at": self._now(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def get_furniture_layout(self, session_id: str) -> Optional[Dict[str, Any]]:
        # Check persistence dir first, then session root
        for path in [
            self._session_dir(session_id) / "furniture_layout.json",
            self.outputs_root / session_id / "furniture_layout.json",
        ]:
            if path.exists():
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    return data.get("layout", data)
                except Exception:
                    continue
        return None

    def save_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: bytes,
        filename: Optional[str] = None,
        user_id: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        artifacts_dir = self._session_dir(session_id) / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{artifact_type}.bin"
        file_path = artifacts_dir / fname
        file_path.write_bytes(content)

        meta_path = self._session_dir(session_id) / "artifacts.json"
        artifacts_meta = []
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    artifacts_meta = json.load(f)
            except Exception:
                artifacts_meta = []

        # Remove existing if updating
        artifacts_meta = [a for a in artifacts_meta if a.get("artifact_type") != artifact_type]
        storage_path = str(file_path.relative_to(self.outputs_root))
        artifacts_meta.append({
            "session_id": session_id,
            "user_id": user_id,
            "artifact_type": artifact_type,
            "storage_path": storage_path,
            "byte_size": len(content),
            "content_type": content_type,
            "created_at": self._now(),
        })
        with open(meta_path, "w") as f:
            json.dump(artifacts_meta, f, indent=2)
        return storage_path

    def get_artifact(self, session_id: str, artifact_type: str) -> Optional[bytes]:
        meta_path = self._session_dir(session_id) / "artifacts.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                for a in meta:
                    if a.get("artifact_type") == artifact_type:
                        p = self.outputs_root / a["storage_path"]
                        if p.exists():
                            return p.read_bytes()
            except Exception:
                pass
        return None

    def list_artifacts(self, session_id: str) -> List[Dict[str, Any]]:
        meta_path = self._session_dir(session_id) / "artifacts.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def list_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.outputs_root.exists():
            return []
        sessions = []
        for child in sorted(self.outputs_root.iterdir()):
            session_file = child / "persistence" / "session.json"
            if session_file.exists():
                with open(session_file, "r") as f:
                    rec = json.load(f)
                if user_id is None or rec.get("user_id") == user_id or rec.get("user_id") is None:
                    sessions.append(rec)
        return sessions

    def get_twin(self, session_id: str) -> Optional[Dict[str, Any]]:
        record = self._latest_versioned(session_id, "twins")
        return record["payload"] if record else None

