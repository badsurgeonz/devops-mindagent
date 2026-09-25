import json
import time

from app.config import cfg


class KVTraceStore:
    def __init__(self, kv) -> None:
        self.kv = kv

    def _key(self, request_id: str) -> str:
        return f"trace:{request_id}"

    def _index_key(self, tenant_id: str, user_id: str) -> str:
        return f"trace:index:{tenant_id}:{user_id}"

    async def save_trace(self, record: dict) -> None:
        record["created_ts"] = time.time()
        await self.kv.set_json(self._key(record["request_id"]), record, ttl=86400 * 7)
        index = await self.kv.get_json(self._index_key(record["tenant_id"], record["user_id"])) or []
        if record["request_id"] not in index:
            index.insert(0, record["request_id"])
            await self.kv.set_json(self._index_key(record["tenant_id"], record["user_id"]), index[:100], ttl=86400 * 7)

    async def save_tool_call(self, record: dict) -> None:
        existing = await self.kv.get_json(self._key(record["trace_id"]))
        if existing is not None:
            existing.setdefault("tool_calls", []).append(record)
            await self.kv.set_json(self._key(record["trace_id"]), existing, ttl=86400 * 7)

    async def get_trace(self, request_id: str, tenant_id: str, user_id: str) -> dict | None:
        record = await self.kv.get_json(self._key(request_id))
        if record is None:
            return None
        if record.get("tenant_id") != tenant_id or record.get("user_id") != user_id:
            return None
        return record

    async def list_traces(self, tenant_id: str, user_id: str, limit: int = 20) -> list:
        index = await self.kv.get_json(self._index_key(tenant_id, user_id)) or []
        out = []
        for rid in index[:limit]:
            r = await self.kv.get_json(self._key(rid))
            if r:
                out.append({k: r.get(k) for k in ("request_id", "session_id", "status", "cached", "latency_ms", "created_ts")})
        return out


class SQLTraceStore:
    def __init__(self, db) -> None:
        from app.db.repo import TraceRepo

        self.repo = TraceRepo(db)

    async def save_trace(self, record: dict) -> None:
        await self.repo.save_trace(
            {
                "id": record["id"],
                "event_id": record["event_id"],
                "request_id": record["request_id"],
                "session_id": record.get("session_id"),
                "tenant_id": record["tenant_id"],
                "user_id": record["user_id"],
                "query_text": record["query_text"],
                "provider": record.get("provider"),
                "model": record.get("model"),
                "status": record["status"],
                "cached": record.get("cached", False),
                "latency_ms": record.get("latency_ms"),
                "error_code": record.get("error_code"),
            }
        )

    async def save_tool_call(self, record: dict) -> None:
        await self.repo.save_tool_call(
            {
                "event_id": record["event_id"],
                "trace_id": record["trace_id"],
                "tenant_id": record["tenant_id"],
                "tool_name": record["tool_name"],
                "arguments_json": record.get("arguments_json"),
                "result_json": record.get("result_json"),
                "status": record["status"],
                "latency_ms": record.get("latency_ms"),
            }
        )

    async def get_trace(self, request_id: str, tenant_id: str, user_id: str) -> dict | None:
        return await self.repo.get_trace(request_id, tenant_id, user_id)

    async def list_traces(self, tenant_id: str, user_id: str, limit: int = 20) -> list:
        return await self.repo.list_traces(tenant_id, user_id, limit)