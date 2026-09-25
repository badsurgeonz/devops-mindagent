import json
import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / "mindagent_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["APP_ENV"] = "test"
os.environ["MOCK_MODE"] = "true"
os.environ["JWT_SECRET"] = "test-secret-for-unit-tests-0123456789"
os.environ["JWT_ISSUER"] = "devops-mindagent-test"
os.environ["DATABASE_URL"] = "sqlite:///" + str(_TEST_DB).replace("\\", "/")
os.environ["RATE_RATE"] = "0.0"
os.environ["RATE_CAP"] = "12"
os.environ["SEED_USERS"] = json.dumps(
    [
        {
            "id": "1", "tenant_id": "tenant-a", "username": "demo", "password": "demo1234",
            "roles": ["developer"],
            "permissions": ["chat:use", "history:read", "history:delete", "tool:logs:read", "tool:redis:read", "trace:read", "kb:manage"],
        },
        {
            "id": "2", "tenant_id": "tenant-a", "username": "alice", "password": "alice1234",
            "roles": ["developer"],
            "permissions": ["chat:use", "history:read", "history:delete", "trace:read", "kb:manage"],
        },
        {
            "id": "3", "tenant_id": "tenant-b", "username": "bob", "password": "bob1234",
            "roles": ["developer"],
            "permissions": ["chat:use", "history:read", "history:delete", "tool:logs:read", "tool:redis:read", "trace:read", "kb:manage"],
        },
        {
            "id": "4", "tenant_id": "tenant-a", "username": "racer", "password": "racer1234",
            "roles": ["developer"], "permissions": ["chat:use"],
        },
    ]
)

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth():
    tokens = {}

    def _auth(c: TestClient, username: str, password: str) -> str:
        if username in tokens:
            return tokens[username]
        resp = c.post("/api/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        tokens[username] = resp.json()["access_token"]
        return tokens[username]

    return _auth


def sse_events(text: str) -> list:
    events = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    return events