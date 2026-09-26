"""Bounded reference-design controller with a replaceable reasoning planner."""
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Callable

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from src.agents.rag_agent import retrieve_evidence
from src.agents.evaluator_agent import evaluate_one, recorded_fold_success, recorded_biophys_success
from src.agents.planner_agent import PlannerUnavailable
from src.design_contract import DesignDecision, apply_substitutions, load_reference
from src.run_store import create_run, write_json, record_event, save_result
from src.run_control import RunCancelled, check_cancelled


@dataclass(frozen=True)
class ReferenceTools:
    """Per-run tool boundaries; offline jobs never patch process-global functions."""
    retrieve: Callable
    evaluate: Callable


def failure_feedback(row):
    if not recorded_fold_success(row) or not recorded_biophys_success(row):
        return "tool_unavailable"
    failures = []
    if row["plddt"] <= 70:
        failures.append("low_structure_confidence")
    if row["ii"] >= 40:
        failures.append("high_instability_index")
    return "+".join(failures) or "screening_passed"


def run_reference_workflow(config, *, output_root, planner, approval_callback=None,
                           cancel_requested=None, tools=None):
    from src.agents.orchestrator import _finish, candidate_is_eligible, review_run, select_best

    if planner is None or not callable(getattr(planner, "decide", None)):
        raise ValueError("Reference design requires an explicitly configured planner")
    if config.n_candidates != 1:
        raise ValueError("Reference mode evaluates one planned variant per iteration; use --candidates 1")
    reference = load_reference()
    tools = tools or ReferenceTools(retrieve_evidence, evaluate_one)
    result = create_run(config, Path(output_root))
    write_json(result.run_dir / "reference.json", reference)
    phase = "retrieval"
    evidence = {}
    retrieval_count = 0
    queries = set()
    seen_sequences = {reference["sequence"]}

    def retrieve(query):
        nonlocal retrieval_count
        check_cancelled(cancel_requested)
        if retrieval_count >= config.max_retrievals or query in queries:
            raise ValueError("Retrieval budget exhausted or duplicate query")
        retrieval_count += 1
        queries.add(query)
        record_event(result.run_dir, "retrieval_started", query=query)
        retrieved = tools.retrieve(query)
        write_json(result.run_dir / "retrieval" / f"{retrieval_count:03d}.json", retrieved.model_dump())
        record_event(result.run_dir, "retrieval_completed", query=query, status=retrieved.status,
                     evidence_ids=[item.evidence_id for item in retrieved.excerpts])
        if retrieved.status == "unavailable":
            raise PlannerUnavailable("Retrieval unavailable: " + retrieved.error)
        evidence.update({item.evidence_id: item for item in retrieved.excerpts})
        check_cancelled(cancel_requested)

    def evaluate(sequence):
        check_cancelled(cancel_requested)
        record_event(result.run_dir, "baseline_evaluation_started")
        row = tools.evaluate(sequence, save_pdb=True)
        write_json(result.run_dir / "baseline.json", row)
        check_cancelled(cancel_requested)
        if row.get("sequence") != sequence or row.get("full_len") != len(sequence):
            raise ValueError("Evaluator returned a different sequence or length")
        if not recorded_fold_success(row) or not recorded_biophys_success(row):
            raise PlannerUnavailable("Evaluation unavailable: " + row.get("reason", "missing measurements"))
        return row

    try:
        retrieve(config.query)
        if not evidence:
            result.status, result.stop_reason = "no_candidate", "no_evidence"
            return _finish(result)
        phase = "baseline_evaluation"
        # WT provides an actual within-run comparator, not a fabricated trajectory.
        baseline = evaluate(reference["sequence"])
        write_json(result.run_dir / "baseline.json", baseline)
        record_event(result.run_dir, "baseline_evaluated", ii=baseline["ii"], plddt=baseline["plddt"])
        for step in range(1, config.max_actions + 1):
            check_cancelled(cancel_requested)
            phase = "planning"
            allowed = ["stop"]
            if retrieval_count < config.max_retrievals:
                allowed.append("retrieve")
            if len(result.history) < config.max_iterations:
                allowed.append("revise")
            context = {
                "query": config.query, "reference": reference, "allowed_actions": allowed,
                "remaining_variants": config.max_iterations - len(result.history),
                "remaining_retrievals": config.max_retrievals - retrieval_count,
                "remaining_actions": config.max_actions - step + 1,
                "evidence": [item.model_dump() for item in evidence.values()],
                "baseline": {key: value for key, value in baseline.items() if key != "pdb"},
                "history": [{key: value for key, value in row.items() if key not in ("pdb", "evidence")}
                            for batch in result.history for row in batch],
                "feedback": failure_feedback(result.history[-1][0]) if result.history else "initial_design",
            }
            write_json(result.run_dir / "decisions" / f"{step:03d}_input.json", context)
            record_event(result.run_dir, "planning_started", step=step)
            decision = planner.decide(context)
            if not isinstance(decision, DesignDecision):
                decision = DesignDecision.model_validate(decision)
            write_json(result.run_dir / "decisions" / f"{step:03d}.json", {
                "decision": decision.model_dump(), "provider": getattr(planner, "provider", "injected"),
                "model": getattr(planner, "model", ""), "response": getattr(planner, "last_metadata", {}),
            })
            record_event(result.run_dir, "decision", step=step, **decision.model_dump())
            check_cancelled(cancel_requested)
            if decision.action not in allowed or not decision.reason.strip():
                raise ValueError("Planner chose a disallowed action or omitted its rationale")
            if decision.reference_accession != reference["accession"]:
                raise ValueError("Planner used a different reference accession")
            if decision.action != "revise" and decision.substitutions:
                raise ValueError("Only a revise action may contain substitutions")
            if decision.action == "stop":
                result.status, result.stop_reason = "no_candidate", "planner_stopped"
                break
            if decision.action == "retrieve":
                if not decision.query.strip() or len(decision.query) > 1000:
                    raise ValueError("Invalid retrieval query")
                phase = "retrieval"
                retrieve(decision.query)
                continue
            if decision.query:
                raise ValueError("Revise action must not include a retrieval query")
            phase = "revision"
            sequence = apply_substitutions(decision.substitutions, list(evidence.values()))
            if sequence in seen_sequences:
                raise ValueError("Planner repeated a previously evaluated sequence")
            seen_sequences.add(sequence)
            iteration = len(result.history) + 1
            directory = result.run_dir / "iterations" / f"{iteration:03d}"
            candidate_id = f"iter_{iteration:03d}_candidate_001"
            write_json(directory / "generation.json", {
                "status": "success", "conditioning": "explicit_reference_substitutions",
                "model_id": config.planner_model, "sequences": [sequence],
                "substitutions": [item.model_dump() for item in decision.substitutions],
            })
            record_event(result.run_dir, "variant_constructed", iteration=iteration, candidate_id=candidate_id)
            phase = "evaluation"
            # Save unavailable measurements too; they remain diagnostic evidence.
            check_cancelled(cancel_requested)
            record_event(result.run_dir, "evaluation_started", candidate_id=candidate_id)
            row = tools.evaluate(sequence, save_pdb=True)
            if row.get("sequence") != sequence or row.get("full_len") != len(sequence):
                raise ValueError("Evaluator returned a different sequence or length")
            used_ids = {item.evidence_id for item in decision.substitutions}
            row.update(candidate_id=candidate_id, iteration=iteration, validation_status="valid",
                       design_mode="reference", reference_sha256=reference["sequence_sha256"],
                       substitutions=[item.model_dump() for item in decision.substitutions],
                       evidence=[evidence[key].model_dump() for key in sorted(used_ids)],
                       generation_model=config.planner_model)
            row["delta_ii"] = row["ii"] - baseline["ii"] if recorded_biophys_success(row) else None
            row["delta_plddt"] = row["plddt"] - baseline["plddt"] if recorded_fold_success(row) else None
            row["eligible"] = row["passes"] = candidate_is_eligible(row)
            result.history.append([row])
            write_json(directory / "evaluation.json", [row])
            SeqIO.write([SeqRecord(Seq(sequence), id=candidate_id, description="unapproved reference variant")],
                        directory / "candidates.fasta", "fasta")
            result.best = select_best(result.history, eligible_only=False)
            save_result(result)
            check_cancelled(cancel_requested)
            record_event(result.run_dir, "candidate_evaluated", candidate_id=candidate_id,
                         feedback=failure_feedback(row), eligible=row["eligible"])
            if failure_feedback(row) == "tool_unavailable":
                result.status, result.stop_reason = "unavailable", "evaluation_unavailable"
                break
            if row["eligible"]:
                result.status, result.approval = "pending_review", "pending"
                result.stop_reason = "screening_passed"
                record_event(result.run_dir, "review_requested", candidate_id=candidate_id)
                break
            if len(result.history) >= config.max_iterations:
                result.status, result.stop_reason = "no_candidate", "iteration_budget_exhausted"
                break
        else:
            result.status, result.stop_reason = "no_candidate", "action_budget_exhausted"
    except PlannerUnavailable as exc:
        result.status, result.stop_reason, result.error = "unavailable", f"{phase}_unavailable", str(exc)
    except ValueError as exc:
        result.status, result.stop_reason, result.error = "invalid_output", f"{phase}_invalid", str(exc)
    except (KeyboardInterrupt, RunCancelled):
        result.status, result.stop_reason = "cancelled", "interrupted"
    except Exception as exc:
        result.status, result.stop_reason = "failed", f"{phase}_failed"
        result.error = f"{type(exc).__name__}: {exc}"
    result.best = select_best(result.history, eligible_only=False)
    _finish(result)
    if result.status == "pending_review" and approval_callback is not None:
        try:
            decision = approval_callback(result.best["sequence"])
        except (EOFError, KeyboardInterrupt):
            decision = None
        except Exception as exc:
            record_event(result.run_dir, "review_deferred", error=type(exc).__name__)
            return result
        if type(decision) is bool:
            return review_run(result.run_dir, decision)
        record_event(result.run_dir, "review_deferred", reason="No explicit boolean decision")
    return result
