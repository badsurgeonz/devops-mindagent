# DevOps-MindAgent

基于 **RAG（混合检索 + 语义缓存）** 与 **Multi-Tool Agent（ReAct + Function Calling）** 的智能技术文档问答 / 日志故障诊断平台。

技术栈：`FastAPI + ReAct Agent + 混合检索(BM25+向量+Rerank) + JWT 鉴权 + SQLAlchemy 持久化 + Redis(可选) + Kafka 异步审计(可选) + SSE 流式`

---

## 一、快速启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 可选：配置真实大模型与外部组件（不配置则本地 Mock + SQLite 即可体验全流程）
Copy-Item .env.example .env

uvicorn app.main:app --reload --port 8000
```

浏览器打开 `http://127.0.0.1:8000`，使用默认账号 `demo / demo1234` 登录后即可对话。

### 演示路径

| 快捷问题               | 触发行为                                       |
| ------------------ | ------------------------------------------ |
| Redis 内存告警 / 连接池报错 | `query_redis_status` + `search_error_logs` |
| order-service 500  | `search_error_logs`（含敏感信息脱敏验证）             |
| 什么是缓存穿透            | `get_kb_doc`（RAG 检索租户知识库）                  |

## 二、Mock / 真实模型与组件切换

| 组件       | 本地默认                       | 生产配置                                                                                    |
| -------- | -------------------------- | --------------------------------------------------------------------------------------- |
| LLM      | Mock（本地规则模拟 ReAct）         | `LLM_API_KEY` + `LLM_BASE_URL`/`LLM_MODEL`，未配置则启动报错（不允许静默降级）                            |
| 存储       | SQLite（`data/dev.db`，自动建表） | `DATABASE_URL=mysql+pymysql://...`，可选 `docker compose up -d mysql`                      |
| KV/缓存/限流 | 进程内内存                      | `REDIS_URL`                                                                             |
| 向量检索     | 哈希特征向量（进程内）                | `VECTOR_STORE=chroma` + `CHROMA_HOST/PORT` + BGE 模型（`EMBEDDING_MODEL`/`RERANKER_MODEL`） |
| 工具数据源    | Mock 适配器                   | `LOG_PLATFORM_URL` / `REDIS_DIAG_URL`（只读 HTTP 诊断服务）                                     |
| 审计       | 本地 JSONL                   | `KAFKA_BOOTSTRAP_SERVERS` + 消费端 `python -m app.audit.consumer`                          |

## 三、系统架构

```
[ 前端 static/index.html · JWT 登录 · SSE 打字机流式渲染 ]
        │ POST /api/chat  Authorization: Bearer <token>
        ▼
[ FastAPI API 网关 ]
  · JWT 鉴权 / 租户解析 / 权限校验 (/api/auth/login 签发 Token)
  · Redis+Lua / 内存 令牌桶限流（tenant+user 维度）
  · request_id 贯穿全链路
        │
        ├──► [ Agent 工作流引擎 (ReAct) ]
        │       ├──► [ RAG 混合检索: BM25 + ChromaDB/本地向量 + BGE-Reranker, 租户过滤 ]
        │       └──► [ Function Calling 工具链（适配器注入身份/权限） ]
        │             ├ search_error_logs(service, time_range_minutes, keyword, limit)
        │             ├ query_redis_status(cluster_id, key)
        │             └ get_kb_doc(query)
        │
        ├──► [ 存储层: MySQL(会话/消息/Trace) + Redis(语义缓存/会话缓存/限流) ]
        │
        └──► [ 审计: Kafka Producer(不可用降级 JSONL) → Consumer → MySQL 幂等落库 ]
```

## 四、目录结构

