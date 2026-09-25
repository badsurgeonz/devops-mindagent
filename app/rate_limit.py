import asyncio
import time

from app.config import cfg

_LUA_TOKEN_BUCKET = """
local rate = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', KEYS[1], 'ts', 'tokens')
local ts = tonumber(data[1]) or now
local tokens = tonumber(data[2]) or cap
tokens = math.min(cap, tokens + (now - ts) * rate)
local ok = 0
if tokens >= 1 then
    tokens = tokens - 1
    ok = 1
end
redis.call('HMSET', KEYS[1], 'ts', now, 'tokens', tokens)
redis.call('PEXPIRE', KEYS[1], math.floor(cap / rate * 1000) + 5000)
return ok
"""


class TokenBucketLimiter:
    def __init__(self, kv, rate: float, cap: float) -> None:
        self.kv = kv
        self.rate = rate
        self.cap = cap
        self._buckets: dict = {}
        self._lock = asyncio.Lock()
        self._use_redis = kv.kind == "redis" and cfg.redis_rate_script

    async def allow(self, key: str) -> bool:
        full_key = f"{cfg.rate_prefix}{key}"
        if self._use_redis:
            res = await self.kv.eval_script(_LUA_TOKEN_BUCKET, [full_key], [str(self.rate), str(self.cap), str(time.time())])
            return bool(res)
        async with self._lock:
            now = time.monotonic()
            state = self._buckets.setdefault(key, {"tokens": self.cap, "ts": now})
            state["tokens"] = min(self.cap, state["tokens"] + (now - state["ts"]) * self.rate)
            state["ts"] = now
            if state["tokens"] >= 1:
                state["tokens"] -= 1
                return True
            return False