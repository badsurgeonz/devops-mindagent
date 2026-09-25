from tests.conftest import sse_events


def test_tool_permission_denied(client, auth):
    alice = auth(client, "alice", "alice1234")
    resp = client.post(
        "/api/chat",
        json={"message": "Redis 内存告警，帮我排查", "session_id": "p1"},
        headers={"Authorization": f"Bearer {alice}"},
    )
    events = sse_events(resp.text)
    denied = [e for e in events if e["type"] == "tool_result" and e["name"] == "query_redis_status"]
    assert denied and "PERMISSION_DENIED" in denied[0]["content"]


def test_tool_permission_allowed(client, auth):
    demo = auth(client, "demo", "demo1234")
    resp = client.post(
        "/api/chat",
        json={"message": "Redis 内存告警，帮我排查", "session_id": "p2"},
        headers={"Authorization": f"Bearer {demo}"},
    )
    events = sse_events(resp.text)
    ok = [e for e in events if e["type"] == "tool_result" and e["name"] == "query_redis_status"]
    assert ok and "used_memory" in ok[0]["content"]


def test_log_redaction(client, auth):
    demo = auth(client, "demo", "demo1234")
    resp = client.post(
        "/api/chat",
        json={"message": "order-service 500 报错，查看日志", "session_id": "p3"},
        headers={"Authorization": f"Bearer {demo}"},
    )
    events = sse_events(resp.text)
    logs = [e for e in events if e["type"] == "tool_result" and e["name"] == "search_error_logs"]
    assert logs
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in logs[0]["content"]
    assert "Authorization: ***" in logs[0]["content"]