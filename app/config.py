import json
from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _flag(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _int(v: str, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v: str, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class AuthSettings:
    secret: str = ""
    issuer: str = "devops-mindagent"
    algorithm: str = "HS256"
    access_expire_seconds: int = 3600
    seed_users: list = field(default_factory=list)


@dataclass
class DatabaseSettings:
    url: str = ""
    enabled: bool = False
    auto_create: bool = True
    pool_size: int = 5
    pool_timeout: int = 10


@dataclass
class VectorSettings:
    store: str = "local"
    host: str = "localhost"
    port: int = 8000
    collection: str = "mindagent_kb"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    enabled: bool = False


@dataclass
class KafkaSettings:
    bootstrap_servers: str = ""
    trace_topic: str = "mindagent.agent.trace.v1"
    tool_topic: str = "mindagent.tool.call.v1"
    security_topic: str = "mindagent.security.audit.v1"
    group_id: str = "mindagent-audit-consumer"
    enabled: bool = False


@dataclass
class ToolSettings:
    log_platform_url: str = ""
    redis_diag_url: str = ""
    timeout: float = 5.0
    mock: bool = True


@dataclass
class SecuritySettings:
    max_input_len: int = 4096
    max_tool_output: int = 4000
    max_log_range_minutes: int = 1440
    max_log_limit: int = 200


class Config:
    def __init__(self) -> None:
        self.app_env = os.getenv("APP_ENV", "local").strip().lower()

        self.llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").strip().rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat").strip()
        self.llm_temperature = _float(os.getenv("LLM_TEMPERATURE"), 0.4)

        forced_mock = _flag(os.getenv("MOCK_MODE", "")) or self.llm_provider == "mock"
        local_no_key = self.app_env == "local" and not self.llm_provider and not self.llm_api_key
        self.mock_mode = forced_mock or local_no_key
        if not self.mock_mode and not self.llm_api_key:
            raise RuntimeError(
                "非本地环境缺少 LLM_API_KEY，且未显式设置 MOCK_MODE=true。"
                "Mock 必须显式开启，不允许因外部依赖异常静默降级。"
            )

        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.redis_rate_script = _flag(os.getenv("REDIS_RATE_SCRIPT", "true"))

        self.rag_top_k = _int(os.getenv("RAG_TOP_K"), 3)
        self.rag_bm25_weight = _float(os.getenv("RAG_BM25_WEIGHT"), 0.35)
        self.rag_vector_weight = _float(os.getenv("RAG_VECTOR_WEIGHT"), 0.65)

        self.semantic_enabled = _flag(os.getenv("SEMANTIC_CACHE", "true"))
        self.semantic_threshold = _float(os.getenv("SEMANTIC_THRESHOLD"), 0.95)
        self.semantic_ttl = _int(os.getenv("SEMANTIC_TTL"), 600)

        self.session_ttl = _int(os.getenv("SESSION_TTL"), 86400)
        self.rate_rate = _float(os.getenv("RATE_RATE"), 2.0)
        self.rate_cap = _float(os.getenv("RATE_CAP"), 10)

        self.max_agent_steps = _int(os.getenv("MAX_AGENT_STEPS"), 6)

        self.audit_dir = Path(os.getenv("AUDIT_DIR", str(BASE_DIR / "logs" / "audit")))
        self.kb_dir = BASE_DIR / "app" / "rag" / "kb"
        self.static_dir = BASE_DIR / "static"
        self.data_dir = BASE_DIR / "data"

        self.index_key = "semantic:index"
        self.session_prefix = "session:"
        self.rate_prefix = "rate:"

        self.auth = AuthSettings(
            secret=os.getenv("JWT_SECRET", "").strip(),
            issuer=os.getenv("JWT_ISSUER", "devops-mindagent"),
            access_expire_seconds=_int(os.getenv("JWT_EXPIRE_SECONDS"), 3600),
            seed_users=json.loads(os.getenv("SEED_USERS", "[]") or "[]"),
        )
        if not self.auth.secret:
            if self.app_env == "local":
                self.auth.secret = "local-dev-secret-do-not-use"
            else:
                raise RuntimeError("非 local 环境必须配置 JWT_SECRET")

        default_db_url = f"sqlite:///{self.data_dir / 'dev.db'}" if self.app_env == "local" else ""
        db_url = os.getenv("DATABASE_URL", default_db_url).strip()
        self.db = DatabaseSettings(
            url=db_url,
            enabled=bool(db_url),
            auto_create=_flag(os.getenv("DB_AUTO_CREATE", "true")),
            pool_size=_int(os.getenv("DB_POOL_SIZE"), 5),
            pool_timeout=_int(os.getenv("DB_POOL_TIMEOUT"), 10),
        )

        vector_store = os.getenv("VECTOR_STORE", "local").strip().lower()
        self.vector = VectorSettings(
            store=vector_store,
            host=os.getenv("CHROMA_HOST", "localhost"),
            port=_int(os.getenv("CHROMA_PORT"), 8000),
            collection=os.getenv("CHROMA_COLLECTION", "mindagent_kb"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            enabled=vector_store in {"chroma", "chroma-http"},
        )

        kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        self.kafka = KafkaSettings(
            bootstrap_servers=kafka_servers,
            trace_topic=os.getenv("KAFKA_TRACE_TOPIC", "mindagent.agent.trace.v1"),
            tool_topic=os.getenv("KAFKA_TOOL_TOPIC", "mindagent.tool.call.v1"),
            security_topic=os.getenv("KAFKA_SECURITY_TOPIC", "mindagent.security.audit.v1"),
            group_id=os.getenv("KAFKA_GROUP_ID", "mindagent-audit-consumer"),
            enabled=bool(kafka_servers),
        )

        self.tool = ToolSettings(
            log_platform_url=os.getenv("LOG_PLATFORM_URL", "").strip(),
            redis_diag_url=os.getenv("REDIS_DIAG_URL", "").strip(),
            timeout=_float(os.getenv("TOOL_TIMEOUT"), 5.0),
            mock=not (os.getenv("LOG_PLATFORM_URL") or os.getenv("REDIS_DIAG_URL")),
        )

        self.security = SecuritySettings(
            max_input_len=_int(os.getenv("MAX_INPUT_LEN"), 4096),
            max_tool_output=_int(os.getenv("MAX_TOOL_OUTPUT"), 4000),
            max_log_range_minutes=_int(os.getenv("MAX_LOG_RANGE_MINUTES"), 1440),
            max_log_limit=_int(os.getenv("MAX_LOG_LIMIT"), 200),
        )


cfg = Config()