"""Background UI jobs with per-session ownership and idempotent submission."""
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal
from uuid import uuid4
import json
import os

from pydantic import BaseModel, ConfigDict, Field

from src.agents.orchestrator import run_enzyme_atelier
from src.agents.planner_agent import OpenAIPlanner
from src.run_models import RunConfig
from src.run_store import load_result


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["demo", "reference", "progen2"] = "demo"
    query: str = "Find evidence-backed PETase stability variants"
    max_iterations: int = Field(default=2, ge=1, le=10, strict=True)
    n_candidates: int = Field(default=1, ge=1, le=20, strict=True)
    max_actions: int = Field(default=8, ge=1, le=30, strict=True)
    max_retrievals: int = Field(default=3, ge=1, le=10, strict=True)
    model: str = ""
    api_enabled: bool = False

    def check_ready(self):
        RunConfig(query=self.query, max_iterations=self.max_iterations, n_candidates=self.n_candidates)
        if self.mode == "reference":
            if not self.api_enabled:
                raise ValueError("Enable paid planner calls before starting reference design.")
            if not self.model.strip() or not os.getenv("OPENAI_API_KEY", "").strip():
                raise ValueError("Set OPENAI_API_KEY in .env and enter an OpenAI model ID.")
            if self.n_candidates != 1:
                raise ValueError("Reference design evaluates one variant per iteration.")


@dataclass
class Job:
    owner: str
    token: str
    request: JobRequest
    output_root: Path
    job_id: str = field(default_factory=lambda: uuid4().hex)
    cancel: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)
    run_dir: Path | None = None
    error: str = ""


class JobManager:
    """Workers never call Streamlit or mutate its session state."""
    def __init__(self, output_root="outputs/runs/ui"):
        self.output_root = Path(output_root).resolve()
        self._jobs = {}
        self._submissions = {}
        self._lock = Lock()

    def start(self, owner: str, token: str, request: JobRequest) -> str:
        if not owner or not token:
            raise ValueError("Missing session or submission identity")
        with self._lock:
            prior = self._submissions.get((owner, token))
            if prior:
                if self._jobs[prior].request != request:
                    raise ValueError("A submitted request cannot be changed; prepare a new run.")
                return prior
            request.check_ready()
            if any(job.owner == owner and not job.done.is_set() for job in self._jobs.values()):
                raise ValueError("This session already has a running job.")
            if sum(not job.done.is_set() for job in self._jobs.values()) >= 2:
                raise ValueError("Two jobs are already running. Wait for one to finish.")
            job = Job(owner=owner, token=token, request=request, output_root=self.output_root / uuid4().hex)
            self._jobs[job.job_id] = job
            self._submissions[owner, token] = job.job_id
            Thread(target=self._execute, args=(job,), daemon=True, name=f"atelier-{job.job_id[:8]}").start()
            return job.job_id

    def _execute(self, job):
        try:
            request = job.request
            if request.mode == "demo":
                from eval.design_scenarios import run_case
                result = run_case("low_confidence_revision", job.output_root, cancel_requested=job.cancel.is_set)
            else:
                planner = OpenAIPlanner(request.model) if request.mode == "reference" else None
                result = run_enzyme_atelier(
                    request.query, max_iterations=request.max_iterations, n_candidates=request.n_candidates,
                    output_root=job.output_root, mode=request.mode, planner=planner,
                    max_actions=request.max_actions, max_retrievals=request.max_retrievals,
                    cancel_requested=job.cancel.is_set,
                )
            job.run_dir = result.run_dir
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.done.set()

    def _owned(self, owner, job_id):
        job = self._jobs.get(job_id)
        if job is None or job.owner != owner:
            raise ValueError("Job is not available in this session")
        return job

    def cancel(self, owner, job_id):
        with self._lock:
            job = self._owned(owner, job_id)
            if not job.done.is_set():
                job.cancel.set()

    def snapshot(self, owner, job_id):
        with self._lock:
            job = self._owned(owner, job_id)
            directory = job.run_dir
            if directory is None and job.output_root.exists():
                records = list(job.output_root.glob("*/result.json"))
                directory = records[0].parent if len(records) == 1 else None
            return {"job_id": job_id, "done": job.done.is_set(), "error": job.error,
                    "cancel_requested": job.cancel.is_set(), "run_dir": directory}


def read_events(run_dir):
    """Read complete JSONL lines; an in-flight final line is not an error."""
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def saved_runs(root="outputs/runs"):
    """Discover saved runs only; listing must never execute or resume tools."""
    rows = []
    for path in Path(root).glob("**/result.json"):
        try:
            result = load_result(path.parent)
            rows.append((path.stat().st_mtime, result))
        except (OSError, ValueError):
            continue
    return [result for _, result in sorted(rows, key=lambda pair: pair[0], reverse=True)]
