def test_login_success(client, auth):
    token = auth(client, "demo", "demo1234")
    assert token


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "demo", "password": "wrong"})
    assert resp.status_code == 401


def test_chat_requires_auth(client):
    resp = client.post("/api/chat", json={"message": "你好", "session_id": "s"})
    assert resp.status_code == 401


def test_forged_token_rejected(client):
    resp = client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "s"},
        headers={"Authorization": "Bearer forged.token.value"},
    )
    assert resp.status_code == 401


def test_token_missing_permission(client, auth):
    token = auth(client, "racer", "racer1234")
    resp = client.get("/api/history/x", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403