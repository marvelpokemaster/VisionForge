from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PersistenceBackend(ABC):
    """Persists project-level digital twin data: sessions, room models, scene
    graphs, twins, measurements, experiment results, and processing status.

    Never stores frames, PLY point data, or per-frame poses -- those stay on
    disk under outputs/<run>/ and are referenced by path, not persisted here.
    """

    @abstractmethod
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
        ...

    @abstractmethod
    def save_room_model(self, session_id: str, room_model: Dict[str, Any]) -> int:
        """Saves a new versioned room_model row. Returns the version number."""
        ...

    @abstractmethod
    def save_scene_graph(self, session_id: str, scene_graph: Dict[str, Any]) -> int:
        """Saves a new versioned scene_graph row. Returns the version number."""
        ...

    @abstractmethod
    def save_twin(self, session_id: str, twin: Dict[str, Any]) -> int:
        """Saves a new versioned twin row. Returns the version number."""
        ...

    @abstractmethod
    def save_measurements(self, session_id: str, measurements: List[Dict[str, Any]]) -> None:
        """`measurements` is a list of {name, value, units, metric, method}."""
        ...

    @abstractmethod
    def save_experiment_result(self, session_id: str, key: str, data: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def save_processing_status(self, session_id: str, stages: Dict[str, str]) -> None:
        """`stages` is {stage_name: status}, e.g. run_status.json's "stages"."""
        ...

    @abstractmethod
    def save_furniture_layout(self, session_id: str, layout: Dict[str, Any], user_id: Optional[str] = None) -> None:
        """Saves or updates the furniture layout for a session."""
        ...

    @abstractmethod
    def get_furniture_layout(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the latest furniture layout for a session, or None."""
        ...

    @abstractmethod
    def save_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: bytes,
        filename: Optional[str] = None,
        user_id: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Saves or uploads an artifact (e.g. sparse_cloud.ply). Returns its storage path."""
        ...

    @abstractmethod
    def get_artifact(self, session_id: str, artifact_type: str) -> Optional[bytes]:
        """Retrieves raw artifact content by type, or None if not found."""
        ...

    @abstractmethod
    def list_artifacts(self, session_id: str) -> List[Dict[str, Any]]:
        """Lists metadata for all artifacts recorded for this session."""
        ...

    @abstractmethod
    def list_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every session this backend knows about, optionally filtered by user_id."""
        ...

    @abstractmethod
    def get_twin(self, session_id: str) -> Optional[Dict[str, Any]]:
        """The latest persisted twin payload for a session, or None."""
        ...

    @abstractmethod
    def get_session_owner(self, session_id: str) -> Optional[str]:
        """Returns the user_id owner of the session, or None if unowned/not found."""
        ...

