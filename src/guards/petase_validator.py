"""
Guardrails + Human-in-the-Loop
"""
from pydantic import BaseModel, validator
import re

class PetaseValidator(BaseModel):
    sequence: str
    human_approved: bool = False

    @validator("sequence")
    def check_length(cls, v):
        # Task 6: PETase 290 AA, guardrail 240-320 (was 50-400 too loose)
        # Matches your 121->290 cleaning fix and console3 290 AA PASS
        if not 240 <= len(v) <= 320:
            raise ValueError(f"Length {len(v)} outside allowed 240-320 (PETase), got {len(v)}")
        if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]+", v):
            raise ValueError("Invalid amino acids")
        return v

    def needs_human_review(self):
        # Trigger HITL before export
        return True

def human_approval_gate(seq: str) -> bool:
    print(f"\n[HITL] Final candidate length {len(seq)} ready for export.")
    print("First 60 aa:", seq[:60])
    ans = input("Approve export to outputs/? (y/n): ").strip().lower()
    return ans == "y"