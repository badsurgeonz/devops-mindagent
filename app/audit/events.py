import uuid
from datetime import datetime, timezone


def new_event_id() -> str:
    return uuid.uuid4().hex


def envelope(event_type: str, payload: dict, request_id: str, tenant_id: str, user_id: str, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or new_event_id(),
        "event_type": event_type,
        "schema_version": 1,
        "request_id": request_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def trace_completed(trace: dict) -> dict:
    return envelope("agent.trace.completed", trace, trace["request_id"], trace["tenant_id"], trace["user_id"])


def tool_call(call: dict) -> dict:
    return envelope("agent.tool.call", call, call["request_id"], call["tenant_id"], call["user_id"])


def security(event_type: str, detail: dict, request_id: str, tenant_id: str, user_id: str) -> dict:
    return envelope(event_type, detail, request_id, tenant_id, user_id)