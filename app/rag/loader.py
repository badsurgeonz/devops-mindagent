from pathlib import Path
import hashlib
import re

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


def _stable_id(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:24]


def split_chunks(text: str, source: str, max_len: int = 800,
                 doc_id: str = "", doc_version: str = "v1",
                 tenant_id: str = "tenant-a", visibility: str = "internal") -> list:
    chunks = []
    heading = source
    buf = []
    buf_len = 0
    chunk_index = 0

    def flush():
        nonlocal buf, buf_len, chunk_index
        body = "".join(buf).strip()
        if body:
            meta = {
                "doc_id": doc_id or source,
                "doc_version": doc_version,
                "tenant_id": tenant_id,
                "source": source,
                "heading": heading,
                "chunk_index": chunk_index,
                "visibility": visibility,
            }
            meta["id"] = _stable_id(tenant_id, meta["doc_id"], doc_version, chunk_index)
            chunks.append({**meta, "text": body})
            chunk_index += 1
        buf = []
        buf_len = 0

    for raw in text.splitlines():
        m = _HEADING.match(raw)
        if m:
            flush()
            heading = f"{source} › {m.group(2).strip()}"
            buf.append(raw)
            buf_len += len(raw)
        else:
            buf.append(raw)
            buf_len += len(raw)
            if buf_len >= max_len:
                flush()
    flush()
    return chunks


def load_markdown_dir(kb_dir: Path, tenant_id: str = "tenant-a", doc_version: str = "v1") -> list:
    chunks = []
    for path in sorted(kb_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        chunks.extend(
            split_chunks(raw, path.stem, doc_id=path.stem, doc_version=doc_version, tenant_id=tenant_id)
        )
    return chunks