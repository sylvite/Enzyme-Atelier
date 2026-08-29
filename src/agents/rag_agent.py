"""
def run_rag(query: str) -> str:
    # TODO: implement retrieval from ChromaDB with citations
    return "Constraints: Keep catalytic triad S160-D206-H237, target Tm > 65C [Joo 2018]"
"""


"""
RAG Agent - Retrieves engineering constraints from your 3-paper open-access corpus
"""

from src.memory.semantic_store import get_chroma_client
from typing import List, Dict

def run_rag(query: str, top_k: int = 3) -> str:
    """
    Real RAG retrieval with citations
    """
    try:
        client = get_chroma_client()
        col = client.get_collection("petase_papers")

        results = col.query(query_texts=[query], n_results=top_k)
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        if not docs:
            return "Constraints: Keep catalytic triad S160-D206-H237, target Tm > 65C [Fallback]"

        # Build citation-rich constraints
        constraints = []
        citations = []
        for doc, meta in zip(docs, metas):
            source = meta.get("source", "unknown")
            constraints.append(doc[:300])
            citations.append(source)

        combined = " | ".join(constraints)
        cite_str = ", ".join(set(citations))

        result = f"Constraints from RAG ({cite_str}): {combined}"

        print(f"[RAG] Query: {query}")
        print(f"[RAG] Retrieved {len(docs)} chunks from {cite_str}")
        print(f"[RAG] {result[:400]}...")

        return result

    except Exception as e:
        print(f"[RAG] Error {e}, using fallback")
        return "Constraints: Keep catalytic triad S160-D206-H237, target Tm > 65C, consider disulfide DS1 43-58 [Joo 2018], D186H salt bridge [Qu 2024] [Fallback]"

def rag_constraints(query: str = "PETase thermostability") -> str:
    """
    Backward compat for main.py - main.py expects this name
    This is the function main.py calls
    """
    return run_rag(query, top_k=3)

def get_rag_context_for_designer(failure_reason: str = "") -> str:
    """
    Helper for critic to get designer prompt
    """
    if "plDDT" in failure_reason:
        q = "thermostable PETase disulfide salt bridge D186 mutation Tm increase"
    else:
        q = "PETase thermostability engineering"

    return run_rag(q, top_k=2)

if __name__ == "__main__":
    # Test with your new corpus
    print(run_rag("thermostable PETase disulfide"))
    print("\n---\n")
    print(run_rag("D186H salt bridge mutation"))
    print("\n---\n")
    print(rag_constraints("PETase thermostability"))