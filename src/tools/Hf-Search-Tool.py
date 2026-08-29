"""
Tool: HuggingFace Model Search - for self-healing when models disappear
Uses HF Hub API, no token needed for search
"""
import requests
from pydantic import BaseModel
from typing import List

class HFSearchInput(BaseModel):
    query: str = Field(description="e.g., progen2-small, progen3")
    limit: int = Field(default=5, ge=1, le=10)

class HFModelInfo(BaseModel):
    model_id: str
    downloads: int
    likes: int
    author: str

class HFSearchOutput(BaseModel):
    models: List[HFModelInfo]
    success: bool
    error: str = ""

def search_hf_models(inp: HFSearchInput) -> HFSearchOutput:
    """
    Searches HuggingFace Hub for model mirrors.
    Agent calls this when primary model 404s.
    """
    try:
        url = f"https://huggingface.co/api/models?search={inp.query}&sort=downloads&direction=-1&limit={inp.limit}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return HFSearchOutput(models=[], success=False, error=f"HF API {resp.status_code}")
        data = resp.json()
        models = []
        for m in data[:inp.limit]:
            models.append(HFModelInfo(
                model_id=m.get("modelId",""),
                downloads=m.get("downloads",0),
                likes=m.get("likes",0),
                author=m.get("modelId","").split("/")[0] if "/" in m.get("modelId","") else ""
            ))
        return HFSearchOutput(models=models, success=True)
    except Exception as e:
        return HFSearchOutput(models=[], success=False, error=str(e))

# Example of ReAct recovery pattern for orchestrator
RECOVERY_PROMPT = """
If progen2_generate returns success=False and error contains 'not found' or '404':
1. Call search_hf_models with query='progen2'
2. Pick model with highest downloads that is not Salesforce/*
3. Retry progen2_generate with model_id_override = that model
"""