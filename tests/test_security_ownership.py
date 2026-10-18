import json
import base64
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from visionforge.api.app import create_app
from visionforge.persistence.firebase_backend import FirebaseBackend
from visionforge.persistence.local_backend import LocalJsonBackend


def _make_fake_jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.fake_sig"


def test_firebase_backend_rejects_invalid_token_without_fallback(tmp_path):
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    backend = FirebaseBackend(firestore_client=mock_db, storage_bucket_client=mock_bucket)

    app = create_app(outputs_root=tmp_path, backend=backend)
    client = TestClient(app)

    with patch("firebase_admin.auth.verify_id_token", side_effect=Exception("Invalid token signature")):
        fake_token = _make_fake_jwt({"sub": "malicious-user-id"})
        resp = client.get("/sessions", headers={"Authorization": f"Bearer {fake_token}"})
        assert resp.status_code == 401
        assert "Firebase authentication failed" in resp.json()["detail"]


def test_firebase_backend_accepts_verified_token(tmp_path):
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    backend = FirebaseBackend(firestore_client=mock_db, storage_bucket_client=mock_bucket)

    # Mock list_sessions
    mock_col = MagicMock()
    mock_query = MagicMock()
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = {"id": "sess-fb-1", "user_id": "verified-uid-123"}
    mock_query.get.return_value = [mock_doc]
    mock_col.where.return_value = mock_query
    mock_db.collection.return_value = mock_col

    app = create_app(outputs_root=tmp_path, backend=backend)
    client = TestClient(app)

    with patch("firebase_admin.auth.verify_id_token", return_value={"uid": "verified-uid-123"}):
        resp = client.get("/sessions", headers={"Authorization": "Bearer valid-firebase-token"})
        assert resp.status_code == 200
        sessions = resp.json()
        assert any(s["id"] == "sess-fb-1" for s in sessions)


def test_cross_user_session_access_denied_403(tmp_path):
    # Setup session owned by user_alice
    session_dir = tmp_path / "sess_alice"
    session_dir.mkdir(parents=True)
    p2 = session_dir / "p2"
    p2.mkdir(parents=True)
    (p2 / "room_model.json").write_text(json.dumps({"room": {"length": 5.0, "width": 4.0}}))
    (session_dir / "scene_graph.json").write_text(json.dumps({"nodes": []}))

    backend = LocalJsonBackend(outputs_root=tmp_path)
    backend.save_session(
        session_id="sess_alice",
        input_type="synthetic",
        video_name=None,
        status="success",
        user_id="user_alice",
    )

    app = create_app(outputs_root=tmp_path)
    app.state.backend = backend
    client = TestClient(app)

    alice_token = _make_fake_jwt({"sub": "user_alice"})
    bob_token = _make_fake_jwt({"sub": "user_bob"})

    # 1. Alice can access her session
    resp_alice = client.get("/sessions/sess_alice", headers={"Authorization": f"Bearer {alice_token}"})
    assert resp_alice.status_code == 200
    assert resp_alice.json()["id"] == "sess_alice"

    # 2. Bob is denied with 403 Forbidden
    resp_bob = client.get("/sessions/sess_alice", headers={"Authorization": f"Bearer {bob_token}"})
    assert resp_bob.status_code == 403
    assert "Forbidden: You do not own this session" in resp_bob.json()["detail"]

    # 3. Bob cannot access room model or twin
    resp_bob_rm = client.get("/sessions/sess_alice/room_model", headers={"Authorization": f"Bearer {bob_token}"})
    assert resp_bob_rm.status_code == 403

    resp_bob_twin = client.get("/sessions/sess_alice/twin", headers={"Authorization": f"Bearer {bob_token}"})
    assert resp_bob_twin.status_code == 403

    # 4. Bob cannot save layout to Alice's session
    resp_bob_layout = client.post(
        "/sessions/sess_alice/furniture/layout",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={"placed_items": [], "pack_spacing": 0.3},
    )
    assert resp_bob_layout.status_code == 403

    # 5. Bob listing sessions does not see Alice's session
    resp_bob_list = client.get("/sessions", headers={"Authorization": f"Bearer {bob_token}"})
    assert resp_bob_list.status_code == 200
    listed_ids = [s["id"] for s in resp_bob_list.json()]
    assert "sess_alice" not in listed_ids

    # 6. Alice listing sessions DOES see her session
    resp_alice_list = client.get("/sessions", headers={"Authorization": f"Bearer {alice_token}"})
    assert resp_alice_list.status_code == 200
    listed_ids_alice = [s["id"] for s in resp_alice_list.json()]
    assert "sess_alice" in listed_ids_alice


def test_production_rejects_unverified_jwt(tmp_path, monkeypatch):
    monkeypatch.setenv("VISIONFORGE_ENV", "production")
    app = create_app(outputs_root=tmp_path)
    client = TestClient(app)

    fake_jwt = _make_fake_jwt({"sub": "any-user"})
    resp = client.get("/sessions", headers={"Authorization": f"Bearer {fake_jwt}"})
    assert resp.status_code == 401
    assert "could not be verified by production backend" in resp.json()["detail"]
