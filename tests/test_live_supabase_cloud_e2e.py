import os
import json
import pytest
from fastapi.testclient import TestClient

from visionforge.api.app import create_app
from visionforge.persistence.supabase_backend import SupabaseBackend


@pytest.fixture(scope="module")
def supabase_credentials():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        pytest.skip("SUPABASE_URL and SUPABASE_KEY environment variables required for live cloud e2e test")
    return url, key


@pytest.fixture(scope="module")
def supabase_backend(supabase_credentials):
    url, key = supabase_credentials
    return SupabaseBackend(url=url, key=key)


@pytest.fixture(scope="module")
def test_users(supabase_backend):
    """Creates two isolated test users in Supabase Auth and cleans them up after testing."""
    admin = supabase_backend.client.auth.admin
    user_a = admin.create_user({
        "email": "vf_test_alice@visionforge.internal",
        "password": "Password123!Secure",
        "email_confirm": True,
    })
    user_b = admin.create_user({
        "email": "vf_test_bob@visionforge.internal",
        "password": "Password123!Secure",
        "email_confirm": True,
    })

    # Sign in as each user to get valid session access tokens
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    anon_client = create_client(url, key)

    sess_a = anon_client.auth.sign_in_with_password({
        "email": "vf_test_alice@visionforge.internal",
        "password": "Password123!Secure",
    })
    sess_b = anon_client.auth.sign_in_with_password({
        "email": "vf_test_bob@visionforge.internal",
        "password": "Password123!Secure",
    })

    yield {
        "alice": {"id": user_a.user.id, "token": sess_a.session.access_token},
        "bob": {"id": user_b.user.id, "token": sess_b.session.access_token},
    }

    # Teardown: delete test users
    try:
        admin.delete_user(user_a.user.id)
    except Exception:
        pass
    try:
        admin.delete_user(user_b.user.id)
    except Exception:
        pass


def test_live_cloud_e2e_rejection_of_unauthenticated_and_invalid(tmp_path, supabase_backend, monkeypatch):
    monkeypatch.setenv("VISIONFORGE_ENV", "production")
    monkeypatch.setenv("VISIONFORGE_REQUIRE_AUTH", "1")

    app = create_app(outputs_root=tmp_path, backend=supabase_backend)
    client = TestClient(app)

    # 1. Anonymous request rejected
    resp = client.get("/sessions")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]

    # 2. Invalid bearer token rejected
    resp = client.get("/sessions", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401

    # 3. Forged JWT rejected (production must verify with Supabase)
    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJmYWtlLXVzZXIifQ.fake_signature"
    resp = client.get("/sessions", headers={"Authorization": f"Bearer {fake_jwt}"})
    assert resp.status_code == 401


def test_live_cloud_e2e_user_persistence_and_cross_user_isolation(tmp_path, supabase_backend, test_users, monkeypatch):
    monkeypatch.setenv("VISIONFORGE_ENV", "production")
    monkeypatch.setenv("VISIONFORGE_REQUIRE_AUTH", "1")

    alice = test_users["alice"]
    bob = test_users["bob"]
    session_id = f"test-cloud-session-{alice['id'][:8]}"

    # Start FastAPI app
    app = create_app(outputs_root=tmp_path, backend=supabase_backend)
    client = TestClient(app)

    # 1. Alice creates her session
    supabase_backend.save_session(
        session_id=session_id,
        input_type="synthetic",
        video_name="room.mp4",
        status="success",
        user_id=alice["id"],
    )

    # 2. Alice lists sessions and sees her session
    resp = client.get("/sessions", headers={"Authorization": f"Bearer {alice['token']}"})
    assert resp.status_code == 200
    listed_ids = [s["id"] for s in resp.json()]
    assert session_id in listed_ids

    # 3. Bob lists sessions and DOES NOT see Alice's session
    resp_bob = client.get("/sessions", headers={"Authorization": f"Bearer {bob['token']}"})
    assert resp_bob.status_code == 200
    listed_ids_bob = [s["id"] for s in resp_bob.json()]
    assert session_id not in listed_ids_bob

    # 4. Bob tries to access Alice's session directly -> 403 Forbidden
    resp_bob_direct = client.get(f"/sessions/{session_id}", headers={"Authorization": f"Bearer {bob['token']}"})
    assert resp_bob_direct.status_code == 403
    assert "Forbidden" in resp_bob_direct.json()["detail"]

    # 5. Alice persists room model and twin
    v_rm = supabase_backend.save_room_model(session_id, {"room": {"length": 5.2, "width": 3.8}})
    assert v_rm >= 1
    v_tw = supabase_backend.save_twin(session_id, {"provenance": {"input_type": "synthetic"}, "version": 1})
    assert v_tw >= 1

    # 6. Alice saves furniture layout
    layout_data = {
        "placed_items": [{"furniture_id": "armchair_1", "center_x": 1.2, "center_z": -0.5, "angle_deg": 90.0}],
        "pack_spacing": 0.35,
    }
    resp_layout = client.post(
        f"/sessions/{session_id}/furniture/layout",
        headers={"Authorization": f"Bearer {alice['token']}"},
        json=layout_data,
    )
    assert resp_layout.status_code == 200

    # 7. Bob cannot access or save layout to Alice's session -> 403
    resp_bob_layout_get = client.get(f"/sessions/{session_id}/furniture/layout", headers={"Authorization": f"Bearer {bob['token']}"})
    assert resp_bob_layout_get.status_code == 403

    resp_bob_layout_post = client.post(
        f"/sessions/{session_id}/furniture/layout",
        headers={"Authorization": f"Bearer {bob['token']}"},
        json=layout_data,
    )
    assert resp_bob_layout_post.status_code == 403

    # 8. Artifact upload and retrieval through Supabase Storage
    ply_content = b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n1 0 0\n0 1 0\n"
    storage_path = supabase_backend.save_artifact(
        session_id=session_id,
        artifact_type="sparse_cloud",
        content=ply_content,
        filename="sparse_cloud.ply",
        user_id=alice["id"],
    )
    assert storage_path.startswith(session_id)

    downloaded = supabase_backend.get_artifact(session_id, "sparse_cloud")
    assert downloaded == ply_content, "Downloaded artifact content mismatch"

    # 9. Verify server restart survivability
    # Create a fresh app instance with a brand new SessionStore
    fresh_app = create_app(outputs_root=tmp_path / "fresh_outputs", backend=supabase_backend)
    fresh_client = TestClient(fresh_app)

    # Alice can still access and reload her cloud data after server restart
    resp_fresh = fresh_client.get("/sessions", headers={"Authorization": f"Bearer {alice['token']}"})
    assert resp_fresh.status_code == 200
    assert session_id in [s["id"] for s in resp_fresh.json()]

    resp_fresh_layout = fresh_client.get(
        f"/sessions/{session_id}/furniture/layout",
        headers={"Authorization": f"Bearer {alice['token']}"},
    )
    assert resp_fresh_layout.status_code == 200
    assert resp_fresh_layout.json()["placed_items"][0]["furniture_id"] == "armchair_1"

    # 10. Clean up test session data
    supabase_backend.client.table("sessions").delete().eq("id", session_id).execute()
    try:
        supabase_backend.client.storage.from_("visionforge-artifacts").remove([storage_path])
    except Exception:
        pass
