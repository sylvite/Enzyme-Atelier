"""ESM Atlas folding with explicit unavailable results and bounded requests."""

import math
import time

import requests
from Bio.SeqUtils import seq1
from pydantic import BaseModel


class ESMFoldInput(BaseModel):
    sequence: str


class ESMFoldOutput(BaseModel):
    pdb: str = ""
    plddt: float | None = None
    success: bool = False
    status: str = "unavailable"
    error: str = ""
    attempts: int = 0
    source: str = "esm_atlas"
    requested_length: int = 0
    folded_length: int = 0
    plddt_scale: int = 100


def _parse_prediction(pdb: str, sequence: str, plddt_scale: int) -> float:
    """Validate monomer coverage and average atom confidence on a 0-100 scale.

    ESM's documented PDB convention uses 0-100 B-factors. A provider using
    0-1 must be explicitly configured; low scores are never auto-rescaled.
    """
    scores = []
    residues = {}
    alpha_carbons = set()
    for line in pdb.splitlines():
        if not line.startswith("ATOM  "):
            continue
        try:
            score = float(line[60:66])
            coordinates = [float(line[a:b]) for a, b in ((30, 38), (38, 46), (46, 54))]
            int(line[22:26])
        except ValueError as exc:
            raise ValueError("Malformed PDB atom record") from exc
        if not all(math.isfinite(value) for value in [score, *coordinates]):
            raise ValueError("Non-finite PDB value")
        if not 0 <= score <= plddt_scale:
            raise ValueError("Confidence outside configured scale")
        key = (line[21:22], line[22:27])
        residue = seq1(line[17:20])
        if key in residues and residues[key] != residue:
            raise ValueError("Conflicting PDB residue identities")
        residues[key] = residue
        if line[12:16].strip() == "CA":
            if key in alpha_carbons:
                raise ValueError("Duplicate PDB alpha carbon")
            alpha_carbons.add(key)
        scores.append(score * (100 / plddt_scale))
    if not scores:
        raise ValueError("No PDB atom confidence records")
    if len({key[0] for key in residues}) != 1:
        raise ValueError("Expected a single-chain prediction")
    if set(residues) != alpha_carbons or "".join(residues.values()) != sequence:
        raise ValueError("Prediction does not cover the requested sequence")
    return sum(scores) / len(scores)


def esmfold_fold(sequence: str, max_retries=3, *, plddt_scale=100):
    """Fold the full sequence; max_retries is the total attempt budget.

    Failures have no measurement (plddt=None). Retry HTTP 429/5xx, transport
    errors, and invalid predictions, sleeping only between attempts.
    """
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 1:
        raise ValueError("max_retries must be a positive integer")
    if plddt_scale not in (1, 100):
        raise ValueError("plddt_scale must be 1 or 100")
    result = ESMFoldOutput(requested_length=len(sequence), plddt_scale=plddt_scale)
    if not sequence or set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"):
        result.error = "Expected a nonempty canonical amino-acid sequence"
        return result.model_dump()

    for attempt in range(1, max_retries + 1):
        result.attempts = attempt
        retryable = True
        try:
            response = requests.post(
                "https://api.esmatlas.com/foldSequence/v1/pdb/",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=sequence,
                timeout=120,
            )
            if response.status_code == 200:
                score = _parse_prediction(response.text, sequence, plddt_scale)
                result.plddt = score
                result.pdb = response.text
                result.success = True
                result.status = "success"
                result.error = ""
                result.folded_length = len(sequence)
                return result.model_dump()
            result.error = f"HTTP {response.status_code}"
            retryable = response.status_code == 429 or 500 <= response.status_code < 600
        except (requests.RequestException, ValueError) as exc:
            result.error = str(exc)
        if not retryable or attempt == max_retries:
            break
        time.sleep(5)
    return result.model_dump()
