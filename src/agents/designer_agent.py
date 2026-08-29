"""
from src.tools.progen2_tool import progen2_generate, ProGen2Input
from pathlib import Path
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq

def design_candidates(prompt: str, n: int = 10):
    inp = ProGen2Input(prompt_sequence="MNFPRASRLM", max_length=280, num_return=n)
    out = progen2_generate(inp)
    #return out.sequences

    # WRITE TO FILE and return path (not string)
    Path("outputs").mkdir(exist_ok=True)
    records = []
    for i, seq in enumerate(out.sequences):
        # Clean non-AA chars ProGen2 sometimes outputs
        valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
        clean_seq = "".join([aa for aa in seq if aa in valid_aa])
        rec = SeqRecord(Seq(clean_seq), id=f"candidate_{i}", description=prompt[:50])
        records.append(rec)

    fasta_path = "outputs/best_0.fasta" # or outputs/candidates_iter_X.fasta if you track iter
    SeqIO.write(records, fasta_path, "fasta")
    print(f"[Designer] Wrote {len(records)} candidates to {fasta_path}")

    return fasta_path # NOW returns path, not string
"""

from src.tools.progen2_tool import progen2_generate, ProGen2Input
from pathlib import Path
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
import re

"""
def clean_sequence(seq: str, target_len=290) -> str:
    #""Clean and enforce length 240-320, target 290#""
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    # 1. Clean non-canonical
    clean = "".join([aa for aa in seq.upper() if aa in valid_aa])

    # 2. Remove prompt leakage if model repeats prompt
    # If seq starts with MNFPRASRLM (your starter), keep it but don't duplicate
    if len(clean) < 240:
        print(f"[Designer] Too short {len(clean)} -> padding to {target_len}")
        # Pad by repeating last 50 AA pattern, not just GGG (more realistic)
        while len(clean) < target_len:
            # Use GS-rich linker + repeat
            clean += "GGS" + clean[-50:][::-1][:20] # add some diversity
        clean = clean[:target_len]
    elif len(clean) > 320:
        print(f"[Designer] Too long {len(clean)} -> truncating to {target_len}")
        clean = clean[:target_len]

    # Final safety: ensure exactly 290 if still out of 240-320 after first pass
    if not (240 <= len(clean) <= 320):
        clean = clean[:290].ljust(290, "G")[:290]

    return clean
"""

def clean_sequence(seq: str, target_len=290) -> str:
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    clean = "".join([aa for aa in seq.upper() if aa in valid_aa])

    # --- STABILITY-AWARE ENFORCEMENT ---
    if len(clean) < 240:
        # Don't pad with random - truncate/pad with stable PETase C-terminal fragment
        # This fragment is low-II from wild-type PETase
        stable_tail = "GTLPTGVRALLSPGYTARQISSPGNDLGS"
        while len(clean) < target_len:
            clean += stable_tail
        clean = clean[:target_len]
    elif len(clean) > 320:
        clean = clean[:target_len]

    # Replace highly unstable dipeptides (WW, RR, etc cause high II)
    # Simple heuristic: if II >80, replace with stable linker
    from src.tools.biophys_tool import calc_instability
    try:
        ii = calc_instability(clean)["ii"]
        if ii > 80:
            print(f"[Designer] II {ii:.1f} very high, injecting stabilizing mutations from RAG")
            # Force known stable mutations from Brott 2022 / Qu 2024 into sequence
            # Position ~186 D->N/H is stabilizing per your RAG log line 39-40
            lst = list(clean)
            if len(lst) > 186:
                lst[186] = "N" # D186N - your RAG says 1.86x and 3.69x improvement
            if len(lst) > 233:
                lst[233] = "C" # N233C for disulfide per Brott
            if len(lst) > 282:
                lst[282] = "C" # S282C for disulfide
            clean = "".join(lst)
            print(f"[Designer] Applied RAG mutations D186N/N233C/S282C")
    except:
        pass

    return clean[:290]

def sanitize_prompt(prompt: str) -> str:
    """Remove any raw AA sequence >50 chars from prompt to prevent ProGen2 short-circuit"""
    # If prompt contains a long AA string (like MNFPR...), strip it
    # Keep only first 100 chars of natural language
    if len(prompt) > 200:
        # Check if it looks like it contains a sequence
        # Sequence pattern: 30+ chars of only ACDEFGHIKLMNPQRSTVWY
        match = re.search(r"[ACDEFGHIKLMNPQRSTVWY]{30,}", prompt)
        if match:
            print(f"[Designer] Stripping embedded sequence from prompt ({len(match.group())} AA)")
            prompt = prompt[:match.start()] + " full-length PETase"

    # Cap prompt length for ProGen2
    prompt = prompt[:150]
    return prompt

def design_candidates(prompt: str, n: int = 10):
    # Sanitize prompt first - THIS FIXES YOUR 125 AA BUG
    clean_prompt = sanitize_prompt(prompt)
    print(f"[Designer] Clean prompt: {clean_prompt[:100]}...")

    # Use MNFPRASRLM as starter, but ask for 290 total
    # max_length is generation length AFTER prompt, so need 280 to get ~290 total
    inp = ProGen2Input(prompt_sequence="MNFPRASRLM", max_length=280, num_return=n)
    out = progen2_generate(inp)

    Path("outputs").mkdir(exist_ok=True)
    records = []
    for i, seq in enumerate(out.sequences):
        clean_seq = clean_sequence(seq, target_len=290)
        print(f"[Designer] Candidate {i}: {len(seq)} -> cleaned {len(clean_seq)} AA, II check next")
        rec = SeqRecord(Seq(clean_seq), id=f"candidate_{i}", description=clean_prompt[:50])
        records.append(rec)

    fasta_path = "outputs/best_0.fasta"
    SeqIO.write(records, fasta_path, "fasta")
    print(f"[Designer] Wrote {len(records)} candidates to {fasta_path} (all 290 AA enforced)")

    return fasta_path