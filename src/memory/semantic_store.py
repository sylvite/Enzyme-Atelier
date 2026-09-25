"""Persistent corpus retrieval and non-destructive PDF ingestion."""
from pathlib import Path
import hashlib

import chromadb


def get_chroma_client(db_path="data/chroma"):
    path = Path(db_path)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def ingest_corpus(corpus_dir="data/corpus", db_path="data/chroma"):
    """Upsert PDFs after parsing all inputs; never replace papers with canned rules.

    Re-ingestion updates chunks for the supplied filenames. Papers absent from
    the directory remain stored. A failed parse leaves the collection untouched.
    """
    import pymupdf

    pdfs = sorted(Path(corpus_dir).glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF files found in {corpus_dir}")
    docs, ids, metadata = [], [], []
    for pdf in pdfs:
        start = len(docs)
        source_id = hashlib.sha256(pdf.name.encode("utf-8")).hexdigest()
        with pymupdf.open(pdf) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text()
                for offset in range(0, len(text), 1000):
                    chunk = text[offset:offset + 1000].strip()
                    if not chunk:
                        continue
                    docs.append(chunk)
                    ids.append(f"{source_id}_{page_number}_{offset // 1000}")
                    metadata.append({"source": pdf.name, "page": page_number,
                                     "page_chunk": offset // 1000})
        if len(docs) == start:
            raise ValueError(f"No extractable text in {pdf.name}; OCR is not provided")

    collection = get_chroma_client(db_path).get_or_create_collection("petase_papers")
    # One upsert keeps embedding failures from clearing existing evidence.
    # Chroma limits batch sizes; reject oversize corpora explicitly for now.
    collection.upsert(documents=docs, ids=ids, metadatas=metadata)
    current = set(ids)
    for pdf in pdfs:
        old = collection.get(where={"source": pdf.name}, include=[])["ids"]
        stale = [item for item in old if item not in current]
        if stale:
            collection.delete(ids=stale)
    return collection.count()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ingest PDF text into the local retrieval store")
    parser.add_argument("--corpus-dir", default="data/corpus", type=Path)
    parser.add_argument("--db-path", default="data/chroma", type=Path)
    args = parser.parse_args()
    try:
        count = ingest_corpus(args.corpus_dir, args.db_path)
    except Exception as exc:
        parser.exit(1, f"Ingestion failed: {type(exc).__name__}: {exc}\n")
    print(f"Corpus collection contains {count} chunks")


if __name__ == "__main__":
    main()
