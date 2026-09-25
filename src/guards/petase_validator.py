"""
Guardrails + Human-in-the-Loop
"""
from pydantic import BaseModel, field_validator
import re

class PetaseValidator(BaseModel):
    sequence: str

    @field_validator("sequence")
    @classmethod
    def check_length(cls, v):
        # Screening bounds only; these do not establish enzyme identity.
        if not 240 <= len(v) <= 320:
            raise ValueError(f"Length {len(v)} outside allowed 240-320 (PETase), got {len(v)}")
        if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]+", v):
            raise ValueError("Invalid amino acids")
        return v

def human_approval_gate(seq: str) -> bool:
    print(f"\n[HITL] Final candidate length {len(seq)} ready for export.")
    print("Sequence:", seq)
    ans = input("Approve final export for this candidate? (y/n): ").strip().lower()
    return ans == "y"
