"""Shared orchestration for the CLI, evaluation harness, and future UI."""
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from pydantic import ValidationError

from src.agents.rag_agent import rag_constraints
from src.agents.designer_agent import generate_candidates, GenerationFailure
from src.agents.evaluator_agent import (
    evaluate_one, candidate_sort_key, recorded_fold_success, recorded_biophys_success,
)
from src.agents.critic_agent import critique_results
from src.guards.petase_validator import PetaseValidator
from src.memory.episodic_store import log_run
from src.run_models import AtelierResult, RunConfig
from src.run_store import create_run, write_json, record_event, save_result, load_result


ApprovalCallback = Callable[[str], bool | None]


def candidate_is_eligible(candidate: dict) -> bool:
    """Recheck actual values and sequence validity; never trust a PASS label alone."""
    try:
        sequence = PetaseValidator(sequence=candidate.get("sequence", "")).sequence
    except ValidationError:
        return False
    if candidate.get("design_mode") == "reference":
        from src.design_contract import validate_reference_candidate
        if not validate_reference_candidate(candidate):
            return False
    return (
        recorded_fold_success(candidate) and recorded_biophys_success(candidate)
        and candidate.get("full_len") == len(sequence)
        and candidate["plddt"] > 70 and candidate["ii"] < 40
        and candidate.get("validation_status") == "valid"
    )


def select_best(history: list[list[dict]], *, eligible_only=True) -> dict:
    """Rank all iterations, preferring eligible candidates over diagnostic results."""
    candidates = [row for batch in history for row in batch
                  if not eligible_only or candidate_is_eligible(row)]
    candidates.sort(key=lambda row: (not candidate_is_eligible(row), candidate_sort_key(row)))
    return dict(candidates[0]) if candidates else {}


def _finish(result: AtelierResult) -> AtelierResult:
    """Save a terminal or pending checkpoint and its per-run memory snapshot."""
    record_event(result.run_dir, "run_finished", status=result.status,
                 stop_reason=result.stop_reason, error=result.error,
                 selected_candidate=result.best.get("candidate_id"))
    log_run(result.config.query, result.best.get("sequence", ""), result.best.get("plddt"),
            path=result.run_dir / "memory.jsonl", run_id=result.run_id, status=result.status)
    save_result(result)
    return result


