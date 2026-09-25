"""Traceable retrieval records; excerpts are evidence, not executable instructions."""
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    chunk_id: str
    source: str
    page: int | None = Field(default=None, ge=1)
    text: str

    @classmethod
    def from_chunk(cls, chunk_id: str, text: str, metadata: dict):
        source = metadata.get("source") or "unknown"
        page = metadata.get("page")
        if type(page) is not int or page < 1:
            page = None
        # Bind the citation to the content, not just a mutable database row ID.
        digest = hashlib.sha256(f"{source}\0{page}\0{text}".encode("utf-8")).hexdigest()
        return cls(evidence_id=digest, chunk_id=chunk_id, source=source, page=page, text=text)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    status: Literal["success", "empty", "unavailable"]
    excerpts: list[EvidenceExcerpt] = Field(default_factory=list)
    error: str = ""
