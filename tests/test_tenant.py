from tests.conftest import sse_events


def test_cross_tenant_history_404(client, auth):
    demo = auth(client, "demo", "demo1234")
    bob = auth(client, "bob", "bob1234")

    resp = client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "shared"},
        headers={"Authorization": f"Bearer {demo}"},
    )
    assert resp.status_code == 200

    ok = client.get("/api/history/shared", headers={"Authorization": f"Bearer {demo}"})
    assert ok.status_code == 200

    denied = client.get("/api/history/shared", headers={"Authorization": f"Bearer {bob}"})
    assert denied.status_code == 404


def test_unknown_session_404(client, auth):
    token = auth(client, "demo", "demo1234")
    resp = client.get("/api/history/nope", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_cross_tenant_trace_404(client, auth):
    demo = auth(client, "demo", "demo1234")
    bob = auth(client, "bob", "bob1234")

    resp = client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "trace1"},
        headers={"Authorization": f"Bearer {demo}"},
    )
    done = next(e for e in sse_events(resp.text) if e["type"] == "done")
    rid = done["request_id"]

    ok = client.get(f"/api/traces/{rid}", headers={"Authorization": f"Bearer {demo}"})
    assert ok.status_code == 200
    assert ok.json()["query_text"] == "你好"

    denied = client.get(f"/api/traces/{rid}", headers={"Authorization": f"Bearer {bob}"})
    assert denied.status_code == 404


def test_trace_list(client, auth):
    token = auth(client, "demo", "demo1234")
    resp = client.get("/api/traces", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["traces"], list)