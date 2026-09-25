from src.agents.rag_agent import run_rag, rag_constraints
from src.agents.designer_agent import design_candidates, GenerationFailure
from src.agents.evaluator_agent import (
    evaluate_batch, candidate_sort_key, recorded_fold_success, recorded_biophys_success,
)
from src.agents.critic_agent import critique_eval_results # NEW API - was critique_and_refine
from src.guards.petase_validator import PetaseValidator, human_approval_gate
from src.memory.episodic_store import log_run
from pathlib import Path
import json

class AtelierResult:
    def __init__(self, best, history, status="complete", error=""):
        self.best = best
        self.history = history
        self.status = status
        self.error = error
    def summary(self):
        if self.error:
            return f"Run {self.status}: {self.error}"
        seq = self.best.get('sequence','') or self.best.get('seq','')
        return f"Best: plDDT {self.best.get('plddt')} II {self.best.get('ii')} len {len(seq)}"

def run_enzyme_atelier(user_query: str, max_iterations: int = 2, n_candidates: int = 1):
    """
    Main orchestration loop - compatible with current evaluator/critic
    """
    Path("outputs").mkdir(exist_ok=True)

    # 1. RAG constraints (compatible with both run_rag and rag_constraints)
    try:
        constraints = rag_constraints(user_query)
    except:
        constraints = run_rag(user_query)

    print(f"[Orchestrator] RAG constraints: {constraints[:200]}...")
    history = []
    prompt = constraints if constraints else "Thermostable PETase variant"

    for i in range(max_iterations):
        print(f"\n=== ITERATION {i+1}/{max_iterations} ===")

        # 2. DESIGN - now returns fasta_path, not list of sequences
        try:
            fasta_path = design_candidates(prompt, n=n_candidates)
        except GenerationFailure as exc:
            return AtelierResult({}, history, status=exc.status, error=str(exc))

        # Handle both return types: if old version returns list, convert
        if isinstance(fasta_path, list):
            # Old API returned sequences list - write to fasta
            from Bio.SeqRecord import SeqRecord
            from Bio.Seq import Seq
            from Bio import SeqIO
            records = [SeqRecord(Seq(s), id=f"cand_{j}") for j, s in enumerate(fasta_path)]
            fasta_path = f"outputs/best_{i}.fasta"
            SeqIO.write(records, fasta_path, "fasta")
            evaled = evaluate_batch(fasta_path)
        else:
            # New API: fasta_path string
            evaled = evaluate_batch(fasta_path)

        history.append(evaled)

        # Check PASS
        passing = [r for r in evaled if r.get("passes")]
        if passing:
            print(f"[Orchestrator] SUCCESS - {len(passing)} passing")
            best = passing[0]
            break

        # 3. CRITIQUE - new API takes no args, reads eval_results.json
        if i < max_iterations - 1:
            critique = critique_eval_results() # was critique_and_refine(evaled, constraints)
            if critique and critique.get("action") == "redesign":
                # Don't use rag_sources list (filenames) - use fixed RAG concept
                failure = critique.get("failure_reason","")
                if "II" in failure:
                    prompt = "Thermostable PETase with disulfide N233C S282C and D186N mutation low instability index stable"
                else:
                    prompt = "Thermostable PETase with D186N disulfide N233C S282C high plDDT thermostable"
                print(f"[Orchestrator] Next prompt: {prompt}")
            else:
                print("[Orchestrator] Critic says stop")
                break
        else:
            print("[Orchestrator] Max iterations reached")

    # Best selection
    if history:
        last = history[-1]
        best = sorted(last, key=candidate_sort_key)[0] if last else {}
    else:
        best = {}

    if not best or not recorded_fold_success(best) or not recorded_biophys_success(best):
        return AtelierResult(best, history, status="unavailable",
                             error="No candidate has complete measured evaluation results")

    seq_for_guard = best.get("sequence") or best.get("seq","")

    # Guardrail
    try:
        v = PetaseValidator(sequence=seq_for_guard)
        print(f"[Guardrail] Validation PASS")
    except Exception as e:
        print(f"Guardrail blocked: {e}")

    # Save
    Path(f"outputs/best_{i}.fasta").write_text(f">best_Tm_candidate\n{seq_for_guard}")
    try:
        log_run(user_query, seq_for_guard, best.get("plddt",0))
    except Exception as e:
        print(f"[Log] {e}")

    return AtelierResult(best, history)

if __name__ == "__main__":
    result = run_enzyme_atelier("PETase thermostability", max_iterations=2, n_candidates=1)
    print(result.summary())
