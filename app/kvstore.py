import json
import logging
import time

logger = logging.getLogger("kvstore")


class MemKV:
    kind = "memory"

    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = None

    def _purge(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._data.items() if exp and exp < now]
        for k in expired:
            self._data.pop(k, None)

    async def get(self, key: str) -> str | None:
        self._purge()
        item = self._data.get(key)
        if not item:
            return None
        val, exp = item
        if exp and exp < time.time():
            self._data.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        exp = time.time() + ttl if ttl else None
        self._data[key] = (value, exp)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def get_json(self, key: str):
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    async def ping(self) -> bool:
        return True


class RedisKV:
    kind = "redis"

    def __init__(self, url: str) -> None:
        from redis import asyncio as aioredis

        self._client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl:
            await self._client.setex(key, ttl, value)
        else:
            await self._client.set(key, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def get_json(self, key: str):
        raw = await self.get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def eval_script(self, script: str, keys: list, args: list):
        return await self._client.eval(script, len(keys), *keys, *args)


def create_kv(cfg) -> MemKV | RedisKV:
    if cfg.redis_url:
        try:
            kv = RedisKV(cfg.redis_url)
            logger.info("KV store = redis (%s)", cfg.redis_url.split("@")[-1])
            return kv
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis 不可用(%s)，降级为内存存储", exc)
    return MemKV()
