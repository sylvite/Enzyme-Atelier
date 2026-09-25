"""Offline setup, ingestion, and pinned model-loading contracts."""
from unittest.mock import Mock

import pytest
import pymupdf

from src.memory import semantic_store as store
from src.agents import rag_agent
from src.tools import progen2_tool as generation


def make_pdf(path, text="Evidence about protein stability."):
    with pymupdf.open() as document:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
        document.save(path)


@pytest.mark.parametrize("kind", ["missing", "empty", "invalid"])
def test_failed_ingestion_does_not_touch_store(tmp_path, monkeypatch, kind):
    client = Mock(side_effect=AssertionError("Must parse before connecting"))
    monkeypatch.setattr(store, "get_chroma_client", client)
    if kind == "empty":
        make_pdf(tmp_path / "paper.pdf", "")
    elif kind == "invalid":
        (tmp_path / "paper.pdf").write_text("not a PDF")
    with pytest.raises(Exception):
        store.ingest_corpus(tmp_path)
    client.assert_not_called()


def test_ingestion_preserves_text_and_page_sources(tmp_path, monkeypatch):
    make_pdf(tmp_path / "paper.pdf")
    client = Mock()
    collection = client.get_or_create_collection.return_value
    collection.get.return_value = {"ids": ["obsolete-chunk"]}
    collection.count.return_value = 1
    monkeypatch.setattr(store, "get_chroma_client", lambda path: client)
    assert store.ingest_corpus(tmp_path) == 1
    kwargs = collection.upsert.call_args.kwargs
    assert kwargs["documents"] == ["Evidence about protein stability."]
    assert kwargs["metadatas"] == [{"source": "paper.pdf", "page": 1, "page_chunk": 0}]
    collection.delete.assert_called_once_with(ids=["obsolete-chunk"])
    client.delete_collection.assert_not_called()


def test_embedding_failure_does_not_delete_evidence(tmp_path, monkeypatch):
    make_pdf(tmp_path / "paper.pdf")
    client = Mock()
    collection = client.get_or_create_collection.return_value
    collection.upsert.side_effect = RuntimeError("embedding unavailable")
    monkeypatch.setattr(store, "get_chroma_client", lambda path: client)
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        store.ingest_corpus(tmp_path)
    collection.delete.assert_not_called()
    client.delete_collection.assert_not_called()


def test_retrieval_failure_does_not_invent_citations(monkeypatch):
    monkeypatch.setattr(rag_agent, "get_chroma_client", Mock(side_effect=RuntimeError("no corpus")))
    result = rag_agent.run_rag("query")
    assert result == "Retrieval unavailable: RuntimeError: no corpus"


def test_pinned_loader_uses_tokenizer_json_and_sequence_delimiters(monkeypatch):
    import huggingface_hub
    import transformers
    download = Mock(return_value="tokenizer.json")
    tokenizer = Mock()
    model = Mock()
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    monkeypatch.setattr(transformers, "PreTrainedTokenizerFast", tokenizer)
    monkeypatch.setattr(transformers.AutoModelForCausalLM, "from_pretrained", model)
    monkeypatch.setattr(generation, "_model_cache", {})
    loaded, tokens, reference = generation._load_model()
    generation._load_model()
    assert reference == generation.MODEL_REFERENCE
    assert loaded is model.return_value and tokens is tokenizer.return_value
    download.assert_called_once_with(generation.MODEL_ID, "tokenizer.json", revision=generation.MODEL_REVISION)
    assert tokenizer.call_args.kwargs["bos_token"] == "1"
    assert tokenizer.call_args.kwargs["eos_token"] == "2"
    model.assert_called_once_with(generation.MODEL_ID, revision=generation.MODEL_REVISION,
                                  code_revision=generation.MODEL_REVISION,
                                  trust_remote_code=True, use_safetensors=True)

def test_pdf_ingestion_roundtrip_with_real_chroma(tmp_path, monkeypatch):
    from chromadb.api.types import EmbeddingFunction

    class OfflineEmbedding(EmbeddingFunction):
        def __init__(self):
            pass

        def __call__(self, input):
            return [[1.0, float(len(text))] for text in input]

        @staticmethod
        def name():
            return "offline-test-embedding"

        def get_config(self):
            return {}

        @staticmethod
        def build_from_config(config):
            return OfflineEmbedding()

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    make_pdf(corpus / "paper.pdf")
    real_client = store.get_chroma_client(tmp_path / "database")
    adapter = Mock()
    adapter.get_or_create_collection.side_effect = lambda name: real_client.get_or_create_collection(
        name, embedding_function=OfflineEmbedding())
    monkeypatch.setattr(store, "get_chroma_client", lambda path: adapter)
    assert store.ingest_corpus(corpus) == 1
    assert store.ingest_corpus(corpus) == 1  # Upsert is repeatable, not duplicate append.
    collection = real_client.get_collection("petase_papers", embedding_function=OfflineEmbedding())
    result = collection.query(query_texts=["protein"], n_results=1)
    assert result["documents"] == [["Evidence about protein stability."]]
    assert result["metadatas"][0][0]["source"] == "paper.pdf"
    assert result["metadatas"][0][0]["page"] == 1
