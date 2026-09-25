import asyncio
import logging

from app.agent.adapters import build_log_adapter, build_redis_adapter
from app.agent.loop import Agent
from app.agent.tools import ToolRegistry
from app.audit.producer import AuditProducer
from app.auth.users import UserStore
from app.chatstore import KVChatStore, SQLChatStore
from app.config import cfg
from app.db.base import build_db
from app.kvstore import create_kv
from app.llm.provider import create_provider
from app.rag.ingest import load_tenant_docs, rebuild_retriever
from app.rag.retriever import build_retriever
from app.rate_limit import TokenBucketLimiter
from app.semantic_cache import SemanticCache
from app.traces import KVTraceStore, SQLTraceStore

logger = logging.getLogger("bootstrap")


class AppContext:
    def __init__(self) -> None:
        self.provider = None
        self.registry = None
        self.chatstore = None
        self.cache = None
        self.traces = None
        self.audit = None
        self.limiter = None
        self.retriever = None
        self.kv = None
        self.agent = None
        self.db = None
        self.users = None
        self.log_adapter = None
        self.redis_adapter = None


async def build_context() -> AppContext:
    ctx = AppContext()

    kv = create_kv(cfg)
    if not await kv.ping():
        raise RuntimeError("KV 存储不可用")

    db = build_db(cfg.db.url) if cfg.db.enabled else None
    if db is not None and cfg.db.auto_create:
        await asyncio.to_thread(db.create_all)

    chunks = await asyncio.to_thread(load_tenant_docs)
    retriever = build_retriever(chunks, cfg.rag_bm25_weight, cfg.rag_vector_weight)

    log_adapter = build_log_adapter()
    redis_adapter = build_redis_adapter()

    ctx.kv = kv
    ctx.db = db
    ctx.retriever = retriever
    ctx.provider = create_provider()
    ctx.registry = ToolRegistry(retriever, log_adapter, redis_adapter)
    ctx.chatstore = SQLChatStore(db) if db is not None else KVChatStore(kv)
    ctx.cache = SemanticCache(kv, cfg.semantic_threshold, cfg.semantic_ttl) if cfg.semantic_enabled else None
    ctx.traces = SQLTraceStore(db) if db is not None else KVTraceStore(kv)
    ctx.limiter = TokenBucketLimiter(kv, cfg.rate_rate, cfg.rate_cap)
    ctx.users = UserStore(db)
    ctx.audit = AuditProducer()
    ctx.log_adapter = log_adapter
    ctx.redis_adapter = redis_adapter
    ctx.agent = Agent(ctx.provider, ctx.registry, ctx.chatstore, ctx.cache, ctx.traces, ctx.audit)

    await ctx.users.seed_defaults()
    await ctx.audit.start()

    logger.info(
        "就绪: env=%s llm=%s kv=%s db=%s vector=%s audit=%s 文档片段=%d 工具=%s",
        cfg.app_env,
        ctx.provider.name,
        kv.kind,
        "sqlalchemy" if db else "none",
        cfg.vector.store,
        "kafka" if ctx.audit.kafka else "jsonl",
        retriever.size,
        ctx.registry.names,
    )
    return ctx


async def close_context(ctx: AppContext) -> None:
    await ctx.audit.close()
    await ctx.provider.aclose()
    for adapter in (ctx.log_adapter, ctx.redis_adapter):
        if adapter is not None and hasattr(adapter, "aclose"):
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001
                pass
    if ctx.db is not None:
        ctx.db.engine.dispose()