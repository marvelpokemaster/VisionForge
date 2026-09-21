from typing import Any, Dict, List, Optional

# Importing `supabase` is only reached when this module is imported, which
# only happens when SupabaseBackend is actually selected (see
# persistence/__init__.py's get_backend) -- the offline pipeline never
# imports supabase-py otherwise.
from supabase import create_client

from visionforge.persistence.backend import PersistenceBackend


class SupabaseBackend(PersistenceBackend):
    """Configured only via SUPABASE_URL / SUPABASE_KEY (never hardcoded).
    `client` can be injected directly (e.g. a fake, for tests) to avoid any
    network access."""

    def __init__(self, url: str, key: str, client: Optional[Any] = None):
        self.client = client if client is not None else create_client(url, key)

    def _next_version(self, table: str, session_id: str) -> int:
        result = (
            self.client.table(table)
            .select("version")
            .eq("session_id", session_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return int(result.data[0]["version"]) + 1
        return 1

    def _save_versioned(self, table: str, session_id: str, payload: Dict[str, Any]) -> int:
        version = self._next_version(table, session_id)
        self.client.table(table).insert({
            "session_id": session_id,
            "version": version,
            "payload": payload
        }).execute()
        return version

    def _latest_versioned(self, table: str, session_id: str) -> Optional[Dict[str, Any]]:
        result = (
            self.client.table(table)
            .select("*")
            .eq("session_id", session_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # ------------------------------------------------------------------

    def save_session(self, session_id: str, input_type: str, video_name: Optional[str], status: str) -> None:
        self.client.table("sessions").upsert({
            "id": session_id,
            "input_type": input_type,
            "video_name": video_name,
            "status": status
        }, on_conflict="id").execute()

    def save_room_model(self, session_id: str, room_model: Dict[str, Any]) -> int:
        return self._save_versioned("room_models", session_id, room_model)

    def save_scene_graph(self, session_id: str, scene_graph: Dict[str, Any]) -> int:
        return self._save_versioned("scene_graphs", session_id, scene_graph)

    def save_twin(self, session_id: str, twin: Dict[str, Any]) -> int:
        return self._save_versioned("twins", session_id, twin)

    def save_measurements(self, session_id: str, measurements: List[Dict[str, Any]]) -> None:
        rows = [
            {
                "session_id": session_id,
                "name": m["name"],
                "value": m.get("value"),
                "units": m.get("units"),
                "metric": m.get("metric"),
                "method": m.get("method")
            }
            for m in measurements
        ]
        if rows:
            self.client.table("measurements").insert(rows).execute()

    def save_experiment_result(self, session_id: str, key: str, data: Dict[str, Any]) -> None:
        self.client.table("experiment_results").insert({
            "session_id": session_id,
            "key": key,
            "json": data
        }).execute()

    def save_processing_status(self, session_id: str, stages: Dict[str, str]) -> None:
        rows = [{"session_id": session_id, "stage": stage, "status": status} for stage, status in stages.items()]
        if rows:
            self.client.table("processing_status").insert(rows).execute()

    def list_sessions(self) -> List[Dict[str, Any]]:
        result = self.client.table("sessions").select("*").execute()
        return result.data or []

    def get_twin(self, session_id: str) -> Optional[Dict[str, Any]]:
        record = self._latest_versioned("twins", session_id)
        return record["payload"] if record else None
