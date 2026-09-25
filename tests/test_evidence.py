"""Structured retrieval tests without embeddings, network, or real corpus changes."""
from unittest.mock import Mock

from src.agents import rag_agent
from src.evidence import EvidenceExcerpt


def test_evidence_identity_binds_content_and_source():
    first = EvidenceExcerpt.from_chunk("row", "evidence", {"source": "paper.pdf", "page": 2})
    same = EvidenceExcerpt.from_chunk("different-row", "evidence", {"source": "paper.pdf", "page": 2})
    changed = EvidenceExcerpt.from_chunk("row", "changed", {"source": "paper.pdf", "page": 2})
    assert first.evidence_id == same.evidence_id
    assert first.evidence_id != changed.evidence_id
    assert first.page == 2


def test_retrieval_preserves_full_excerpt_and_metadata(monkeypatch):
    client = Mock()
    client.get_collection.return_value.query.return_value = {
        "documents": [["evidence " * 100]], "ids": [["chunk-1"]],
        "metadatas": [[{"source": "paper.pdf", "page": 3}]],
    }
    monkeypatch.setattr(rag_agent, "get_chroma_client", lambda: client)
    result = rag_agent.retrieve_evidence("stability")
    assert result.status == "success"
    assert result.excerpts[0].text == "evidence " * 100
    assert result.excerpts[0].page == 3
    assert result.excerpts[0].chunk_id == "chunk-1"


def test_misaligned_citations_are_unavailable(monkeypatch):
    client = Mock()
    client.get_collection.return_value.query.return_value = {
        "documents": [["claim"]], "ids": [["chunk"]], "metadatas": [[]],
    }
    monkeypatch.setattr(rag_agent, "get_chroma_client", lambda: client)
    result = rag_agent.retrieve_evidence("query")
    assert result.status == "unavailable" and result.excerpts == []
    assert "misaligned" in result.error


def test_empty_retrieval_is_distinct_from_service_failure(monkeypatch):
    client = Mock()
    client.get_collection.return_value.query.return_value = {"documents": [[]]}
    monkeypatch.setattr(rag_agent, "get_chroma_client", lambda: client)
    assert rag_agent.retrieve_evidence("query").status == "empty"
    client.get_collection.side_effect = RuntimeError("database unavailable")
    result = rag_agent.retrieve_evidence("query")
    assert result.status == "unavailable" and result.excerpts == []
