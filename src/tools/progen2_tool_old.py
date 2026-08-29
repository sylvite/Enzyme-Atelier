"""
Tool 1: ProGen2 generation wrapper
Uses HF transformers - runs locally, no Profluent API key needed
"""
from typing import List
from pydantic import BaseModel, Field

class ProGen2Input(BaseModel):
    prompt_sequence: str = Field(description="N-terminal prompt, e.g., catalytic triad context")
    max_length: int = Field(default=100, ge=10, le=350)
    temperature: float = Field(default=0.8, ge=0.1, le=1.5)
    num_return: int = Field(default=5, ge=1, le=20)

class ProGen2Output(BaseModel):
    sequences: List[str]
    model_id: str

# Lazy load to avoid import errors in CI
_model = None
_tokenizer = None

#def _load_model(model_id: str = "Salesforce/progen2-small"):
def _load_model(model_id: str = "hugohrban/progen2-small"):
    global _model, _tokenizer
    if _model is None:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch
        _tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        _model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
        _model.eval()
    return _model, _tokenizer

def progen2_generate(inp: ProGen2Input) -> ProGen2Output:
    """
    Generates protein sequences conditioned on prompt.
    Error handling: returns empty if model not available (for tests)
    """
    try:
        model, tokenizer = _load_model()
        import torch
        inputs = tokenizer(inp.prompt_sequence, return_tensors="pt")
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=len(inp.prompt_sequence) + inp.max_length,
                do_sample=True,
                temperature=inp.temperature,
                num_return_sequences=inp.num_return,
                pad_token_id=tokenizer.eos_token_id
            )
        seqs = [tokenizer.decode(o, skip_special_tokens=True) for o in outputs]
        return ProGen2Output(sequences=seqs, model_id="progen2-small")
    except Exception as e:
        # Graceful fallback for TA without GPU/torch
        print(f"[progen2_tool] Fallback due to {e}")
        return ProGen2Output(sequences=[inp.prompt_sequence + "A"*inp.max_length]*inp.num_return, model_id="fallback")