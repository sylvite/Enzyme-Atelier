"""
ProGen2 generation with a pinned model and explicit failure results.
"""
from typing import List
from enum import StrEnum
from pydantic import BaseModel, Field


class ProGen2Input(BaseModel):
    prompt_sequence: str = Field(description="N-terminal amino-acid sequence prefix")
    max_length: int = Field(default=100, ge=10, le=350, description="Maximum new sequence tokens")
    temperature: float = Field(default=0.8, ge=0.1, le=1.5)
    num_return: int = Field(default=5, ge=1, le=20)

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

MODEL_ID = "hugohrban/progen2-small"
MODEL_REVISION = "43237a0b733c6629226a079266d2985c9fdce9b7"
MODEL_REFERENCE = f"{MODEL_ID}@{MODEL_REVISION}"
_model_cache = {}


def _load_model():
    """Load only the supported revision; remote Python code is revision-pinned."""
    from huggingface_hub import hf_hub_download
    from transformers import AutoModelForCausalLM, PreTrainedTokenizerFast

    if MODEL_REFERENCE not in _model_cache:
        tokenizer_path = hf_hub_download(MODEL_ID, "tokenizer.json", revision=MODEL_REVISION)
        # This repository supplies tokenizer.json, not GPT2 vocab/merges files.
        # ProGen's forward sequence delimiters are 1 and 2.
        tokenizer = PreTrainedTokenizerFast(
            tokenizer_file=tokenizer_path, bos_token="1", eos_token="2", pad_token="<|pad|>",
            model_input_names=["input_ids", "attention_mask"],
            clean_up_tokenization_spaces=False,
        )
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, code_revision=MODEL_REVISION,
            trust_remote_code=True, use_safetensors=True,
        )
        model.eval()
        _model_cache[MODEL_REFERENCE] = (model, tokenizer)
    model, tokenizer = _model_cache[MODEL_REFERENCE]
    return model, tokenizer, MODEL_REFERENCE


def progen2_generate(inp: ProGen2Input) -> ProGen2Output:
    """
    Generates protein sequences with the supported model revision.
    Unavailable inference returns no sequences. Invalid decoded batches are
    rejected intact rather than silently repaired or replaced with padding.
    """
    used_id = MODEL_REFERENCE
    try:
        model, tokenizer, used_id = _load_model()
        import torch
        inputs = tokenizer("1" + inp.prompt_sequence, return_tensors="pt", add_special_tokens=False)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=inp.max_length,
                eos_token_id=tokenizer.eos_token_id,
                do_sample=True,
                temperature=inp.temperature,
                num_return_sequences=inp.num_return,
                pad_token_id=tokenizer.pad_token_id
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
