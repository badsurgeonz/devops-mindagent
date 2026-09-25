import asyncio
import json
import time

from app.agent.adapters import StructuredToolError
from app.config import cfg
from app.redact import redact


class Tool:
    def __init__(self, name: str, description: str, parameters: dict,
                 required_permission: str | None, func) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.required_permission = required_permission
        self.func = func

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, retriever, log_adapter, redis_adapter) -> None:
        self.retriever = retriever
        self.log_adapter = log_adapter
        self.redis_adapter = redis_adapter
        self._tools = {
            t.name: t
            for t in [
                Tool(
                    "search_error_logs",
                    "根据服务名与时间范围抓取该服务的异常日志与 StackTrace，用于线上故障定位。",
                    {
                        "type": "object",
                        "properties": {
                            "service_name": {"type": "string", "description": "服务名，例如 order-service"},
                            "time_range_minutes": {"type": "integer", "description": "查询最近 N 分钟（最大 1440）"},
                            "keyword": {"type": "string", "description": "关键字过滤，例如 JedisConnectionException"},
                            "limit": {"type": "integer", "description": "返回条数上限（最大 200）"},
                        },
                        "required": ["service_name"],
                    },
                    "tool:logs:read",
                    self._search_error_logs,
                ),
                Tool(
                    "query_redis_status",
                    "查询 Redis 集群的内存占用、连接数、大 Key、键存活等只读状态，用于缓存类故障排查。",
                    {
                        "type": "object",
                        "properties": {
                            "cluster_id": {"type": "string", "description": "Redis 集群标识，默认 default"},
                            "key": {"type": "string", "description": "要检查的 Redis Key"},
                        },
                        "required": [],
                    },
                    "tool:redis:read",
                    self._query_redis_status,
                ),
                Tool(
                    "get_kb_doc",
                    "主动检索租户知识库《故障排查手册》，返回与问题最相关的技术文档片段（含来源与版本）。",
                    {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "检索问题描述"}},
                        "required": ["query"],
                    },
                    "chat:use",
                    self._get_kb_doc,
                ),
            ]
        }

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def schemas(self) -> list:
        return [t.schema for t in self._tools.values()]

    @property
    def names(self) -> list:
        return list(self._tools)

    async def _search_error_logs(self, args: dict, principal) -> tuple[str, dict]:
        service_name = str(args.get("service_name") or "unknown-service")
        minutes = min(max(1, int(args.get("time_range_minutes") or 30)), cfg.security.max_log_range_minutes)
        limit = min(max(1, int(args.get("limit") or 100)), cfg.security.max_log_limit)
        keyword = str(args.get("keyword") or "") or None
        data = await self.log_adapter.search(service_name, minutes, keyword, limit, principal.tenant_id)
        lines = [f"[{e['ts']}] [{e['level']}] {e['message']}" for e in data.get("entries", [])]
        text = (
            f"服务 {service_name} 最近 {minutes} 分钟异常日志（共 {data.get('total', len(lines))} 条，"
            f"request_id={data.get('request_id', '-')}）：\n" + "\n".join(lines)
        )
        result = {
            "service_name": service_name,
            "request_id": data.get("request_id"),
            "total": data.get("total"),
            "entries": data.get("entries", []),
        }
        return redact(text), redact(json.dumps(result, ensure_ascii=False))

    async def _query_redis_status(self, args: dict, principal) -> tuple[str, dict]:
        cluster_id = str(args.get("cluster_id") or "default")
        key = str(args.get("key") or "")
        data = await self.redis_adapter.status(cluster_id, key or None, principal.tenant_id)
        text = (
            f"Redis 集群 {data.get('cluster_id')} 状态：\n"
            f"- used_memory={data.get('used_memory_human')}, peak={data.get('used_memory_peak_human')}, "
            f"maxmemory={data.get('maxmemory_human')}\n"
            f"- connected_clients={data.get('connected_clients')}, blocked_clients={data.get('blocked_clients')}, "
            f"hit_rate={data.get('hit_rate')}\n"
            f"- 大 Key 告警: {data.get('big_key_alert')}\n"
            f"- key_info: {data.get('key_info')}"
        )
        return redact(text), redact(json.dumps(data, ensure_ascii=False))

    async def _get_kb_doc(self, args: dict, principal) -> tuple[str, dict]:
        query = str(args.get("query") or "")
        results = await self.retriever.retrieve(query, top_k=cfg.rag_top_k,
                                                tenant_id=principal.tenant_id,
                                                permissions=principal.permissions)
        if not results:
            return "未检索到相关文档。", json.dumps({"query": query, "total": 0}, ensure_ascii=False)
        lines = []
        for i, r in enumerate(results, 1):
            text = r["text"].strip().replace("\n", "\n  ")
            lines.append(
                f"[{i}] 来源={r['source']} | 章节={r['heading']} | 版本={r['doc_version']} | 相关度={r['score']}\n  {text}"
            )
        return "\n\n".join(lines), json.dumps({"query": query, "total": len(results)}, ensure_ascii=False)

    async def run(self, name: str, arguments: str, principal) -> tuple[str, dict]:
        tool = self.get(name)
        if tool is None:
            return StructuredToolError("TOOL_NOT_FOUND", f"工具 {name} 不存在").to_text(), {
                "status": "error", "error_code": "TOOL_NOT_FOUND"
            }
        if tool.required_permission and not principal.has_perm(tool.required_permission):
            return StructuredToolError("PERMISSION_DENIED", f"缺少权限 {tool.required_permission}").to_text(), {
                "status": "denied", "error_code": "PERMISSION_DENIED"
            }
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        started = time.perf_counter()
        try:
            text, result = await asyncio.wait_for(tool.func(args, principal), timeout=cfg.tool.timeout)
            meta = {
                "status": "ok",
                "tool": name,
                "arguments": args,
                "result": result,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
            return text, meta
        except StructuredToolError as exc:
            return exc.to_text(), {
                "status": "error",
                "tool": name,
                "arguments": args,
                "error_code": exc.error_code,
                "retryable": exc.retryable,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except asyncio.TimeoutError:
            return StructuredToolError("TOOL_TIMEOUT", "工具执行超时，请稍后重试", retryable=True).to_text(), {
                "status": "error", "tool": name, "arguments": args,
                "error_code": "TOOL_TIMEOUT",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001
            return StructuredToolError("TOOL_INTERNAL_ERROR", "工具内部错误").to_text(), {
                "status": "error", "tool": name, "arguments": args,
                "error_code": "TOOL_INTERNAL_ERROR",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }