import datetime
import os
from typing import Any, Dict, List, Optional

from visionforge.persistence.backend import PersistenceBackend


class FirebaseBackend(PersistenceBackend):
    """Cloud Firestore and Cloud Storage for Firebase persistence backend.
    Stores session metadata, versioned models, measurements, and furniture layouts
    in Firestore, and binary artifacts (.ply) in Cloud Storage."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        storage_bucket: Optional[str] = None,
        firestore_client: Any = None,
        storage_bucket_client: Any = None,
    ):
        self.project_id = project_id or os.environ.get("FIREBASE_PROJECT_ID", "visionforge-spatial")
        self.storage_bucket_name = storage_bucket or os.environ.get(
            "FIREBASE_STORAGE_BUCKET", f"{self.project_id}.firebasestorage.app"
        )
        self._db = firestore_client
        self._bucket = storage_bucket_client

    def _init_firebase_app(self) -> None:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred = None
            sa_key = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")
            if sa_key:
                import json
                if sa_key.strip().startswith("{"):
                    cred = credentials.Certificate(json.loads(sa_key))
                elif os.path.exists(sa_key):
                    cred = credentials.Certificate(sa_key)
            options = {
                "projectId": self.project_id,
                "storageBucket": self.storage_bucket_name,
            }
            firebase_admin.initialize_app(credential=cred, options=options)

    @property
    def db(self) -> Any:
        if self._db is None:
            from firebase_admin import firestore
            self._init_firebase_app()
            self._db = firestore.client()
        return self._db

    @property
    def bucket(self) -> Any:
        if self._bucket is None:
            from firebase_admin import storage
            self._init_firebase_app()
            self._bucket = storage.bucket(self.storage_bucket_name)
        return self._bucket

    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

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
        doc_ref = self.db.collection("sessions").document(session_id)
        snapshot = doc_ref.get()
        created_at = self._now()
        if snapshot.exists:
            existing = snapshot.to_dict() or {}
            created_at = existing.get("created_at", created_at)

        data = {
            "id": session_id,
            "created_at": created_at,
            "input_type": input_type,
            "video_name": video_name,
            "status": status,
            "user_id": user_id,
            "scale_factor": scale_factor,
            "metric_available": metric_available,
            "updated_at": self._now(),
        }
        doc_ref.set(data, merge=True)

    def _save_versioned(self, session_id: str, collection_name: str, payload: Dict[str, Any]) -> int:
        col_ref = self.db.collection("sessions").document(session_id).collection(collection_name)
        # Determine latest version
        latest_docs = col_ref.order_by("version", direction="DESCENDING").limit(1).get()
        latest_version = 0
        for d in latest_docs:
            latest_version = d.to_dict().get("version", 0)
        version = latest_version + 1

        record = {
            "session_id": session_id,
            "version": version,
            "payload": payload,
            "created_at": self._now(),
        }
        col_ref.document(f"v{version}").set(record)
        return version

    def save_room_model(self, session_id: str, room_model: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "room_models", room_model)

    def save_scene_graph(self, session_id: str, scene_graph: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "scene_graphs", scene_graph)

    def save_twin(self, session_id: str, twin: Dict[str, Any]) -> int:
        return self._save_versioned(session_id, "twins", twin)

    def save_measurements(self, session_id: str, measurements: List[Dict[str, Any]]) -> None:
        doc_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("measurements")
            .document("latest")
        )
        doc_ref.set({
            "session_id": session_id,
            "measurements": measurements,
            "updated_at": self._now(),
        })

    def save_experiment_result(self, session_id: str, key: str, data: Dict[str, Any]) -> None:
        doc_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("experiments")
            .document(key)
        )
        doc_ref.set({
            "session_id": session_id,
            "key": key,
            "data": data,
            "updated_at": self._now(),
        })

    def save_processing_status(self, session_id: str, stages: Dict[str, str]) -> None:
        doc_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("status")
            .document("processing")
        )
        doc_ref.set({
            "session_id": session_id,
            "stages": stages,
            "updated_at": self._now(),
        })

    def save_furniture_layout(self, session_id: str, layout: Dict[str, Any], user_id: Optional[str] = None) -> None:
        doc_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("furniture_layouts")
            .document("current")
        )
        data: Dict[str, Any] = {
            "session_id": session_id,
            "layout": layout,
            "updated_at": self._now(),
        }
        if user_id is not None:
            data["user_id"] = user_id
        doc_ref.set(data)

    def get_furniture_layout(self, session_id: str) -> Optional[Dict[str, Any]]:
        doc_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("furniture_layouts")
            .document("current")
        )
        snapshot = doc_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict() or {}
            return data.get("layout", data)
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
        fname = filename or f"{artifact_type}.bin"
        storage_path = f"{session_id}/{fname}"

        # Upload to Cloud Storage
        blob = self.bucket.blob(storage_path)
        blob.upload_from_string(content, content_type=content_type)

        # Record metadata in Firestore
        meta_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("artifacts")
            .document(artifact_type)
        )
        meta = {
            "session_id": session_id,
            "artifact_type": artifact_type,
            "storage_path": storage_path,
            "byte_size": len(content),
            "content_type": content_type,
            "user_id": user_id,
            "created_at": self._now(),
        }
        meta_ref.set(meta)
        return storage_path

    def get_artifact(self, session_id: str, artifact_type: str) -> Optional[bytes]:
        meta_ref = (
            self.db.collection("sessions")
            .document(session_id)
            .collection("artifacts")
            .document(artifact_type)
        )
        snapshot = meta_ref.get()
        if not snapshot.exists:
            # Fallback direct path check in storage bucket
            try:
                blob = self.bucket.blob(f"{session_id}/{artifact_type}.ply")
                if blob.exists():
                    return blob.download_as_bytes()
            except Exception:
                pass
            return None

        storage_path = (snapshot.to_dict() or {}).get("storage_path")
        if not storage_path:
            return None

        try:
            blob = self.bucket.blob(storage_path)
            return blob.download_as_bytes()
        except Exception:
            return None

    def list_artifacts(self, session_id: str) -> List[Dict[str, Any]]:
        artifacts_ref = self.db.collection("sessions").document(session_id).collection("artifacts")
        docs = artifacts_ref.get()
        return [d.to_dict() for d in docs]

    def list_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        col_ref = self.db.collection("sessions")
        if user_id is not None:
            try:
                from google.cloud.firestore_v1.base_query import FieldFilter
                docs = col_ref.where(filter=FieldFilter("user_id", "==", user_id)).get()
            except Exception:
                docs = col_ref.where("user_id", "==", user_id).get()
        else:
            docs = col_ref.get()
        return [d.to_dict() for d in docs]

    def get_twin(self, session_id: str) -> Optional[Dict[str, Any]]:
        col_ref = self.db.collection("sessions").document(session_id).collection("twins")
        docs = col_ref.order_by("version", direction="DESCENDING").limit(1).get()
        for d in docs:
            return (d.to_dict() or {}).get("payload")
        return None

    def get_session_owner(self, session_id: str) -> Optional[str]:
        doc_ref = self.db.collection("sessions").document(session_id)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return (snapshot.to_dict() or {}).get("user_id")
        return None
