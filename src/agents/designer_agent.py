"""Generate candidates without inventing residues when generation fails."""
import json
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from src.tools.progen2_tool import progen2_generate, ProGen2Input, GenerationStatus


class GenerationFailure(RuntimeError):
    """A generation attempt cannot supply a valid candidate batch."""
    def __init__(self, status: str, error: str, model_id: str = ""):
        super().__init__(error)
        self.status = status
        self.model_id = model_id


def record_generation_failure(failure: GenerationFailure):
    """Invalidate current result files so a stopped run cannot reuse old scores.

    Historical FASTA files remain untouched; callers must stop on the exception.
    Per-run artifact isolation will replace these shared files in Step 2B.
    """
    Path("outputs").mkdir(exist_ok=True)
    result = {"generation_status": failure.status, "generation_error": str(failure),
              "generation_model": failure.model_id, "passes": False,
              "final_ii": None, "final_plddt": None, "esmfold_status": "not_run",
              "biophys_status": "not_run", "candidate_count": 0}
    Path("outputs/generation_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    Path("outputs/final_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    Path("outputs/eval_results.json").write_text("[]", encoding="utf-8")
    Path("outputs/critique.json").write_text(json.dumps({
        "action": "stop", "reason": "Generation failed: " + str(failure), "rag_sources": []
    }, indent=2), encoding="utf-8")


def clean_sequence(seq: str, target_len=290) -> str:
    """Legacy name: validate and return unchanged; never pad, truncate or mutate.

    target_len is retained for caller compatibility, not enforced by editing.
    The current application's accepted length window remains 240-320 residues.
    """
    if not 240 <= len(seq) <= 320:
        raise ValueError(f"Generated sequence length {len(seq)} outside 240-320")
    if set(seq) - set("ACDEFGHIKLMNPQRSTVWY"):
        raise ValueError("Generated sequence contains noncanonical amino acids")
    return seq


def design_candidates(prompt: str, n: int = 10):
    """Write only a completely valid, successful generation batch to FASTA.

    Natural-language constraints are metadata only until the orchestration
    redesign supplies a genuine conditioning strategy for the sequence model.
    """
    inp = ProGen2Input(prompt_sequence="MNFPRASRLM", max_length=280, num_return=n)
    out = progen2_generate(inp)
    try:
        if not out.success or out.status != GenerationStatus.SUCCESS:
            status = "invalid_output" if out.status == GenerationStatus.INVALID_OUTPUT else "unavailable"
            raise GenerationFailure(status, out.error or "Generation did not succeed", out.model_id)
        if len(out.sequences) != n:
            raise GenerationFailure("invalid_output", "Generation returned an incomplete batch", out.model_id)
        sequences = [clean_sequence(seq) for seq in out.sequences]
    except ValueError as exc:
        failure = GenerationFailure("invalid_output", str(exc), out.model_id)
        record_generation_failure(failure)
        raise failure from exc
    except GenerationFailure as failure:
        record_generation_failure(failure)
        raise

    Path("outputs").mkdir(exist_ok=True)
    description = " ".join(prompt.split())[:50]
    records = [SeqRecord(Seq(seq), id=f"candidate_{i}", description=description)
               for i, seq in enumerate(sequences)]
    fasta_path = "outputs/best_0.fasta"
    SeqIO.write(records, fasta_path, "fasta")
    Path("outputs/generation_result.json").write_text(json.dumps({
        "generation_status": "success", "generation_model": out.model_id,
        "generation_error": "", "candidate_count": len(sequences),
    }, indent=2), encoding="utf-8")
    print(f"[Designer] Wrote {len(records)} unmodified generated candidates to {fasta_path}")
    return fasta_path
