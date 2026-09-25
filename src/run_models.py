"""Validated run settings and the persisted backend result contract."""
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunConfig(BaseModel):
    """Validate settings before creating artifacts or calling a tool."""
    model_config = ConfigDict(extra="forbid")
    query: str
    max_iterations: int = Field(default=2, ge=1, strict=True)
    n_candidates: int = Field(default=1, ge=1, le=20, strict=True)
    mode: Literal["progen2", "reference"] = "progen2"
    max_actions: int = Field(default=8, ge=1, le=30, strict=True)
    max_retrievals: int = Field(default=3, ge=1, le=10, strict=True)
    planner_model: str = ""
    simulation: bool = False

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


RunStatus = Literal[
    "running", "pending_review", "approved", "rejected", "no_candidate",
    "unavailable", "invalid_output", "failed", "cancelled",
]


class AtelierResult(BaseModel):
    """One run's state; screening passage and export approval are separate."""
    run_id: str
    run_dir: Path
    config: RunConfig
    status: RunStatus = "running"
    error: str = ""
    stop_reason: str = ""
    best: dict[str, Any] = Field(default_factory=dict)
    history: list[list[dict[str, Any]]] = Field(default_factory=list)
    approval: Literal["not_requested", "pending", "approved", "rejected"] = "not_requested"
    exported_files: list[str] = Field(default_factory=list)

    def summary(self):
        """A concise CLI-friendly outcome with the exact artifact location."""
        message = f"Run {self.run_id}: {self.status} | {self.run_dir}"
        if self.config.simulation:
            message = "SYNTHETIC TEST | " + message
        if self.best:
            message += f" | best={self.best.get('candidate_id')} pLDDT={self.best.get('plddt')} II={self.best.get('ii')}"
        if self.error:
            message += f" | {self.error}"
        return message
