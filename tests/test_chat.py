from tests.conftest import sse_events


def test_chat_flow_and_done(client, auth):
    token = auth(client, "demo", "demo1234")
    resp = client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "flow"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    events = sse_events(resp.text)
    types = {e["type"] for e in events}
    assert "token" in types
    assert "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["request_id"]


def test_tool_trigger_redis(client, auth):
    token = auth(client, "demo", "demo1234")
    resp = client.post(
        "/api/chat",
        json={"message": "Redis 内存告警，连接池报错，帮我排查", "session_id": "tool"},
        headers={"Authorization": f"Bearer {token}"},
    )
    events = sse_events(resp.text)
    tools = [e["name"] for e in events if e["type"] == "tool_result"]
    assert "query_redis_status" in tools
    assert "search_error_logs" in tools


def test_kb_retrieval_trigger(client, auth):
    token = auth(client, "demo", "demo1234")
    resp = client.post(
        "/api/chat",
        json={"message": "什么是缓存穿透，如何解决？", "session_id": "kb"},
        headers={"Authorization": f"Bearer {token}"},
    )
    events = sse_events(resp.text)
    assert any(e["type"] == "tool_result" and e["name"] == "get_kb_doc" for e in events)
    doc = next(e for e in events if e["type"] == "tool_result" and e["name"] == "get_kb_doc")
    assert "缓存" in doc["content"]


def test_semantic_cache_hit(client, auth):
    token = auth(client, "demo", "demo1234")
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(2):
        resp = client.post("/api/chat", json={"message": "你好", "session_id": "cache"}, headers=headers)
    events = sse_events(resp.text)
    assert any(e["type"] == "info" and "命中语义缓存" in e["content"] for e in events)


def test_rate_limit_429(client, auth):
    token = auth(client, "racer", "racer1234")
    headers = {"Authorization": f"Bearer {token}"}
    statuses = []
    for _ in range(14):
        resp = client.post("/api/chat", json={"message": "你好", "session_id": "rl"}, headers=headers)
        statuses.append(resp.status_code)
    assert 429 in statuses