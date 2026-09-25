import asyncio
from pathlib import Path

from app.config import cfg
from app.rag.loader import split_chunks


def parse_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return path.read_text(encoding="utf-8")


def load_tenant_docs(tenant_id: str = "tenant-a") -> list:
    from app.rag.loader import load_markdown_dir

    chunks = load_markdown_dir(cfg.kb_dir, tenant_id=tenant_id)
    for path in sorted(cfg.kb_dir.glob("*.pdf")):
        text = extract_text(path)
        chunks.extend(
            split_chunks(text, path.stem, doc_id=path.stem, doc_version="v1", tenant_id=tenant_id)
        )
    return chunks


async def index_document(path: Path, retriever, tenant_id: str = "tenant-a") -> int:
    text = await asyncio.to_thread(extract_text, path)
    chunks = split_chunks(text, path.stem, doc_id=path.stem, doc_version="v1", tenant_id=tenant_id)
    if not chunks:
        return 0

    async def _rebuild():
        all_chunks = await asyncio.to_thread(load_tenant_docs, tenant_id)
        retriever.reindex(all_chunks)

    await _rebuild()
    return len(chunks)


async def rebuild_retriever(retriever, tenant_id: str = "tenant-a") -> int:
    chunks = await asyncio.to_thread(load_tenant_docs, tenant_id)
    retriever.reindex(chunks)
    return len(chunks)