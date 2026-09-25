from app.config import cfg
from app.utils import cosine, embed


class LocalVectorStore:
    def __init__(self) -> None:
        self.ids: list = []
        self.vectors: list = []
        self.metadatas: list = []

    def add(self, ids: list, vectors: list, metadatas: list) -> None:
        self.ids.extend(ids)
        self.vectors.extend(vectors)
        self.metadatas.extend(metadatas)

    def query(self, vector: list, top_k: int = 10, where: dict | None = None) -> list:
        scored = []
        for i, (vec, meta) in enumerate(zip(self.vectors, self.metadatas)):
            if where and not all(meta.get(k) == v for k, v in where.items()):
                continue
            scored.append((i, cosine(vector, vec)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {"id": self.ids[i], "score": float(s), "metadata": self.metadatas[i]}
            for i, s in scored[:top_k]
        ]

    def delete(self, where: dict) -> None:
        keep = []
        for i, meta in enumerate(self.metadatas):
            if where and all(meta.get(k) == v for k, v in where.items()):
                continue
            keep.append(i)
        self.ids = [self.ids[i] for i in keep]
        self.vectors = [self.vectors[i] for i in keep]
        self.metadatas = [self.metadatas[i] for i in keep]

    @property
    def size(self) -> int:
        return len(self.ids)


class ChromaStore:
    def __init__(self) -> None:
        import chromadb

        if cfg.vector.store == "chroma-http":
            client = chromadb.HttpClient(host=cfg.vector.host, port=cfg.vector.port)
        else:
            client = chromadb.PersistentClient(path=str(cfg.data_dir / "chroma"))
        self.col = client.get_or_create_collection(
            name=cfg.vector.collection, metadata={"hnsw:space": "cosine"}
        )

    def add(self, ids: list, vectors: list, metadatas: list) -> None:
        self.col.upsert(ids=ids, embeddings=vectors, metadatas=metadatas)

    def query(self, vector: list, top_k: int = 10, where: dict | None = None) -> list:
        res = self.col.query(query_embeddings=[vector], n_results=top_k, where=where)
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        return [
            {"id": i, "score": 1.0 - float(d), "metadata": m or {}}
            for i, d, m in zip(ids, dists, metas)
        ]

    def delete(self, where: dict) -> None:
        self.col.delete(where=where)


class HashEmbedder:
    name = "hash"

    def embed(self, texts: list) -> list:
        return [embed(t) for t in texts]


class BGEEmbedder:
    name = "bge"

    def __init__(self, model_name: str = "") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name or cfg.vector.embedding_model)

    def embed(self, texts: list) -> list:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class IdentityReranker:
    name = "identity"

    def rerank(self, query: str, pairs: list) -> list | None:
        return None


class BGEReranker:
    name = "bge"

    def __init__(self, model_name: str = "") -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name or cfg.vector.reranker_model)

    def rerank(self, query: str, pairs: list) -> list:
        return self.model.predict([(query, p) for p in pairs]).tolist()


def build_embedder() -> HashEmbedder | BGEEmbedder:
    if cfg.vector.enabled:
        return BGEEmbedder()
    return HashEmbedder()


def build_reranker() -> IdentityReranker | BGEReranker | None:
    if cfg.vector.enabled:
        return BGEReranker()
    return IdentityReranker()


def build_vector_store() -> LocalVectorStore | ChromaStore:
    if cfg.vector.enabled:
        return ChromaStore()
    return LocalVectorStore()