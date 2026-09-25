"""Generate candidates without inventing residues when generation fails."""
from dataclasses import dataclass

from src.tools.progen2_tool import progen2_generate, ProGen2Input, GenerationStatus


class GenerationFailure(RuntimeError):
    """A generation attempt cannot supply a valid candidate batch."""
    def __init__(self, status: str, error: str, model_id: str = ""):
        super().__init__(error)
        self.status = status
        self.model_id = model_id


@dataclass(frozen=True)
class CandidateBatch:
    """Generation handoff with no dependency on an output file."""
    sequences: tuple[str, ...]
    model_id: str
    prompt: str


def generate_candidates(prompt: str, n: int = 10) -> CandidateBatch:
    """Return an unchanged, validated model batch; do not write artifacts."""
    inp = ProGen2Input(prompt_sequence="MNFPRASRLM", max_length=280, num_return=n)
    out = progen2_generate(inp)
    if not out.success or out.status != GenerationStatus.SUCCESS:
        status = "invalid_output" if out.status == GenerationStatus.INVALID_OUTPUT else "unavailable"
        raise GenerationFailure(status, out.error or "Generation did not succeed", out.model_id)
    if len(out.sequences) != n:
        raise GenerationFailure("invalid_output", "Generation returned an incomplete batch", out.model_id)
    try:
        sequences = tuple(validate_generated_sequence(seq) for seq in out.sequences)
    except ValueError as exc:
        raise GenerationFailure("invalid_output", str(exc), out.model_id) from exc
    return CandidateBatch(sequences, out.model_id, prompt)


def validate_generated_sequence(seq: str) -> str:
    """Validate length and alphabet without editing the generated sequence."""
    if not 240 <= len(seq) <= 320:
        raise ValueError(f"Generated sequence length {len(seq)} outside 240-320")
    if set(seq) - set("ACDEFGHIKLMNPQRSTVWY"):
        raise ValueError("Generated sequence contains noncanonical amino acids")
    return seq
