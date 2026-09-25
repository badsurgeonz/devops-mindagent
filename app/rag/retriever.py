import asyncio

from rank_bm25 import BM25Okapi

from app.rag.vectorstore import HashEmbedder, IdentityReranker, LocalVectorStore, build_embedder, build_reranker, build_vector_store
from app.utils import cosine, tokenize


class HybridRetriever:
    def __init__(self, chunks: list, bm25_weight: float = 0.35, vector_weight: float = 0.65,
                 embedder=None, vector_store=None, reranker=None) -> None:
        self.chunks = chunks
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.embedder = embedder or HashEmbedder()
        self.vector_store = vector_store or LocalVectorStore()
        self.reranker = reranker or IdentityReranker()
        self._rebuild()

    def _rebuild(self) -> None:
        corpus = [tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(corpus)
        vectors = self.embedder.embed([c["text"] for c in self.chunks])
        self.vector_store.add([c["id"] for c in self.chunks], vectors, [c for c in self.chunks])

    def reindex(self, chunks: list) -> None:
        self.chunks = chunks
        self._rebuild()

    def _filtered_indices(self, tenant_id: str | None) -> list:
        if tenant_id is None:
            return list(range(len(self.chunks)))
        return [i for i, c in enumerate(self.chunks) if c.get("tenant_id") == tenant_id]

    async def retrieve(self, query: str, top_k: int = 3, tenant_id: str | None = None,
                       permissions: set | None = None) -> list:
        indices = self._filtered_indices(tenant_id)
        if not indices:
            return []

        qv = await asyncio.to_thread(self.embedder.embed, [query])
        qv = qv[0]

        bm25_scores = self.bm25.get_scores(tokenize(query))
        max_bm25 = max((bm25_scores[i] for i in indices), default=1.0) or 1.0

        where = {"tenant_id": tenant_id} if tenant_id else None
        vector_hits = await asyncio.to_thread(self.vector_store.query, qv, top_k=20, where=where)
        vector_map = {h["id"]: h["score"] for h in vector_hits}

        merged: dict = {}
        for i in indices:
            c = self.chunks[i]
            merged[c["id"]] = {
                "index": i,
                "chunk": c,
                "bm25": bm25_scores[i] / max_bm25,
                "vector": vector_map.get(c["id"], 0.0),
            }
        for h in vector_hits:
            if h["id"] not in merged:
                merged[h["id"]] = {
                    "index": -1,
                    "chunk": h["metadata"],
                    "bm25": 0.0,
                    "vector": h["score"],
                }

        entries = list(merged.values())
        if self.reranker is not None and getattr(self.reranker, "name", "") != "identity":
            texts = [e["chunk"].get("text", "") for e in entries]
            scores = await asyncio.to_thread(self.reranker.rerank, query, texts)
            for e, s in zip(entries, scores):
                e["final"] = float(s)
        else:
            for e in entries:
                e["final"] = self.bm25_weight * e["bm25"] + self.vector_weight * e["vector"]

        entries.sort(key=lambda x: x["final"], reverse=True)
        return [
            {
                "id": e["chunk"].get("id", ""),
                "score": round(e["final"], 4),
                "source": e["chunk"].get("source", ""),
                "heading": e["chunk"].get("heading", ""),
                "text": e["chunk"].get("text", ""),
                "doc_version": e["chunk"].get("doc_version", ""),
            }
            for e in entries[:top_k]
        ]

    @property
    def size(self) -> int:
        return len(self.chunks)


def build_retriever(chunks: list, bm25_weight: float = 0.35, vector_weight: float = 0.65) -> HybridRetriever:
    return HybridRetriever(
        chunks,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        embedder=build_embedder(),
        vector_store=build_vector_store(),
        reranker=build_reranker(),
    )