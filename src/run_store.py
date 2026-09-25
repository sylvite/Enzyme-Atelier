"""Run-local storage. No shared candidate files or latest-run pointer."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.memory.episodic_store import append_record
from src.run_models import AtelierResult, RunConfig


def write_json(path: Path, value):
    """Replace a JSON document atomically after serialization succeeds."""
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record_event(run_dir: Path, event: str, **details):
    """Record a decision or tool boundary with its associated run identity."""
    append_record(Path(run_dir) / "events.jsonl", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": Path(run_dir).name, "event": event, **details,
    })


def create_run(config: RunConfig, output_root: Path) -> AtelierResult:
    """Allocate an exclusive UUID directory, even for concurrent invocations."""
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    directory = root / run_id
    directory.mkdir(exist_ok=False)
    result = AtelierResult(run_id=run_id, run_dir=directory, config=config)
    write_json(directory / "config.json", config.model_dump())
    record_event(directory, "run_started", config=config.model_dump())
    save_result(result)
    return result


def save_result(result: AtelierResult):
    """Persist the full checkpoint and a compact factual summary."""
    write_json(result.run_dir / "result.json", result.model_dump(mode="json"))
    best = result.best
    write_json(result.run_dir / "final_summary.json", {
        "run_id": result.run_id, "status": result.status,
        "mode": result.config.mode, "simulation": result.config.simulation,
        "error": result.error, "stop_reason": result.stop_reason,
        "screening_passes": bool(best.get("eligible", False)),
        "approval": result.approval, "exported_files": result.exported_files,
        "candidate_id": best.get("candidate_id"),
        "final_ii": best.get("ii"), "final_plddt": best.get("plddt"),
        "fold_status": best.get("fold_status", "not_run"),
        "biophys_status": best.get("biophys_status", "not_run"),
        "iterations_evaluated": len(result.history),
        "candidates_evaluated": sum(map(len, result.history)),
    })


def load_result(run_dir: Path) -> AtelierResult:
    """Load an explicitly selected run; never guess from shared output files."""
    directory = Path(run_dir).resolve()
    result = AtelierResult.model_validate_json((directory / "result.json").read_text(encoding="utf-8"))
    if result.run_id != directory.name:
        raise ValueError("Run identity does not match its directory")
    result.run_dir = directory
    return result