```
DevOps-MindAgent/
├── app/
│   ├── main.py              # 路由：auth/chat(SSE)/history/traces/kb + 限流 + 鉴权
│   ├── config.py            # 六组配置：Auth/Database/Vector/Kafka/Tool/Security
│   ├── bootstrap.py         # 启动装配与关闭（DB/Retriever/Producer/适配器）
│   ├── kvstore.py           # 内存 / Redis 双后端 KV
│   ├── chatstore.py         # 会话读写（KV / SQL 双实现，租户归属校验）
│   ├── traces.py            # Agent Trace 读写（KV / SQL 双实现）
│   ├── semantic_cache.py    # 语义缓存（按 tenant+user 隔离）
│   ├── rate_limit.py        # 令牌桶限流（Redis Lua / 内存）
│   ├── redact.py            # 敏感信息脱敏（Token/密钥/手机号/邮箱）
│   ├── auth/                # models(Principal) / security(JWT) / deps(依赖) / users
│   ├── db/                  # SQLAlchemy models + repos（含幂等 upsert）
│   ├── audit/               # events / producer(Kafka+JSONL) / consumer
│   ├── llm/provider.py      # OpenAI 兼容流式(含 tool_calls) + Mock 双模式
│   ├── rag/
│   │   ├── loader.py        # Markdown 分块（含租户/版本/分块元数据）
│   │   ├── retriever.py     # BM25+向量+Rerank，tenant 过滤
│   │   ├── vectorstore.py   # Local/Chroma + Hash/BGE Embedder + Reranker
│   │   ├── ingest.py        # 文档解析(MD/PDF)与重建索引
│   │   └── kb/faq.md        # 《故障排查手册》知识库
│   └── agent/
│       ├── adapters.py      # Log/Redis 诊断适配器（Mock/Http + 结构化错误）
│       ├── tools.py         # 工具 Schema/权限/参数边界/脱敏/超时
│       └── loop.py          # ReAct 循环 + Trace/审计埋点
├── static/index.html        # 前端（登录 + SSE 流式渲染）
├── migrations/              # Alembic 迁移脚手架
├── tests/                   # pytest（鉴权/租户/工具权限/缓存/限流/脱敏/持久化）
├── docker-compose.yml       # MySQL/Redis/Kafka/Kafka-UI/Chroma
├── requirements.txt         # 核心依赖
├── requirements-optional.txt# 可选：chromadb/BGE/aiokafka/pymysql/pypdf
└── requirements-dev.txt     # pytest/alembic
```

## 五、API

| 方法     | 路径                               | 权限               | 说明                                            |
| ------ | -------------------------------- | ---------------- | --------------------------------------------- |
| GET    | `/api/health`                    | 公开               | 健康检查（不返回敏感配置）                                 |
| POST   | `/api/auth/login`                | 公开               | 登录，签发 JWT                                     |
| POST   | `/api/chat`                      | `chat:use`       | SSE 流式对话（`thought/tool_result/token/done` 事件） |
| GET    | `/api/history/{session_id}`      | `history:read`   | 会话历史（租户归属校验，越权 404）                           |
| DELETE | `/api/history/{session_id}`      | `history:delete` | 清空会话                                          |
| GET    | `/api/traces`                    | `trace:read`     | 我的 Trace 列表                                   |
| GET    | `/api/traces/{request_id}`       | `trace:read`     | Trace 详情（含工具调用），越权 404                        |
| GET    | `/api/kb/documents`              | `kb:manage`      | 知识库文档列表                                       |
| POST   | `/api/kb/documents`              | `kb:manage`      | 上传文档（md/pdf/txt）并重建索引                         |
| POST   | `/api/kb/documents/{name}/index` | `kb:manage`      | 重建索引                                          |
| DELETE | `/api/kb/documents/{name}`       | `kb:manage`      | 删除文档                                          |

curl 示例：

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -N http://127.0.0.1:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"Redis 连接池报错怎么办","session_id":"demo"}'
```

## 六、测试

```powershell
pip install -r requirements-dev.txt
pytest tests -v
```

覆盖：登录/伪造 Token/401-403、跨租户 404、工具权限拒绝/放行、SSE 事件流、语义缓存命中、限流 429、日志脱敏、Trace 持久化、KB 上传删除。

## 七、生产环境 Checklist

- `APP_ENV=staging|production`，`MOCK_MODE` 不设，配置 `LLM_API_KEY` + `JWT_SECRET`
- `DATABASE_URL` 指向 MySQL 8，执行 `alembic upgrade head`（或开启 `DB_AUTO_CREATE`）
- `REDIS_URL` 开启分布式限流/缓存；`VECTOR_STORE=chroma` 接入 ChromaDB + BGE 模型
- `KAFKA_BOOTSTRAP_SERVERS` 开启异步审计，部署 `app.audit.consumer`
- 日志平台 / Redis 诊断服务接入 `LOG_PLATFORM_URL` / `REDIS_DIAG_URL`（只读）
- 安全边界：`MAX_INPUT_LEN` / `MAX_TOOL_OUTPUT` / `MAX_LOG_RANGE_MINUTES` / `MAX_LOG_LIMIT`