"""
from concurrent.futures import ThreadPoolExecutor
from src.tools.esmfold_tool import esmfold_fold, ESMFoldInput
#from src.tools.biophys_tool import biophys_score, BioPhysInput, calc_instability
from src.tools.biophys_tool import  calc_instability

def evaluate_parallel(sequences):
#    def eval_one(seq):
#        fold = esmfold_fold(ESMFoldInput(sequence=seq))
#        bio = biophys_score(BioPhysInput(sequence=seq))
#        return {"seq": seq, "plddt": fold.plddt, "ii": bio.instability_index, "triad": bio.triad_intact, "success": fold.success}

    def evaluate_one(seq):
        fold_res = esmfold_fold(seq)
        ii_res = calc_instability(seq)  # your biophys tool using BioPython
        return {"seq": seq, "plddt": fold_res["plddt"], "ii": ii_res["ii"], "pdb": fold_res["pdb"]}

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(evaluate_one, sequences))
    return sorted(results, key=lambda x: x["plddt"], reverse=True)
"""

"""
Evaluator Agent - Implements Evaluator Pattern
Uses ESMFold + Biophysics tools to rank candidates
"""

from src.tools.esmfold_tool import esmfold_fold
from src.tools.biophys_tool import calc_instability
#from src.memory.semantic_store import get_chroma_client
from pathlib import Path
import json

def evaluate_one(seq: str, save_pdb=False):
    original_len = len(seq) # save original
    """Evaluate single sequence - returns dict with pass/fail"""
    # 1. Biophysics first (fast, no API)
    bio_res = calc_instability(seq)
    ii = bio_res["ii"]
    is_stable = bio_res["is_stable"]

    # 2. ESMFold (slow API) - only on first 250 AA for speed if seq is long
    fold_seq = seq[:250] if len(seq) > 250 else seq
    fold_res = esmfold_fold(fold_seq)
    plddt = fold_res["plddt"]

    # 3. Combined decision
    passes = False
    reason = ""

    if plddt > 70 and is_stable:
        passes = True
        reason = f"PASS: plDDT {plddt:.1f} >70 and II {ii:.1f} <40"
    elif not is_stable:
        passes = False
        reason = f"FAIL: II {ii:.1f} >=40 unstable"
    elif plddt <= 70:
        passes = False
        reason = f"FAIL: plDDT {plddt:.1f} <=70 poor folding, needs thermostable mutations per RAG"
    else:
        passes = False
        reason = "FAIL: unknown"

    print(f"[Evaluator] {reason}")

    result = {
        "sequence": seq,  # NOT fold_seq - keep full length for critic
        "full_len": original_len,
        "fold_len": len(fold_seq),
        "ii": ii,
        "plddt": plddt,
        "is_stable": is_stable,
        "passes": passes,
        "reason": reason,
        "pdb": fold_res["pdb"] if save_pdb else ""
    }
    return result

def evaluate_batch(fasta_path="outputs/best_0.fasta", top_k=2):
    """Evaluate all sequences in FASTA"""
    from Bio import SeqIO

    results = []
    for record in SeqIO.parse(fasta_path, "fasta"):
        seq = str(record.seq)
        res = evaluate_one(seq)
        results.append(res)

    # Sort by plDDT descending, then II ascending
    results_sorted = sorted(results, key=lambda x: (-x["plddt"], x["ii"]))

    # Save results for critic
    Path("outputs").mkdir(exist_ok=True)
    with open("outputs/eval_results.json", "w") as f:
        json.dump(results_sorted, f, indent=2, default=str)

    print(f"\n[Evaluator] Top {top_k} candidates:")
    for r in results_sorted[:top_k]:
        print(f" - plDDT {r['plddt']:.1f} II {r['ii']:.1f} PASS={r['passes']} - {r['reason']}")

    return results_sorted

if __name__ == "__main__":
    evaluate_batch()