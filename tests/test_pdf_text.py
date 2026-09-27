"""Portable mapping application, source preservation, and stale-repair rejection."""
import hashlib
import json

import pymupdf
import pytest

from src.memory.pdf_text import repair_text_mappings


@pytest.fixture
def source(tmp_path):
    pdf = tmp_path / 'fixture.pdf'
    stream = b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n/CMapType 2 def\n1 begincodespacerange\n<00> <ff>\nendcodespacerange\n1 beginbfchar\n<32> <0032>\nendbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop end end'
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), '12')
        font = page.get_fonts()[0][0]
        target = doc.get_new_xref()
        doc.update_object(target, '<<>>')
        doc.update_stream(target, stream)
        doc.xref_set_key(font, 'ToUnicode', f'{target} 0 R')
        doc.save(pdf)
    manifest = tmp_path / 'repairs.json'
    entry = {'filename': pdf.name, 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
             'repairs': [{'stream_xref': target, 'stream_sha256': hashlib.sha256(stream).hexdigest(),
                          'mappings': {'31': '9'}}]}
    manifest.write_text(json.dumps({'documents': [entry]}))
    return pdf, manifest, entry


def test_mapping_applies_in_memory_and_preserves_file(source):
    pdf, manifest, _ = source
    original = pdf.read_bytes()
    with pymupdf.open(pdf) as doc:
        assert doc[0].get_text().strip() == '12'
        assert repair_text_mappings(doc, pdf, manifest)
        # Re-open in-memory bytes to avoid the font cache from the first extraction.
        with pymupdf.open(stream=doc.tobytes(), filetype='pdf') as repaired:
            assert repaired[0].get_text().strip() == '92'
    assert pdf.read_bytes() == original
    with pymupdf.open(pdf) as doc:
        assert doc[0].get_text().strip() == '12'


def test_changed_document_is_rejected(source):
    pdf, manifest, _ = source
    pdf.write_bytes(pdf.read_bytes() + b'\n')
    with pymupdf.open(pdf) as doc, pytest.raises(ValueError, match='PDF changed'):
        repair_text_mappings(doc, pdf, manifest)


def test_changed_stream_is_rejected_before_update(source):
    pdf, manifest, entry = source
    entry['repairs'][0]['stream_sha256'] = 'bad'
    manifest.write_text(json.dumps({'documents': [entry]}))
    with pymupdf.open(pdf) as doc, pytest.raises(ValueError, match='verified repair'):
        repair_text_mappings(doc, pdf, manifest)


def test_unrelated_document_is_unchanged(source, tmp_path):
    pdf, manifest, _ = source
    other = tmp_path / 'other.pdf'
    other.write_bytes(pdf.read_bytes() + b'\n')
    with pymupdf.open(other) as doc:
        assert not repair_text_mappings(doc, other, manifest)
        assert doc[0].get_text().strip() == '12'


def test_renamed_identical_document_is_repaired(source, tmp_path):
    pdf, manifest, _ = source
    renamed = tmp_path / 'renamed.pdf'
    renamed.write_bytes(pdf.read_bytes())
    with pymupdf.open(renamed) as doc:
        assert repair_text_mappings(doc, renamed, manifest)
        assert doc[0].get_text().strip() == '92'


def test_ingestion_indexes_repaired_text_with_provenance(source, monkeypatch):
    from unittest.mock import Mock
    from src.memory import semantic_store, pdf_text
    pdf, manifest, _ = source
    client = Mock()
    collection = client.get_or_create_collection.return_value
    collection.get.return_value = {'ids': []}
    monkeypatch.setattr(semantic_store, 'get_chroma_client', lambda path: client)
    monkeypatch.setattr(pdf_text, 'repair_text_mappings',
                        lambda doc, path: repair_text_mappings(doc, path, manifest))
    semantic_store.ingest_corpus(pdf.parent)
    kwargs = collection.upsert.call_args.kwargs
    assert kwargs['documents'] == ['92']
    assert kwargs['metadatas'] == [{'source': pdf.name, 'page': 1, 'page_chunk': 0,
                                    'text_mapping_repaired': True}]
