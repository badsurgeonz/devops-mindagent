import logging

import httpx

from app.config import cfg

logger = logging.getLogger("tools.adapters")


class StructuredToolError(Exception):
    def __init__(self, error_code: str, message: str, retryable: bool = False, request_id: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.request_id = request_id

    def to_text(self) -> str:
        return (
            "{"
            f'"ok": false, "error_code": "{self.error_code}", '
            f'"message": "{self.message}", "retryable": {str(self.retryable).lower()}'
            "}"
        )


class MockLogAdapter:
    def __init__(self) -> None:
        self.request_id_counter = 0

    async def search(self, service_name: str, time_range_minutes: int, keyword: str | None,
                     limit: int, tenant_id: str) -> dict:
        self.request_id_counter += 1
        lines = [
            f"2026-09-06 14:22:10 ERROR  [{service_name}] 50 /api/order/create "
            "redis.clients.jedis.exceptions.JedisConnectionException: Could not get a resource from the pool",
            "    Caused by: java.net.SocketTimeoutException: Read timed out",
            "    at redis.clients.jedis.JedisPoolFactory... (JedisPoolFactory.java:102)",
            "Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example.token.abc123  (需脱敏)",
            "2026-09-06 14:22:12 ERROR  [order-service] 503 upstream connect error",
        ]
        if keyword:
            lines = [l for l in lines if keyword.lower() in l.lower()] or lines[:1]
        return {
            "ok": True,
            "request_id": f"mock-log-{self.request_id_counter}",
            "service_name": service_name,
            "time_range_minutes": time_range_minutes,
            "total": len(lines),
            "entries": [
                {"ts": l.split(" ERROR")[0], "level": "ERROR", "message": l} for l in lines[:limit]
            ],
        }


class HttpLogAdapter:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def search(self, service_name: str, time_range_minutes: int, keyword: str | None,
                     limit: int, tenant_id: str) -> dict:
        try:
            resp = await self.client.get(
                "/api/logs/search",
                params={
                    "service": service_name,
                    "minutes": time_range_minutes,
                    "keyword": keyword,
                    "limit": limit,
                    "tenant": tenant_id,
                },
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as exc:
            raise StructuredToolError("UPSTREAM_TIMEOUT", "日志平台暂时无响应，请稍后重试", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            raise StructuredToolError(
                "UPSTREAM_ERROR", f"日志平台返回异常状态码 {exc.response.status_code}", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise StructuredToolError("UPSTREAM_UNREACHABLE", "无法连接日志平台", retryable=True) from exc

    async def aclose(self) -> None:
        await self.client.aclose()


class MockRedisAdapter:
    async def status(self, cluster_id: str, key: str | None, tenant_id: str) -> dict:
        return {
            "ok": True,
            "cluster_id": cluster_id or "default",
            "used_memory_human": "482.3M",
            "used_memory_peak_human": "930M",
            "maxmemory_human": "1024M",
            "connected_clients": 128,
            "blocked_clients": 3,
            "hit_rate": 0.872,
            "keyspace_hits": 8841234,
            "keyspace_misses": 1297431,
            "big_key_alert": f"'cache:hot:stock:1001' size=1.8M elements=120000",
            "key_info": {"key": key or "—", "ttl_seconds": 12345, "size": "1.8M"},
        }


class HttpRedisAdapter:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def status(self, cluster_id: str, key: str | None, tenant_id: str) -> dict:
        try:
            resp = await self.client.get(
                f"/internal/redis/{cluster_id or 'default'}/status", params={"key": key, "tenant": tenant_id}
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as exc:
            raise StructuredToolError("UPSTREAM_TIMEOUT", "Redis 诊断服务暂时无响应，请稍后重试", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            raise StructuredToolError(
                "UPSTREAM_ERROR", f"Redis 诊断服务返回异常状态码 {exc.response.status_code}", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise StructuredToolError("UPSTREAM_UNREACHABLE", "无法连接 Redis 诊断服务", retryable=True) from exc

    async def aclose(self) -> None:
        await self.client.aclose()


def build_log_adapter() -> MockLogAdapter | HttpLogAdapter:
    if cfg.tool.log_platform_url:
        return HttpLogAdapter(cfg.tool.log_platform_url, cfg.tool.timeout)
    return MockLogAdapter()


def build_redis_adapter() -> MockRedisAdapter | HttpRedisAdapter:
    if cfg.tool.redis_diag_url:
        return HttpRedisAdapter(cfg.tool.redis_diag_url, cfg.tool.timeout)
    return MockRedisAdapter()