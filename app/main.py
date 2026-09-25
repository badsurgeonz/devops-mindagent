import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import get_current_principal, require_permissions
from app.auth.models import Principal
from app.auth.security import create_access_token
from app.config import BASE_DIR, cfg
from app.bootstrap import build_context, close_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ctx = await build_context()
    yield
    await close_context(app.state.ctx)


app = FastAPI(title="DevOps-MindAgent", version="0.2.0", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(default="default", max_length=64)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/api/health")
async def health():
    ctx = app.state.ctx
    return {
        "status": "ok",
        "env": cfg.app_env,
        "mode": ctx.provider.name,
        "model": cfg.llm_model if not cfg.mock_mode else None,
        "kv": ctx.kv.kind,
        "db": "sqlalchemy" if ctx.db else "none",
        "vector": cfg.vector.store,
        "docs": ctx.retriever.size,
        "tools": ctx.registry.names,
        "semantic_cache": ctx.cache is not None,
    }


@app.post("/api/auth/login")
async def login(body: LoginRequest):
    ctx = app.state.ctx
    user = await ctx.users.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user, user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": cfg.auth.access_expire_seconds,
        "tenant_id": user["tenant_id"],
        "roles": user["roles"],
    }


@app.post("/api/chat")
async def chat(req: ChatRequest, principal: Principal = Depends(get_current_principal)):
    if len(req.message) > cfg.security.max_input_len:
        raise HTTPException(status_code=413, detail=f"输入长度超过上限 {cfg.security.max_input_len}")
    ctx = app.state.ctx
    if not await ctx.limiter.allow(f"chat:{principal.tenant_id}:{principal.user_id}"):
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})

    request_id = uuid.uuid4().hex
    started = time.perf_counter()

    async def event_stream():
        try:
            async for event in ctx.agent.run(req.message, req.session_id, principal, request_id):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat 处理异常")
            yield _sse({"type": "error", "content": "服务内部错误，请稍后重试"})
        yield _sse({"type": "latency_ms", "content": int((time.perf_counter() - started) * 1000)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/history/{session_id}")
async def history(session_id: str, principal: Principal = Depends(require_permissions("history:read"))):
    ctx = app.state.ctx
    messages = await ctx.chatstore.get_messages(session_id, principal.tenant_id, principal.user_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/history/{session_id}")
async def clear_history(session_id: str, principal: Principal = Depends(require_permissions("history:delete"))):
    ctx = app.state.ctx
    if not await ctx.chatstore.clear(session_id, principal.tenant_id, principal.user_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.get("/api/traces/{request_id}")
async def get_trace(request_id: str, principal: Principal = Depends(require_permissions("trace:read"))):
    ctx = app.state.ctx
    trace = await ctx.traces.get_trace(request_id, principal.tenant_id, principal.user_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace 不存在")
    return trace


@app.get("/api/traces")
async def list_traces(principal: Principal = Depends(require_permissions("trace:read"))):
    ctx = app.state.ctx
    return {"traces": await ctx.traces.list_traces(principal.tenant_id, principal.user_id, limit=20)}


@app.get("/api/kb/documents")
async def list_documents(principal: Principal = Depends(require_permissions("kb:manage"))):
    files = []
    for path in sorted(cfg.kb_dir.glob("*")):
        if path.suffix.lower() in {".md", ".pdf", ".txt"}:
            files.append({"name": path.name, "size": path.stat().st_size})
    return {"documents": files}


@app.post("/api/kb/documents")
async def upload_document(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_permissions("kb:manage")),
):
    if file.filename is None or Path(file.filename).suffix.lower() not in {".md", ".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="仅支持 .md/.pdf/.txt")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 10MB 上限")
    name = f"{uuid.uuid4().hex[:8]}-{Path(file.filename).name}"
    target = cfg.kb_dir / name
    target.write_bytes(content)

    from app.rag.ingest import rebuild_retriever

    ctx = app.state.ctx
    n = await rebuild_retriever(ctx.retriever, principal.tenant_id)
    return {"name": name, "chunks": n}


@app.post("/api/kb/documents/{name}/index")
async def reindex_document(name: str, principal: Principal = Depends(require_permissions("kb:manage"))):
    ctx = app.state.ctx
    from app.rag.ingest import rebuild_retriever

    n = await rebuild_retriever(ctx.retriever, principal.tenant_id)
    return {"name": name, "chunks": n}


@app.delete("/api/kb/documents/{name}")
async def delete_document(name: str, principal: Principal = Depends(require_permissions("kb:manage"))):
    path = (cfg.kb_dir / name).resolve()
    if path.parent != cfg.kb_dir.resolve() or path.suffix.lower() not in {".md", ".pdf", ".txt"}:
        raise HTTPException(status_code=400, detail="非法文件名")
    if not path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    path.unlink()
    ctx = app.state.ctx
    from app.rag.ingest import rebuild_retriever

    n = await rebuild_retriever(ctx.retriever, principal.tenant_id)
    return {"ok": True, "chunks": n}


@app.get("/")
async def index():
    return FileResponse(Path(BASE_DIR) / "static" / "index.html")