def review_run(run_dir: str | Path, approved: bool) -> AtelierResult:
    """Approve or reject a saved candidate without running models or retrieval.

    The caller supplies a human decision. The candidate is revalidated on disk,
    and a lock prevents two clients from exporting the same run concurrently.
    """
    if type(approved) is not bool:
        raise ValueError("Review decision must be an explicit boolean")
    directory = Path(run_dir).resolve()
    lock = directory / "review.lock"
    try:
        lock.touch(exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("This run is already being reviewed") from exc
    try:
        result = load_result(directory)
        if result.config.simulation:
            raise ValueError("Synthetic evaluation runs cannot be approved for export")
        desired = "approved" if approved else "rejected"
        if result.status == desired:
            return result
        if result.status != "pending_review":
            raise ValueError(f"Run is not awaiting review: {result.status}")
        recorded_candidates = [row for batch in result.history for row in batch]
        reference_valid = True
        if result.config.mode == "reference":
            from src.design_contract import validate_reference_candidate
            reference_valid = validate_reference_candidate(result.best)
        if not reference_valid or not candidate_is_eligible(result.best) or result.best not in recorded_candidates:
            result.status = "invalid_output"
            result.error = "Saved candidate failed validation before export"
            result.best.update(eligible=False, passes=False)
            result.stop_reason = "export_validation_failed"
            record_event(directory, "export_blocked", reason=result.error)
            return _finish(result)
        record_event(directory, "human_review", decision=desired,
                     candidate_id=result.best["candidate_id"])
        if not approved:
            result.status = "rejected"
            result.approval = "rejected"
            result.stop_reason = "human_rejected"
            return _finish(result)

        result.approval = "approved"
        # Publish the export directory only after every file is written.
        try:
            with TemporaryDirectory(prefix=".export-", dir=directory) as temporary:
                staged = Path(temporary) / "exports"
                staged.mkdir()
                record = SeqRecord(Seq(result.best["sequence"]), id=result.best["candidate_id"],
                                   description="approved computational screening candidate")
                SeqIO.write([record], staged / "best.fasta", "fasta")
                files = ["exports/best.fasta"]
                if result.best.get("pdb"):
                    (staged / "best.pdb").write_text(result.best["pdb"], encoding="utf-8")
                    files.append("exports/best.pdb")
                if result.config.mode == "reference":
                    write_json(staged / "design_evidence.json", {
                        key: result.best.get(key) for key in
                        ("reference_sha256", "substitutions", "evidence", "delta_ii", "delta_plddt")
                    })
                    files.append("exports/design_evidence.json")
                staged.rename(directory / "exports")
        except OSError as exc:
            result.status, result.stop_reason = "failed", "export_failed"
            result.error = f"{type(exc).__name__}: {exc}"
            record_event(directory, "export_failed", error=result.error)
            return _finish(result)
        result.exported_files = files
        result.status = "approved"
        result.stop_reason = "human_approved"
        record_event(directory, "export_completed", files=result.exported_files)
        return _finish(result)
    finally:
        lock.unlink(missing_ok=True)


def run_enzyme_atelier(user_query: str, max_iterations: int = 2, n_candidates: int = 1,
                       *, output_root: str | Path = "outputs/runs",
                       approval_callback: ApprovalCallback | None = None,
                       mode: str = "progen2", planner=None, max_actions: int = 8,
                       max_retrievals: int = 3) -> AtelierResult:
    """Execute one bounded run with in-memory handoffs and isolated artifacts.

    No callback means pending review, never implicit approval. Eligibility is
    computational screening only; the validator currently checks length/alphabet.
    """
    config = RunConfig(query=user_query, max_iterations=max_iterations, n_candidates=n_candidates,
                       mode=mode, max_actions=max_actions, max_retrievals=max_retrievals,
                       planner_model=getattr(planner, "model", ""),
                       simulation=getattr(planner, "simulation", False) is True)
    if config.mode == "reference":
        from src.agents.reference_workflow import run_reference_workflow
        return run_reference_workflow(config, output_root=output_root, planner=planner,
                                      approval_callback=approval_callback)
    result = create_run(config, Path(output_root))
    phase = "retrieval"
    try:
        record_event(result.run_dir, "retrieval_started", query=config.query)
        constraints = rag_constraints(config.query)
        write_json(result.run_dir / "retrieval.json", {"query": config.query, "constraints": constraints})
        record_event(result.run_dir, "retrieval_completed", artifact="retrieval.json")
        prompt = constraints or config.query
        for iteration in range(1, config.max_iterations + 1):
            iteration_dir = result.run_dir / "iterations" / f"{iteration:03d}"
            iteration_dir.mkdir(parents=True)
            phase = "generation"
            record_event(result.run_dir, "generation_started", iteration=iteration, prompt=prompt)
            try:
                batch = generate_candidates(prompt, n=config.n_candidates)
            except GenerationFailure as exc:
                write_json(iteration_dir / "generation.json", {
                    "status": exc.status, "error": str(exc), "model_id": exc.model_id,
                })
                raise
            write_json(iteration_dir / "generation.json", {
                "status": "success", "model_id": batch.model_id, "prompt": prompt,
                "candidate_count": len(batch.sequences), "conditioning": "metadata_only",
                "sequences": list(batch.sequences),
            })
            if len(batch.sequences) != config.n_candidates:
                write_json(iteration_dir / "generation.json", {
                    "status": "invalid_output", "model_id": batch.model_id,
                    "error": "Empty or incomplete candidate batch", "sequences": list(batch.sequences),
                })
                raise GenerationFailure("invalid_output", "Empty or incomplete candidate batch", batch.model_id)
            record_event(result.run_dir, "generation_completed", iteration=iteration,
                         model_id=batch.model_id, candidate_count=len(batch.sequences))
            rows = []
            result.history.append(rows)
            records = []
            phase = "evaluation"
            for index, sequence in enumerate(batch.sequences, 1):
                candidate_id = f"iter_{iteration:03d}_candidate_{index:03d}"
                try:
                    PetaseValidator(sequence=sequence)
                except ValidationError as exc:
                    row = {"candidate_id": candidate_id, "iteration": iteration,
                           "sequence": sequence, "full_len": len(sequence),
                           "passes": False, "eligible": False, "validation_status": "invalid",
                           "validation_error": str(exc), "reason": "Candidate validation failed",
                           "fold_status": "not_run", "biophys_status": "not_run"}
                else:
                    record_event(result.run_dir, "evaluation_started", iteration=iteration,
                                 candidate_id=candidate_id)
                    row = evaluate_one(sequence, save_pdb=True)
                    # Bind measurements to the requested candidate, not a tool's substituted sequence.
                    if row.get("sequence") != sequence:
                        raise ValueError("Evaluator returned a different sequence")
                    row.update(candidate_id=candidate_id, iteration=iteration,
                               validation_status="valid", generation_model=batch.model_id)
                    row["eligible"] = candidate_is_eligible(row)
                    row["passes"] = row["eligible"]
                    records.append(SeqRecord(Seq(sequence), id=candidate_id,
                                             description="intermediate unapproved candidate"))
                rows.append(row)
                write_json(iteration_dir / "evaluation.json", rows)
                record_event(result.run_dir, "candidate_evaluated", iteration=iteration,
                             candidate_id=candidate_id, eligible=row["eligible"],
                             validation_status=row["validation_status"],
                             fold_status=row["fold_status"], biophys_status=row["biophys_status"])
            SeqIO.write(records, iteration_dir / "candidates.fasta", "fasta")
            result.best = select_best(result.history, eligible_only=False)
            save_result(result)
            eligible = select_best(result.history)
            if eligible:
                result.best = eligible
                result.status = "pending_review"
                result.approval = "pending"
                result.stop_reason = "screening_passed"
                record_event(result.run_dir, "review_requested", candidate_id=eligible["candidate_id"])
                break
            if any(row["validation_status"] == "invalid" for row in rows):
                result.status, result.stop_reason = "invalid_output", "candidate_validation_failed"
                break
            if any(not recorded_fold_success(row) or not recorded_biophys_success(row) for row in rows):
                result.status, result.stop_reason = "unavailable", "evaluation_unavailable"
                break
            if iteration == config.max_iterations:
                result.status, result.stop_reason = "no_candidate", "iteration_budget_exhausted"
                break
            phase = "critique"
            critique = critique_results(rows)
            write_json(iteration_dir / "critique.json", critique)
            record_event(result.run_dir, "critique_completed", iteration=iteration,
                         action=critique.get("action"), reason=critique.get("reason", ""))
            if critique.get("action") != "redesign" or not critique.get("new_designer_prompt"):
                result.status, result.stop_reason = "no_candidate", "critic_stopped"
                break
            prompt = critique["new_designer_prompt"]
            record_event(result.run_dir, "retry_decided", iteration=iteration, next_prompt=prompt)
    except GenerationFailure as exc:
        result.status = "invalid_output" if exc.status == "invalid_output" else "unavailable"
        result.error, result.stop_reason = str(exc), "generation_failed"
        record_event(result.run_dir, "tool_failed", phase=phase, error=str(exc))
    except KeyboardInterrupt:
        result.status, result.stop_reason = "cancelled", "interrupted"
        record_event(result.run_dir, "run_interrupted", phase=phase)
    except Exception as exc:
        result.status, result.stop_reason = "failed", f"{phase}_failed"
        result.error = f"{type(exc).__name__}: {exc}"
        record_event(result.run_dir, "tool_failed", phase=phase, error=result.error)
    result.best = select_best(result.history, eligible_only=False)
    _finish(result)
    if result.status == "pending_review" and approval_callback is not None:
        try:
            decision = approval_callback(result.best["sequence"])
        except (EOFError, KeyboardInterrupt):
            decision = None
        except Exception as exc:
            record_event(result.run_dir, "review_deferred", error=f"{type(exc).__name__}: {exc}")
            return result
        if decision is None:
            record_event(result.run_dir, "review_deferred", reason="No decision supplied")
        elif type(decision) is bool:
            return review_run(result.run_dir, decision)
        else:
            record_event(result.run_dir, "review_deferred", reason="Invalid callback decision")
    return result
