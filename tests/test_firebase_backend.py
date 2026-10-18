import pytest
from visionforge.persistence.firebase_backend import FirebaseBackend


class FakeDocSnapshot:
    def __init__(self, data, exists=True):
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocumentRef:
    def __init__(self, doc_id, parent_col):
        self.id = doc_id
        self.parent_col = parent_col
        self._subcollections = {}

    def get(self):
        data = self.parent_col._data_store.get(self.id)
        return FakeDocSnapshot(data, exists=(data is not None))

    def set(self, data, merge=False):
        if merge and self.id in self.parent_col._data_store:
            self.parent_col._data_store[self.id].update(data)
        else:
            self.parent_col._data_store[self.id] = dict(data)

    def collection(self, name):
        if name not in self._subcollections:
            self._subcollections[name] = FakeCollectionRef(name)
        return self._subcollections[name]


class FakeCollectionRef:
    def __init__(self, name):
        self.name = name
        self._docs = {}
        self._data_store = {}

    def document(self, doc_id):
        if doc_id not in self._docs:
            self._docs[doc_id] = FakeDocumentRef(doc_id, self)
        return self._docs[doc_id]

    def order_by(self, field, direction="ASCENDING"):
        return self

    def limit(self, count):
        return self

    def where(self, field, op, val):
        filtered = FakeCollectionRef(self.name)
        for doc_id, data in self._data_store.items():
            if op == "==" and data.get(field) == val:
                filtered._data_store[doc_id] = dict(data)
                filtered._docs[doc_id] = FakeDocumentRef(doc_id, filtered)
        return filtered

    def get(self):
        return [FakeDocSnapshot(data, exists=True) for doc_id, data in self._data_store.items()]


class FakeFirestoreClient:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollectionRef(name)
        return self._collections[name]


class FakeBlob:
    def __init__(self, path, storage):
        self.path = path
        self.storage = storage

    def upload_from_string(self, content, content_type="application/octet-stream"):
        self.storage[self.path] = content

    def download_as_bytes(self):
        return self.storage.get(self.path, b"")

    def exists(self):
        return self.path in self.storage


class FakeStorageBucket:
    def __init__(self):
        self.storage = {}

    def blob(self, path):
        return FakeBlob(path, self.storage)


@pytest.fixture
def fake_firebase_backend():
    db = FakeFirestoreClient()
    bucket = FakeStorageBucket()
    return FirebaseBackend(
        project_id="test-visionforge",
        storage_bucket="test-visionforge.appspot.com",
        firestore_client=db,
        storage_bucket_client=bucket,
    )


def test_firebase_save_and_list_sessions(fake_firebase_backend):
    fake_firebase_backend.save_session(
        "sess-fb-1",
        input_type="physical_video",
        video_name="room_walk.mp4",
        status="success",
        user_id="user-123",
        scale_factor=1.25,
        metric_available=True,
    )

    sessions = fake_firebase_backend.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-fb-1"
    assert sessions[0]["scale_factor"] == 1.25
    assert sessions[0]["metric_available"] is True

    # User filter
    filtered = fake_firebase_backend.list_sessions(user_id="user-123")
    assert len(filtered) == 1
    assert fake_firebase_backend.list_sessions(user_id="other-user") == []


def test_firebase_versioned_models(fake_firebase_backend):
    v1 = fake_firebase_backend.save_room_model("sess-fb-1", {"room": {"width": 3.0}})
    v2 = fake_firebase_backend.save_room_model("sess-fb-1", {"room": {"width": 3.2}})
    assert v1 == 1
    assert v2 == 2

    # Twin versioning and fetch
    fake_firebase_backend.save_twin("sess-fb-1", {"id": "sess-fb-1", "twin_data": 42})
    twin = fake_firebase_backend.get_twin("sess-fb-1")
    assert twin is not None
    assert twin["twin_data"] == 42


def test_firebase_furniture_layout_persistence(fake_firebase_backend):
    assert fake_firebase_backend.get_furniture_layout("sess-fb-1") is None

    layout = {
        "placed_items": [
            {"id": "f1", "furniture_id": "bed_queen", "center_x": 1.0, "center_z": 2.0}
        ],
        "pack_spacing": 0.25,
    }
    fake_firebase_backend.save_furniture_layout("sess-fb-1", layout, user_id="user-123")

    restored = fake_firebase_backend.get_furniture_layout("sess-fb-1")
    assert restored is not None
    assert restored["placed_items"][0]["furniture_id"] == "bed_queen"
    assert restored["pack_spacing"] == 0.25


def test_firebase_artifact_storage(fake_firebase_backend):
    ply_bytes = b"ply\nformat ascii 1.0\nelement vertex 1\nend_header\n0 0 0\n"
    path = fake_firebase_backend.save_artifact(
        session_id="sess-fb-1",
        artifact_type="sparse_cloud",
        content=ply_bytes,
        filename="sparse_cloud.ply",
        user_id="user-123",
    )
    assert path == "sess-fb-1/sparse_cloud.ply"

    downloaded = fake_firebase_backend.get_artifact("sess-fb-1", "sparse_cloud")
    assert downloaded == ply_bytes

    artifacts = fake_firebase_backend.list_artifacts("sess-fb-1")
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_type"] == "sparse_cloud"
    assert artifacts[0]["byte_size"] == len(ply_bytes)
