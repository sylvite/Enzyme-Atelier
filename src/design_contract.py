"""Reference-bound sequence transformations, independent of any reasoning model."""
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.evidence import EvidenceExcerpt

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data" / "references"
PROTECTED_POSITIONS = {160, 206, 237, 203, 239, 273, 289}
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


class Substitution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    position: int
    original: str
    replacement: str
    evidence_id: str
    quote: str


class DesignDecision(BaseModel):
    """All fields required for the strict Responses API JSON schema."""
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["retrieve", "revise", "stop"]
    reason: str
    query: str
    reference_accession: str
    substitutions: list[Substitution]


def load_reference():
    manifest = json.loads((REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    raw = (REFERENCE_DIR / "A0A0K8P6T7.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["record_sha256"]:
        raise ValueError("Reference record checksum mismatch")
    record = json.loads(raw)
    sequence = record["sequence"]["value"]
    if hashlib.sha256(sequence.encode()).hexdigest() != manifest["sequence_sha256"]:
        raise ValueError("Reference sequence checksum mismatch")
    if len(sequence) != 290 or any(sequence[p - 1] != aa for p, aa in {160: "S", 206: "D", 237: "H"}.items()):
        raise ValueError("Unexpected reference length or catalytic numbering")
    return {**manifest, "precursor_sequence": sequence, "sequence": sequence[27:],
            "protected_positions": sorted(PROTECTED_POSITIONS)}


def apply_substitutions(substitutions: list[Substitution], evidence: list[EvidenceExcerpt],
                        *, max_substitutions: int = 3) -> str:
    """Apply a complete variant relative to WT, never edits to an implicit parent.

    Citation checks establish traceability, not scientific entailment. Paper
    context and numbering correspondence must still be reviewed by a human.
    """
    reference = load_reference()
    if not 1 <= len(substitutions) <= max_substitutions:
        raise ValueError("Variant must have between one and the configured maximum substitutions")
    sources = {item.evidence_id: item for item in evidence}
    sequence = list(reference["sequence"])
    seen = set()
    for mutation in substitutions:
        position = mutation.position
        if not 28 <= position <= 290 or position in PROTECTED_POSITIONS:
            raise ValueError("Mutation outside mature chain or at a protected residue")
        if position in seen:
            raise ValueError("Duplicate mutation position")
        seen.add(position)
        if mutation.original not in AMINO_ACIDS or mutation.replacement not in AMINO_ACIDS:
            raise ValueError("Mutation must use single canonical amino acids")
        if reference["precursor_sequence"][position - 1] != mutation.original:
            raise ValueError("Mutation original residue does not match reference numbering")
        if mutation.original == mutation.replacement:
            raise ValueError("Mutation must change a residue")
        excerpt = sources.get(mutation.evidence_id)
        if excerpt is None or excerpt.source == "unknown" or excerpt.page is None:
            raise ValueError("Mutation needs a known source and page from this run's evidence")
        label = f"{mutation.original}{position}{mutation.replacement}"
        if (not mutation.quote.strip() or mutation.quote not in excerpt.text
                or not re.search(r"(?<![A-Za-z0-9])" + re.escape(label) + r"(?![A-Za-z0-9])", mutation.quote)):
            raise ValueError("Mutation needs an exact evidence quote containing its precursor-numbered label")
        sequence[position - 28] = mutation.replacement
    return "".join(sequence)


def validate_reference_candidate(row: dict) -> bool:
    """Reconstruct the candidate from recorded changes before selection/export."""
    try:
        reference = load_reference()
        if row.get("reference_sha256") != reference["sequence_sha256"]:
            return False
        mutations = [Substitution.model_validate(item) for item in row["substitutions"]]
        evidence = [EvidenceExcerpt.model_validate(item) for item in row["evidence"]]
        return row["sequence"] == apply_substitutions(mutations, evidence)
    except (ValueError, KeyError, TypeError):
        return False
