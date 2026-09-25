"""Critique measured results and retrieve supporting evidence."""

from src.memory.semantic_store import get_chroma_client
from src.agents.evaluator_agent import recorded_fold_success, recorded_biophys_success


def query_rag_for_fix(failure_reason: str, top_k=3):
    """Retrieve evidence, without claiming unverified mutations are supported."""
    client = get_chroma_client()
    col = client.get_collection("petase_papers")
    query = "PETase stability protein engineering"
    if "plDDT" in failure_reason:
        query += " structure folding"
    results = col.query(query_texts=[query], n_results=top_k)
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    return docs, metas


def critique_results(results: list[dict]) -> dict:
    """Propose a bounded retry from measured failures, returning cited evidence.

    The returned prose is currently metadata for the sequence generator. Actual
    evidence-conditioned generation is a separate orchestration-design task.
    """
    if not results:
        return {"action": "stop", "reason": "No candidates to critique", "rag_sources": []}
    failing = [row for row in results if not row.get("eligible", row.get("passes", False))]
    if not failing:
        return {"action": "stop", "reason": "Screening passed", "rag_sources": []}
    if any(not recorded_fold_success(row) or not recorded_biophys_success(row) for row in failing):
        return {"action": "stop", "reason": "Evaluation evidence unavailable; resolve tool or input errors before redesign",
                "rag_sources": []}
    reason = failing[0].get("reason", "Screening failed")
    docs, metadata = query_rag_for_fix(reason)
    evidence = [{"text": doc, "source": meta.get("source", "unknown")}
                for doc, meta in zip(docs, metadata)]
    if not evidence:
        return {"action": "stop", "reason": "No retrieved evidence for a revision", "rag_sources": []}
    return {
        "action": "redesign", "failure_reason": reason,
        "rag_sources": [item["source"] for item in evidence], "evidence": evidence,
        "suggestion": "Review the retrieved evidence before another generation attempt.",
        "new_designer_prompt": "PETase screening feedback: " + reason + " | " + " | ".join(docs),
        "conditioning": "metadata_only",
    }
