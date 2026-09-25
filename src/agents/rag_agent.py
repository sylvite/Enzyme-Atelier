"""Retrieve traceable corpus excerpts, with explicit missing-evidence status."""
from src.evidence import EvidenceExcerpt, RetrievalResult
from src.memory.semantic_store import get_chroma_client


def retrieve_evidence(query: str, top_k: int = 3) -> RetrievalResult:
    """Preserve complete excerpts and source/page metadata for decision records."""
    if not query.strip() or type(top_k) is not int or top_k < 1:
        raise ValueError("Retrieval needs a nonempty query and positive top_k")
    try:
        collection = get_chroma_client().get_collection("petase_papers")
        results = collection.query(query_texts=[query], n_results=top_k)
        documents = (results.get("documents") or [[]])[0]
        metadata = (results.get("metadatas") or [[]])[0]
        ids = (results.get("ids") or [[]])[0]
        if not documents:
            return RetrievalResult(query=query, status="empty")
        if len(documents) != len(metadata) or len(documents) != len(ids):
            raise ValueError("Retrieval returned misaligned documents, metadata, or IDs")
        excerpts = [EvidenceExcerpt.from_chunk(chunk_id, text, meta or {})
                    for chunk_id, text, meta in zip(ids, documents, metadata)
                    if isinstance(text, str) and text.strip()]
        return RetrievalResult(query=query, status="success" if excerpts else "empty", excerpts=excerpts)
    except Exception as exc:
        return RetrievalResult(query=query, status="unavailable", error=f"{type(exc).__name__}: {exc}")


def run_rag(query: str, top_k: int = 3) -> str:
    """Text adapter for the existing generation workflow."""
    result = retrieve_evidence(query, top_k)
    if result.status == "unavailable":
        return f"Retrieval unavailable: {result.error}"
    if result.status == "empty":
        return "Retrieval unavailable: no corpus excerpts found."
    sources = ", ".join(dict.fromkeys(item.source for item in result.excerpts))
    excerpts = " | ".join(item.text for item in result.excerpts)
    return f"Constraints from RAG ({sources}): {excerpts}"


def rag_constraints(query: str = "PETase thermostability") -> str:
    """Retrieve context for the shared backend."""
    return run_rag(query)
