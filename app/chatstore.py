import json

from app.config import cfg


class KVChatStore:
    def __init__(self, kv) -> None:
        self.kv = kv

    def _key(self, session_id: str, tenant_id: str, user_id: str) -> str:
        return f"{cfg.session_prefix}{tenant_id}:{user_id}:{session_id}"

    async def get_messages(self, session_id: str, tenant_id: str, user_id: str) -> list | None:
        data = await self.kv.get_json(self._key(session_id, tenant_id, user_id))
        if data is None:
            return None
        return data["messages"][-20:]

    async def append(self, session_id: str, tenant_id: str, user_id: str, role: str, content: str) -> None:
        key = self._key(session_id, tenant_id, user_id)
        data = await self.kv.get_json(key) or {"title": "新对话", "messages": []}
        data["messages"].append({"role": role, "content": content})
        data["messages"] = data["messages"][-20:]
        await self.kv.set_json(key, data, ttl=cfg.session_ttl)

    async def clear(self, session_id: str, tenant_id: str, user_id: str) -> bool:
        key = self._key(session_id, tenant_id, user_id)
        exists = await self.kv.get(key) is not None
        await self.kv.delete(key)
        return exists


class SQLChatStore:
    def __init__(self, db) -> None:
        from app.db.repo import ChatRepo

        self.repo = ChatRepo(db)

    async def get_messages(self, session_id: str, tenant_id: str, user_id: str) -> list | None:
        return await self.repo.get_messages(session_id, tenant_id, user_id)

    async def append(self, session_id: str, tenant_id: str, user_id: str, role: str, content: str) -> None:
        await self.repo.append(session_id, tenant_id, user_id, role, content)

    async def clear(self, session_id: str, tenant_id: str, user_id: str) -> bool:
        return await self.repo.clear(session_id, tenant_id, user_id)