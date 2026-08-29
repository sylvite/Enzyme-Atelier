"""
def critique_and_refine(eval_results, constraints):
    # Reflection loop
    best = eval_results[0] if eval_results else None
    if not best:
        return "Generate more diverse sequences", False
    if best["plddt"] < 70 or best["ii"] > 40:
        feedback = f"Best plDDT {best['plddt']} low, instability {best['ii']}. Suggest: add disulfide, reduce loops."
        return feedback, True # needs retry
    return "Pass", False
"""

"""
Critic Agent - Implements Reflection Pattern + Guardrails
Reads evaluator results, queries RAG for fixes, proposes new design constraints
"""

from src.memory.semantic_store import get_chroma_client
import json
from pathlib import Path

def query_rag_for_fix(failure_reason: str, top_k=3):
    """Query your ingested PDFs for thermostable strategies"""
    client = get_chroma_client()
    col = client.get_collection("petase_papers")

    # Build RAG query based on failure
    if "plDDT" in failure_reason:
        query = "thermostable PETase mutations disulfide bond salt bridge engineering melting temperature Tm increase"
    elif "II" in failure_reason:
        query = "PETase stability instability index protein engineering thermostability"
    else:
        query = "PETase engineering thermostability directed evolution"

    results = col.query(query_texts=[query], n_results=top_k)
    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []

    print(f"[Critic RAG] Queried '{query}' -> {len(docs)} chunks")
    for i, (d, m) in enumerate(zip(docs, metas)):
        print(f" [{i}] {m.get('source','')} : {d[:150]}...")

    return docs, metas

def critique_eval_results(eval_path="outputs/eval_results.json"):
    """Main critic function - reads evaluator JSON and proposes fix"""
    if not Path(eval_path).exists():
        print(f"[Critic] No eval file at {eval_path}")
        return None

    with open(eval_path) as f:
        results = json.load(f)

    # Find first failing candidate
    failing = [r for r in results if not r["passes"]]
    passing = [r for r in results if r["passes"]]

    print(f"\n[Critic] Found {len(passing)} PASS, {len(failing)} FAIL")

    if not failing:
        print("[Critic] All candidates PASS - no critique needed")
        return {"action": "stop", "reason": "All pass"}

    # Take worst failing to critique
    worst = failing[0]
    reason = worst["reason"]
    print(f"[Critic] Critiquing: {reason}")

    # RAG lookup
    rag_docs, rag_metas = query_rag_for_fix(reason)

    # Build improved prompt for designer
    # Guardrail: Must not suggest non-PETase or toxic sequences

    seq_len = len(worst['sequence'])

    # Dynamic guardrail evaluation
    if seq_len < 240:
        guardrail_status = f"WARNING: seq len {seq_len} < 240 - too short, next design must target 290 AA full PETase"
        length_fix = "Request full-length 290 AA PETase"
    elif seq_len > 320:
        guardrail_status = f"WARNING: seq len {seq_len} > 320 - too long"
        length_fix = "Truncate to 290 AA"
    else:
        guardrail_status = f"PASS: seq len {seq_len} in 240-320 AA window"
        length_fix = "Length OK"

    # Check for non-canonical AAs (B, J, O, U, X, Z)
    non_canonical = set(worst['sequence']) - set("ACDEFGHIKLMNPQRSTVWY")
    if non_canonical:
        guardrail_status += f", FAIL: non-canonical AAs found {non_canonical}"
    else:
        guardrail_status += ", PASS: canonical AAs only"

    suggestion = f"""
FAILURE: {reason}
Sequence had II={worst['ii']:.1f} plDDT={worst['plddt']:.1f} len={seq_len}

RAG-BASED FIX (from {', '.join(set([m.get('source','papers') for m in rag_metas])) if rag_metas else 'papers'}):
- Based on retrieved chunks: {rag_docs[0][:300] if rag_docs else 'No RAG'}
- Proposed fixes from RAG:
    1. Disulfide: {rag_docs[0][:100] if rag_docs else 'N233C/S282C per Brott 2022'}
    2. Thermostability: {rag_docs[1][:100] if len(rag_docs)>1 else 'F201I per Brott 2022'}
    3. Salt bridge: D186H per Qu 2024

GUARDRAIL CHECK:
- {guardrail_status}
- {length_fix}
- Must retain catalytic triad S160-D206-H237

NEXT ACTION: Redesign with prompt = "Full-length 290 AA thermostable PETase with {rag_docs[0][:80] if rag_docs else 'disulfide N233C/S282C'}"
"""

    critique_output = {
        "action": "redesign",
        "failure_reason": reason,
        "rag_sources": [m.get('source') for m in rag_metas],
        "suggestion": suggestion,
        "new_designer_prompt": f"Thermostable PETase with DS1 disulfide C43-C58 and S121E/D186H salt bridge, {worst['sequence'][:50]}"
    }

    # Save for orchestrator
    Path("outputs").mkdir(exist_ok=True)
    with open("outputs/critique.json", "w") as f:
        json.dump(critique_output, f, indent=2)

    print(f"\n[Critic] Suggestion saved to outputs/critique.json")
    print(suggestion)

    # Episodic memory log
    with open("outputs/episodic_log.jsonl", "a") as f:
        f.write(json.dumps({"type": "critique", "critique": critique_output}) + "\n")

    return critique_output

if __name__ == "__main__":
    critique_eval_results()