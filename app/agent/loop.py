import time
import uuid

from app.audit import events as audit_events
from app.config import cfg

SYSTEM_PROMPT = (
    "你是 DevOps-MindAgent，一名资深的运维排查与研发辅助助手。"
    "请使用中文回答。面对故障排查问题时，务必优先调用可用工具获取实时状态或检索知识库文档，"
    "再基于工具返回结果与《故障排查手册》给出结论与可执行的修复建议，并注明文档来源。"
    "不要臆造日志、指标或命令输出。工具返回结构化错误时，请向用户说明失败原因并给出重试或降级建议。"
)


class Agent:
    def __init__(self, provider, registry, chatstore, cache, traces, audit_producer) -> None:
        self.provider = provider
        self.registry = registry
        self.chatstore = chatstore
        self.cache = cache
        self.traces = traces
        self.audit = audit_producer

    async def run(self, query: str, session_id: str, principal, request_id: str):
        started = time.perf_counter()
        tenant_id = principal.tenant_id
        user_id = int(principal.user_id) if principal.user_id.isdigit() else 0
        cache_ns = f"{tenant_id}:{principal.user_id}"

        history = await self.chatstore.get_messages(session_id, tenant_id, user_id)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + (history or []) + [
            {"role": "user", "content": query}
        ]
        await self.chatstore.append(session_id, tenant_id, user_id, "user", query)

        trace = {
            "id": uuid.uuid4().hex,
            "event_id": audit_events.new_event_id(),
            "request_id": request_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "query_text": query,
            "provider": getattr(self.provider, "name", "?"),
            "model": cfg.llm_model if not cfg.mock_mode else "mock",
            "status": "running",
            "cached": False,
            "error_code": None,
        }
        tool_calls = []

        if self.cache:
            cached = await self.cache.lookup(query, cache_ns)
            if cached:
                answer = cached
                yield {"type": "info", "content": "命中语义缓存（相似度 >= 95%），直接返回缓存结果。"}
                async for piece in self._chunks(answer):
                    yield {"type": "token", "content": piece}
                await self.chatstore.append(session_id, tenant_id, user_id, "assistant", answer)
                trace.update(status="ok", cached=True, latency_ms=self._latency(started))
                yield await self._finish(trace, query, session_id, principal, answer, [], started, cached=True)
                return

        answer_parts = []
        used_tools = []
        for _ in range(cfg.max_agent_steps):
            tool_calls = None
            async for ev in self.provider.stream_turn(messages, self.registry.schemas):
                if ev.get("content"):
                    piece = ev["content"]
                    answer_parts.append(piece)
                    yield {"type": "token", "content": piece}
                if ev.get("tool_calls"):
                    tool_calls = ev["tool_calls"]
                    break

            if not tool_calls:
                break

            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("arguments") or "{}"
                yield {"type": "thought", "content": f"正在调用工具 {name}，参数: {args}"}
                result_text, meta = await self.registry.run(name, args, principal)
                used_tools.append({"name": name, "meta": meta})
                yield {"type": "tool_result", "name": name, "content": result_text}
                if meta.get("status") != "denied":
                    await self.traces.save_tool_call(
                        {
                            "event_id": audit_events.new_event_id(),
                            "trace_id": trace["id"],
                            "request_id": request_id,
                            "tenant_id": tenant_id,
                            "user_id": trace["user_id"],
                            "tool_name": name,
                            "arguments": meta.get("arguments"),
                            "result": meta.get("result"),
                            "status": meta.get("status", "error"),
                            "latency_ms": meta.get("latency_ms"),
                        }
                    )
                    await self.audit.publish(
                        audit_events.tool_call(
                            {
                                "trace_id": trace["id"],
                                "request_id": request_id,
                                "tenant_id": tenant_id,
                                "user_id": trace["user_id"],
                                "tool_name": name,
                                "arguments": meta.get("arguments"),
                                "result": meta.get("result"),
                                "status": meta.get("status", "error"),
                                "latency_ms": meta.get("latency_ms"),
                            }
                        )
                    )
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_text})

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = "未获取到可用的回答，请换一种问法，或检查 LLM 配置后重试。"
            async for piece in self._chunks(answer):
                yield {"type": "token", "content": piece}

        await self.chatstore.append(session_id, tenant_id, user_id, "assistant", answer)
        if self.cache and not used_tools:
            await self.cache.put(query, answer, cache_ns)
        yield await self._finish(trace, query, session_id, principal, answer, used_tools, started)

    @staticmethod
    async def _chunks(text: str):
        for i in range(0, len(text), 12):
            yield text[i : i + 12]

    @staticmethod
    def _latency(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    async def _finish(self, trace, query, session_id, principal, answer, used_tools, started, cached=False) -> dict:
        latency = self._latency(started)
        trace.update(status="ok", latency_ms=latency, cached=cached)
        trace["tool_count"] = len(used_tools)
        await self.traces.save_trace(trace)
        await self.audit.publish(audit_events.trace_completed(trace))
        return {
            "type": "done",
            "content": answer,
            "session_id": session_id,
            "request_id": trace["request_id"],
            "tools": [t["name"] for t in used_tools],
            "cached": cached,
            "latency_ms": latency,
            "mode": getattr(self.provider, "name", "?"),
        }