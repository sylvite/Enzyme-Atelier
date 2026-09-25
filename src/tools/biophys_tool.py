"""BioPython measurements with explicit failure status and no numeric substitutes."""
import math
from typing import Literal

from pydantic import BaseModel, Field


class BioPhysInput(BaseModel):
    sequence: str = Field(description="Unmodified canonical amino-acid sequence")


class BioPhysOutput(BaseModel):
    ii: float | None = None
    molecular_weight: float | None = None
    gravy: float | None = None
    is_stable: bool | None = None
    success: bool = False
    status: Literal["success", "invalid_input", "unavailable"] = "unavailable"
    source: str = "biopython"
    error: str = ""


def calc_biophysics(inp: BioPhysInput) -> BioPhysOutput:
    """Calculate all metrics for the exact input, or return no measurements.

    Alphabet/length errors are distinct from library/calculation failures.
    No normalization, residue deletion, manual approximation, or constants are
    used to conceal a failed calculation. These metrics do not validate PETase
    identity, catalytic residues, or experimental thermostability.
    """
    seq = inp.sequence
    if len(seq) < 10 or set(seq) - set("ACDEFGHIKLMNPQRSTVWY"):
        return BioPhysOutput(status="invalid_input", error="Expected at least 10 canonical uppercase amino acids")
    try:
        from Bio.SeqUtils.ProtParam import ProteinAnalysis
        analysis = ProteinAnalysis(seq)
        ii = float(analysis.instability_index())
        mw = float(analysis.molecular_weight())
        gravy = float(analysis.gravy())
        if not all(math.isfinite(value) for value in (ii, mw, gravy)) or mw <= 0:
            raise ValueError("Non-finite metrics or nonpositive molecular weight")
        return BioPhysOutput(ii=ii, molecular_weight=mw, gravy=gravy,
                             is_stable=ii < 40, success=True, status="success")
    except Exception as exc:
        return BioPhysOutput(error=f"{type(exc).__name__}: {exc}"[:500])


def calc_instability(sequence: str) -> dict:
    """Expose the legacy metric names while retaining measurement provenance."""
    result = calc_biophysics(BioPhysInput(sequence=sequence)).model_dump()
    result["mw"] = result.pop("molecular_weight")
    return result
