"""
Semantic memory: ChromaDB for RAG + rules
"""
import chromadb
from pathlib import Path

def get_chroma_client():
    db_path = Path("data/chroma")
    db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_path))
    return client

"""
def ingest_corpus(corpus_dir="data/corpus"):
    client = get_chroma_client()
    col = client.get_or_create_collection("petase_papers")
    # Add docs - in real version parse PDFs
    col.add(documents=["Thermostable PETase requires disulfide at 43-58, Joo 2018"], ids=["rule_1"])
    return col.count()
"""


def ingest_corpus(corpus_dir="data/corpus"):
    import pymupdf  # PyMuPDF

    client = get_chroma_client()
    # Delete old collection so you can re-run ingestion
    try:
        client.delete_collection("petase_papers")
    except:
        pass
    col = client.get_or_create_collection("petase_papers")

    pdf_dir = Path(corpus_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    docs = []
    ids = []
    metadatas = []

    # Auto-find all PDFs you put in data/corpus/
    for pdf_file in pdf_dir.glob("*.pdf"):
        print(f"[RAG] Parsing {pdf_file.name}...")
        try:
            doc = pymupdf.open(pdf_file)
            text = ""
            for page in doc:
                text += page.get_text()
            # Chunk into ~1000 char pieces for better retrieval
            chunk_size = 1000
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i + chunk_size].strip()
                if len(chunk) > 200:  # skip tiny chunks
                    docs.append(chunk)
                    ids.append(f"{pdf_file.stem}_{i // chunk_size}")
                    metadatas.append({"source": pdf_file.name, "page_chunk": i // chunk_size})
        except Exception as e:
            print(f"[RAG] Failed to parse {pdf_file.name}: {e}")

    # Fallback rules if no PDFs found yet (so skeleton still runs)
    if not docs:
        print("[RAG] No PDFs found, using fallback rules")
        docs = [
            "Structural insight into molecular mechanism of poly (ethylene terephthalate) degradation, Joo et al 2018",
            "Engineering and evaluation of thermostable IsPETase variants for PET degradation, Brott et al 2021",
            "Molecular Insights into the Enhanced Activity and/or Thermostability of PET Hydrolase by D186 Mutations, Qu et al 2024",
            "Large language models generate functional protein sequences across diverse families. Mandani et al 2023",
            "ProGen2: Exploring the boundaries of protein language models, Nijkamp et al 2023"
        ]
        ids = ["rule_1", "rule_2", "rule_3", "rule_4", "rule_5"]
        metadatas = [{"source": "fallback"}] * 5

    col.add(documents=docs, ids=ids, metadatas=metadatas)
    print(f"[RAG] Ingested {col.count()} chunks from {len(list(pdf_dir.glob('*.pdf')))} PDFs")
    return col.count()