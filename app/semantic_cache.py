import json

from app.config import cfg
from app.utils import cosine, embed, normalize


class SemanticCache:
    def __init__(self, kv, threshold: float = 0.95, ttl: int = 600) -> None:
        self.kv = kv
        self.threshold = threshold
        self.ttl = ttl

    def _key(self, namespace: str) -> str:
        return f"{cfg.index_key}:{namespace}"

    async def lookup(self, query: str, namespace: str = "default") -> str | None:
        q = normalize(query)
        if not q:
            return None
        qv = embed(q)
        index = await self.kv.get_json(self._key(namespace)) or []
        best = None
        best_sim = -1.0
        for entry in index:
            sim = cosine(qv, entry["v"])
            if sim > best_sim:
                best_sim = sim
                best = entry["a"]
        if best is not None and best_sim >= self.threshold:
            return best
        return None

    async def put(self, query: str, answer: str, namespace: str = "default") -> None:
        q = normalize(query)
        if not q or not answer:
            return
        if await self.lookup(query, namespace) is not None:
            return
        key = self._key(namespace)
        index = await self.kv.get_json(key) or []
        index.append({"q": q, "v": embed(q), "a": answer})
        if len(index) > 500:
            index = index[-500:]
        await self.kv.set_json(key, index, ttl=self.ttl)