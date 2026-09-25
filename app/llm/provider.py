import asyncio
import json
import logging

import httpx

from app.config import cfg

logger = logging.getLogger("llm")


class OpenAIProvider:
    name = "openai-compatible"

    def __init__(self) -> None:
        self.url = f"{cfg.llm_base_url}/chat/completions"
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {cfg.llm_api_key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, read=180.0),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def stream_turn(self, messages: list, tools: list | None = None):
        payload = {
            "model": cfg.llm_model,
            "messages": messages,
            "stream": True,
            "temperature": cfg.llm_temperature,
        }
        if tools:
            payload["tools"] = tools
        acc = {}

        async with self.client.stream("POST", self.url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    yield {"content": content}
                for tc in delta.get("tool_calls") or []:
                    slot = acc.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
                reason = choice.get("finish_reason")
                if reason == "tool_calls":
                    calls = [
                        {
                            "id": slot["id"] or f"call_{i}",
                            "name": slot["name"],
                            "arguments": slot["arguments"],
                        }
                        for i, slot in sorted(acc.items())
                    ]
                    yield {"tool_calls": calls}
                    return


_MOCK_TRIGGERS = [
    (("redis", "内存", "大key", "bigkey", "连接池", "雪崩", "击穿", "命中率", "连接数"), "query_redis_status"),
    (("日志", "报错", "错误", "堆栈", "stacktrace", "500", "异常", "排查", "log", "error"), "search_error_logs"),
    (("手册", "规范", "架构", "api", "文档", "怎么", "如何", "为什么", "原因", "解决", "故障", "指南", "穿透"), "get_kb_doc"),
]

_MOCK_QUICK = (
    "你好，我是 DevOps-MindAgent（当前为 Mock 模式）。"
    "可以问我：Redis 内存告警排查、订单服务 500 报错、什么是缓存穿透等；"
    "或配置 LLM_API_KEY 后切换到真实大模型。"
)


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self.mock_mode = True

    async def aclose(self) -> None:
        return None

    @staticmethod
    def _query(messages: list) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    def _plan(self, query: str) -> list:
        q = query.lower()
        calls = []
        seen = set()
        for keywords, tool in _MOCK_TRIGGERS:
            if tool in seen:
                continue
            if any(k in q for k in keywords):
                seen.add(tool)
                calls.append(self._make_call(tool, q))
        return calls

    @staticmethod
    def _make_call(name: str, q: str) -> dict:
        args: dict = {}
        if name == "search_error_logs":
            services = ("gateway", "order-service", "order", "payment", "user", "inventory", "stock")
            matched = [s for s in services if s in q]
            args["service_name"] = max(matched, key=len) if matched else "order-service"
            args["time_range_minutes"] = 30
            args["keyword"] = ""
            args["limit"] = 100
        elif name == "query_redis_status":
            args["cluster_id"] = "default"
            args["key"] = "cache:hot:stock:1001"
        elif name == "get_kb_doc":
            args["query"] = q
        return {"id": f"mock_call_{abs(hash(name))}", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}

    async def stream_turn(self, messages: list, tools: list | None = None):
        query = self._query(messages)
        executed = any(m.get("role") == "tool" for m in messages)

        if executed:
            answer = self._compose_final(messages)
            async for piece in self._emit_text(answer):
                yield {"content": piece}
            return

        plan = self._plan(query)
        if plan:
            names = "、".join(p["name"] for p in plan)
            async for piece in self._emit_text(f"（Mock 模式思考中）根据问题关键词，我准备调用工具：{names}。\n"):
                yield {"content": piece}
            yield {"tool_calls": plan}
            return

        async for piece in self._emit_text(_MOCK_QUICK):
            yield {"content": piece}

    @staticmethod
    def _emit_text(text: str):
        for i in range(0, len(text), 10):
            yield text[i : i + 10]

    def _compose_final(self, messages: list) -> str:
        names = {}
        results = []
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    names[tc["id"]] = tc["function"]["name"]
            if m.get("role") == "tool":
                results.append((names.get(m.get("tool_call_id"), "unknown"), m.get("content", "")))

        sections = []
        for name, content in results:
            sections.append(f"## {name} 执行结果\n{content}")
        body = "\n\n".join(sections)
        return "排查结论与建议：\n\n" + body + "\n\n以上为工具调用结果。如需完整分析，可切换真实大模型（配置 LLM_API_KEY）。"

    async def _emit_text(self, text: str):
        for i in range(0, len(text), 10):
            yield text[i : i + 10]
            await asyncio.sleep(0.02)


def create_provider():
    if cfg.mock_mode:
        logger.info("LLM 模式 = Mock（未配置 LLM_API_KEY，或显式指定 mock）")
        return MockProvider()
    logger.info("LLM 模式 = %s | base=%s | model=%s", "openai-compatible", cfg.llm_base_url, cfg.llm_model)
    return OpenAIProvider()