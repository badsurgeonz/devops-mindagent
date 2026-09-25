from datetime import datetime

from sqlalchemy import select, func

from app.db.models import AgentTrace, Message, Session, ToolCall, User


def _upsert(session, model, unique_col, row: dict):
    existing = session.execute(select(model).where(unique_col == row[unique_col.key])).scalar_one_or_none()
    if existing is not None:
        for k, v in row.items():
            setattr(existing, k, v)
    else:
        session.add(model(**row))


class UserRepo:
    def __init__(self, db) -> None:
        self.db = db

    def _authenticate(self, username: str, password: str):
        from app.auth.security import verify_password

        with self.db.session() as s:
            u = s.execute(
                select(User).where(User.username == username, User.status == 1)
            ).scalar_one_or_none()
            if u is None or not u.password_hash:
                return None
            salt, digest = (u.password_hash or "").split(":", 1)
            if not verify_password(password, salt, digest):
                return None
            return {
                "id": str(u.id),
                "tenant_id": u.tenant_id,
                "username": u.username,
                "roles": u.roles or [],
                "permissions": u.permissions or [],
            }

    async def authenticate(self, username: str, password: str) -> dict | None:
        return await self.db.run(self._authenticate, username, password)

    def _seed_if_empty(self, users: list):
        from app.auth.security import hash_password

        with self.db.session() as s:
            count = s.execute(select(func.count()).select_from(User)).scalar_one()
            if count:
                return
            for u in users:
                salt, digest = hash_password(u["password"])
                s.add(
                    User(
                        tenant_id=u["tenant_id"],
                        username=u["username"],
                        password_hash=f"{salt}:{digest}",
                        roles=u.get("roles", []),
                        permissions=u.get("permissions", []),
                        status=1,
                    )
                )
            s.commit()

    async def seed_if_empty(self, users: list):
        await self.db.run(self._seed_if_empty, users)

    def _list(self):
        with self.db.session() as s:
            return [{"id": str(u.id), "tenant_id": u.tenant_id, "username": u.username} for u in s.execute(select(User)).scalars()]

    async def list_users(self) -> list:
        return await self.db.run(self._list)


class ChatRepo:
    def __init__(self, db) -> None:
        self.db = db

    def _ensure_session(self, session_id, tenant_id, user_id, title=None):
        with self.db.session() as s:
            row = s.get(Session, session_id)
            if row is None:
                s.add(Session(id=session_id, tenant_id=tenant_id, user_id=user_id, title=title or "新对话"))
                s.commit()
            elif row.tenant_id != tenant_id or row.user_id != user_id:
                raise PermissionError("session not owned")

    async def ensure_session(self, session_id, tenant_id, user_id, title=None):
        await self.db.run(self._ensure_session, session_id, tenant_id, user_id, title)

    def _get_messages(self, session_id, tenant_id, user_id):
        with self.db.session() as s:
            row = s.execute(
                select(Session).where(Session.id == session_id, Session.tenant_id == tenant_id, Session.user_id == user_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            msgs = s.execute(
                select(Message)
                .where(Message.session_id == session_id, Message.tenant_id == tenant_id)
                .order_by(Message.sequence_no)
                .limit(20)
            ).scalars()
            return [{"role": m.role, "content": m.content} for m in msgs]

    async def get_messages(self, session_id, tenant_id, user_id):
        return await self.db.run(self._get_messages, session_id, tenant_id, user_id)

    def _append(self, session_id, tenant_id, user_id, role, content):
        with self.db.session() as s:
            self._ensure_session(session_id, tenant_id, user_id)
            seq = s.execute(
                select(func.coalesce(func.max(Message.sequence_no), -1) + 1).where(Message.session_id == session_id)
            ).scalar_one()
            s.add(Message(session_id=session_id, tenant_id=tenant_id, role=role, content=content, sequence_no=seq))
            s.commit()

    async def append(self, session_id, tenant_id, user_id, role, content):
        await self.db.run(self._append, session_id, tenant_id, user_id, role, content)

    def _clear(self, session_id, tenant_id, user_id):
        with self.db.session() as s:
            row = s.execute(
                select(Session).where(Session.id == session_id, Session.tenant_id == tenant_id, Session.user_id == user_id)
            ).scalar_one_or_none()
            if row is None:
                return False
            s.execute(Message.__table__.delete().where(Message.session_id == session_id))
            s.delete(row)
            s.commit()
            return True

    async def clear(self, session_id, tenant_id, user_id):
        return await self.db.run(self._clear, session_id, tenant_id, user_id)


class TraceRepo:
    def __init__(self, db) -> None:
        self.db = db

    def _save_trace(self, trace: dict):
        with self.db.session() as s:
            _upsert(s, AgentTrace, AgentTrace.event_id, trace)
            s.commit()

    async def save_trace(self, trace: dict):
        await self.db.run(self._save_trace, trace)

    def _save_tool_call(self, row: dict):
        with self.db.session() as s:
            _upsert(s, ToolCall, ToolCall.event_id, row)
            s.commit()

    async def save_tool_call(self, row: dict):
        await self.db.run(self._save_tool_call, row)

    def _get_trace(self, request_id, tenant_id, user_id):
        with self.db.session() as s:
            tr = s.execute(
                select(AgentTrace).where(
                    AgentTrace.request_id == request_id,
                    AgentTrace.tenant_id == tenant_id,
                    AgentTrace.user_id == user_id,
                )
            ).scalar_one_or_none()
            if tr is None:
                return None
            calls = s.execute(
                select(ToolCall).where(ToolCall.trace_id == tr.id).order_by(ToolCall.id)
            ).scalars()
            return {
                "request_id": tr.request_id,
                "session_id": tr.session_id,
                "status": tr.status,
                "cached": tr.cached,
                "latency_ms": tr.latency_ms,
                "provider": tr.provider,
                "model": tr.model,
                "created_at": tr.created_at.isoformat() if tr.created_at else None,
                "query_text": tr.query_text,
                "tool_calls": [
                    {
                        "tool_name": c.tool_name,
                        "arguments": c.arguments_json,
                        "result": c.result_json,
                        "status": c.status,
                        "latency_ms": c.latency_ms,
                    }
                    for c in calls
                ],
            }

    async def get_trace(self, request_id, tenant_id, user_id):
        return await self.db.run(self._get_trace, request_id, tenant_id, user_id)

    def _list_traces(self, tenant_id, user_id, limit=20):
        with self.db.session() as s:
            rows = s.execute(
                select(AgentTrace)
                .where(AgentTrace.tenant_id == tenant_id, AgentTrace.user_id == user_id)
                .order_by(AgentTrace.created_at.desc())
                .limit(limit)
            ).scalars()
            return [
                {
                    "request_id": t.request_id,
                    "session_id": t.session_id,
                    "status": t.status,
                    "cached": t.cached,
                    "latency_ms": t.latency_ms,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in rows
            ]

    async def list_traces(self, tenant_id, user_id, limit=20):
        return await self.db.run(self._list_traces, tenant_id, user_id, limit)