"""
Tool 1: ProGen2 generation wrapper - RESILIENT VERSION
Implements fallback chain + error handling for model registry drift
"""
from typing import List, Optional
from enum import StrEnum
from pydantic import BaseModel, Field


class ProGen2Input(BaseModel):
    prompt_sequence: str = Field(description="N-terminal prompt, e.g., catalytic triad context")
    max_length: int = Field(default=100, ge=10, le=350)
    temperature: float = Field(default=0.8, ge=0.1, le=1.5)
    num_return: int = Field(default=5, ge=1, le=20)
    model_id_override: Optional[str] = Field(default=None, description="Override for testing specific mirror")

class GenerationStatus(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"


class ProGen2Output(BaseModel):
    sequences: List[str]
    model_id: str
    success: bool
    error: str = ""
    status: GenerationStatus = GenerationStatus.UNAVAILABLE

# Legacy configured model candidates; availability and compatibility are not
# guaranteed. Loading another model is distinct from fabricating a sequence.
MODEL_FALLBACK_CHAIN: list[str] = [
    "Salesforce/progen2-small",
    "hugohrban/progen2-small",
    "hugohrban/progen2-base",
    "hugohrban/progen2-medium",
    "Profluent-Bio/progen3-112m",
    "Profluent-Bio/progen3-219m",
]

_model_cache = {}

def _load_model_with_fallback(preferred_id: Optional[str] = None):
    """
    Tries chain of models, returns first that loads.
    This is the resilience pattern for model registry drift.
    """
    from transformers import AutoTokenizer, AutoModelForCausalLM
    import os

    # Build try list: preferred first, then chain without duplicates
    try_list = []
    if preferred_id:
        try_list.append(preferred_id)
    for mid in MODEL_FALLBACK_CHAIN:
        if mid not in try_list:
            try_list.append(mid)

    last_error = None
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        print(f"[HF] Token detected")
    else:
        print("[HF] WARNING: No HF_TOKEN in env - using anonymous")
    for model_id in try_list:
        # Use cache if already loaded
        if model_id in _model_cache:
            print(f"[ProGen2] Using cached {model_id}")
            return _model_cache[model_id][0], _model_cache[model_id][1], model_id

        try:
            print(f"[ProGen2] Attempting to load {model_id}...")
            tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
            model.eval()
            _model_cache[model_id] = (model, tokenizer)
            print(f"[ProGen2] Successfully loaded {model_id}")
            return model, tokenizer, model_id
        except Exception as e:
            last_error = e
            print(f"[ProGen2] Failed {model_id}: {str(e)[:300]}")
            continue

    raise RuntimeError(f"All ProGen2 fallbacks exhausted. Last error: {last_error}")

def progen2_generate(inp: ProGen2Input) -> ProGen2Output:
    """
    Generates protein sequences with automatic fallback.
    Unavailable inference returns no sequences. Invalid decoded batches are
    rejected intact rather than silently repaired or replaced with padding.
    """
    used_id = ""
    try:
        model, tokenizer, used_id = _load_model_with_fallback(inp.model_id_override)
        import torch
        inputs = tokenizer(inp.prompt_sequence, return_tensors="pt")
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=len(inp.prompt_sequence) + inp.max_length,
                do_sample=True,
                temperature=inp.temperature,
                num_return_sequences=inp.num_return,
                pad_token_id=tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 0
            )
        seqs = [tokenizer.decode(o, skip_special_tokens=True) for o in outputs]
        if len(seqs) != inp.num_return or any(
            not seq or set(seq) - set("ACDEFGHIKLMNPQRSTVWY") for seq in seqs
        ):
            return ProGen2Output(
                sequences=[], model_id=used_id, success=False,
                status=GenerationStatus.INVALID_OUTPUT,
                error="Model returned an empty, noncanonical, or incomplete sequence batch",
            )
        return ProGen2Output(sequences=seqs, model_id=used_id, success=True,
                             status=GenerationStatus.SUCCESS)
    except Exception as e:
        return ProGen2Output(sequences=[], model_id=used_id, success=False,
                             status=GenerationStatus.UNAVAILABLE,
                             error=f"{type(e).__name__}: {e}"[:500])
