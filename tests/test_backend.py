"""Backend integration tests with external model/retrieval boundaries mocked."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from Bio import SeqIO

import main as cli
import evaluation
from src.agents import orchestrator as backend
from src.agents import designer_agent as designer
from src.agents import evaluator_agent as evaluator
from src.agents import critic_agent as critic
from src.tools.progen2_tool import ProGen2Output
from src.run_store import load_result, write_json
from src.memory.episodic_store import load_history, log_run
from src.guards.petase_validator import human_approval_gate


@pytest.fixture
def external_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    retrieval = Mock(return_value="Retrieved constraints for the requested query")
    generation = Mock(side_effect=lambda inp: ProGen2Output(
        sequences=["A" * 290] * inp.num_return, model_id="offline-test-model",
        success=True, status="success"))
    folding = Mock(side_effect=lambda sequence: {
        "success": True, "status": "success", "source": "esm_atlas",
        "plddt": 85.0, "pdb": "offline-test-structure", "error": "", "attempts": 1,
        "folded_length": len(sequence), "plddt_scale": 100,
    })
    monkeypatch.setattr(backend, "rag_constraints", retrieval)
    monkeypatch.setattr(designer, "progen2_generate", generation)
    monkeypatch.setattr(evaluator, "esmfold_fold", folding)
    monkeypatch.setattr(critic, "query_rag_for_fix", lambda *args: (
        ["Evidence from the offline fixture"], [{"source": "fixture.pdf"}]))
    # Any accidental escape to real HTTP or model loading fails immediately.
    monkeypatch.setattr("requests.post", Mock(side_effect=AssertionError("Unexpected HTTP")))
    return retrieval, generation, folding


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_success_waits_for_explicit_review(external_tools):
    result = backend.run_enzyme_atelier("my actual query", n_candidates=2)
    assert result.status == "pending_review" and result.approval == "pending"
    assert result.best["eligible"] is True
    assert not (result.run_dir / "exports").exists()
    external_tools[0].assert_called_once_with("my actual query")
    assert read_json(result.run_dir / "config.json")["query"] == "my actual query"
    assert len(result.history[0]) == 2
    assert read_json(result.run_dir / "iterations/001/generation.json")["model_id"] == "offline-test-model"
    assert read_json(result.run_dir / "iterations/001/evaluation.json")[0]["candidate_id"]
    assert (result.run_dir / "iterations/001/candidates.fasta").exists()
    events = load_history(result.run_dir / "events.jsonl")
    assert all(row["run_id"] == result.run_id for row in events)
    assert "review_requested" in [row["event"] for row in events]
    assert "human_review" not in [row["event"] for row in events]
    assert load_history(result.run_dir / "memory.jsonl")[0]["best_seq"] == "A" * 290


@pytest.mark.parametrize("approved", [True, False])
def test_review_callback_controls_export(external_tools, approved):
    seen = []
    def decide(sequence):
        seen.append(sequence)
        return approved
    result = backend.run_enzyme_atelier("query", approval_callback=decide)
    assert seen == ["A" * 290]
    assert result.status == ("approved" if approved else "rejected")
    assert (result.run_dir / "exports").exists() is approved
    if approved:
        assert str(next(SeqIO.parse(result.run_dir / "exports/best.fasta", "fasta")).seq) == seen[0]
        assert (result.run_dir / "exports/best.pdb").read_text() == "offline-test-structure"
    assert load_result(result.run_dir).status == result.status
    events = [row["event"] for row in load_history(result.run_dir / "events.jsonl")]
    if approved:
        assert events.index("human_review") < events.index("export_completed")


@pytest.mark.parametrize("decision", [None, 1, "yes", EOFError(), KeyboardInterrupt(), RuntimeError("UI closed")])
def test_missing_or_invalid_review_never_exports(external_tools, decision):
    def decide(sequence):
        if isinstance(decision, BaseException):
            raise decision
        return decision
    result = backend.run_enzyme_atelier("query", approval_callback=decide)
    assert result.status == "pending_review"
    assert not (result.run_dir / "exports").exists()
    assert load_history(result.run_dir / "events.jsonl")[-1]["event"] == "review_deferred"


def test_later_review_does_not_repeat_tools_and_is_idempotent(external_tools):
    result = backend.run_enzyme_atelier("query")
    counts = [tool.call_count for tool in external_tools]
    approved = backend.review_run(result.run_dir, True)
    before = (result.run_dir / "events.jsonl").read_bytes()
    again = backend.review_run(result.run_dir, True)
    assert approved.status == again.status == "approved"
    assert [tool.call_count for tool in external_tools] == counts
    assert (result.run_dir / "events.jsonl").read_bytes() == before
    with pytest.raises(ValueError, match="not awaiting"):
        backend.review_run(result.run_dir, False)


@pytest.mark.parametrize("change", [{"sequence": "AAA"}, {"ii": 99, "is_stable": False},
                                   {"fold_status": "unavailable"}, {"validation_status": "invalid"},
                                   {"candidate_id": "not-in-history"}, {"fold_len": None, "full_len": None}])
def test_export_revalidates_saved_candidate(external_tools, change):
    result = backend.run_enzyme_atelier("query")
    document = read_json(result.run_dir / "result.json")
    document["best"].update(change)
    write_json(result.run_dir / "result.json", document)
    result = backend.review_run(result.run_dir, True)
    assert result.status == "invalid_output"
    assert read_json(result.run_dir / "final_summary.json")["screening_passes"] is False
    assert not (result.run_dir / "exports").exists()


@pytest.mark.parametrize("settings", [{"max_iterations": 0}, {"max_iterations": True},
                                      {"n_candidates": 0}, {"n_candidates": 21}, {"n_candidates": 1.5}])
def test_invalid_configuration_has_no_side_effects(external_tools, settings):
    with pytest.raises(ValueError):
        backend.run_enzyme_atelier("query", **settings)
    assert not Path("outputs").exists()
    for tool in external_tools:
        tool.assert_not_called()


def test_blank_query_rejected(external_tools):
    with pytest.raises(ValueError):
        backend.run_enzyme_atelier("  \n  ")
    assert not Path("outputs").exists()


def test_retries_preserve_iterations_and_pass_actual_critique(external_tools, monkeypatch):
    external_tools[2].side_effect = [
        {"success": True, "status": "success", "source": "esm_atlas", "plddt": score,
         "pdb": "fixture", "attempts": 1, "folded_length": 290}
        for score in (60, 85)
    ]
    generator = Mock(wraps=backend.generate_candidates)
    monkeypatch.setattr(backend, "generate_candidates", generator)
    result = backend.run_enzyme_atelier("query", max_iterations=2)
    assert result.status == "pending_review" and len(result.history) == 2
    assert result.best["candidate_id"] == "iter_002_candidate_001"
    assert "Evidence from the offline fixture" in generator.call_args_list[1].args[0]
    for iteration in (1, 2):
        assert (result.run_dir / f"iterations/{iteration:03d}/evaluation.json").exists()
    assert read_json(result.run_dir / "iterations/001/critique.json")["evidence"]
    events = load_history(result.run_dir / "events.jsonl")
    assert sum(row["event"] == "retry_decided" for row in events) == 1


def test_best_diagnostic_comes_from_all_iterations(external_tools):
    external_tools[2].side_effect = [
        {"success": True, "status": "success", "source": "esm_atlas", "plddt": score,
         "pdb": "fixture", "attempts": 1, "folded_length": 290}
        for score in (65, 55)
    ]
    result = backend.run_enzyme_atelier("query", max_iterations=2)
    assert result.status == "no_candidate" and result.stop_reason == "iteration_budget_exhausted"
    assert result.best["candidate_id"] == "iter_001_candidate_001"
    assert not (result.run_dir / "exports").exists()


def test_selection_ignores_invalid_high_score_across_batches(external_tools):
    result = backend.run_enzyme_atelier("query")
    valid = result.best
    better = dict(valid, candidate_id="earlier", plddt=90)
    invalid = dict(valid, candidate_id="invalid", sequence="AAA", plddt=99)
    assert backend.select_best([[better], [invalid, valid]])["candidate_id"] == "earlier"


def test_unavailable_stops_without_critique_or_review(external_tools, monkeypatch):
    external_tools[2].side_effect = lambda seq: {"success": False, "status": "unavailable", "plddt": None, "error": "timeout"}
    critique = Mock(side_effect=AssertionError("Cannot critique unavailable evidence"))
    review = Mock(side_effect=AssertionError("Cannot approve unavailable evidence"))
    monkeypatch.setattr(backend, "critique_results", critique)
    result = backend.run_enzyme_atelier("query", approval_callback=review)
    assert result.status == "unavailable" and len(result.history) == 1
    critique.assert_not_called()
    review.assert_not_called()


@pytest.mark.parametrize("sequence", ["AAA", "A" * 289 + "X"])
def test_backend_guards_before_evaluation_even_if_generator_is_wrong(external_tools, monkeypatch, sequence):
    monkeypatch.setattr(backend, "generate_candidates", lambda *a, **k: designer.CandidateBatch((sequence,), "test", "query"))
    result = backend.run_enzyme_atelier("query")
    assert result.status == "invalid_output" and result.best["eligible"] is False
    external_tools[2].assert_not_called()
    assert not (result.run_dir / "exports").exists()


def test_empty_generation_is_recorded(external_tools, monkeypatch):
    monkeypatch.setattr(backend, "generate_candidates", lambda *a, **k: designer.CandidateBatch((), "test", "query"))
    result = backend.run_enzyme_atelier("query")
    assert result.status == "invalid_output" and result.best == {}
    assert read_json(result.run_dir / "iterations/001/generation.json")["status"] == "invalid_output"


@pytest.mark.parametrize("phase", ["retrieval", "evaluation", "critique"])
def test_tool_exceptions_leave_readable_run_records(external_tools, monkeypatch, phase):
    if phase == "retrieval":
        external_tools[0].side_effect = RuntimeError("retrieval down")
    elif phase == "evaluation":
        monkeypatch.setattr(backend, "evaluate_one", Mock(side_effect=RuntimeError("evaluation down")))
    else:
        external_tools[2].side_effect = lambda seq: {
            "success": True, "status": "success", "source": "esm_atlas", "plddt": 50,
            "pdb": "fixture", "attempts": 1, "folded_length": len(seq)}
        monkeypatch.setattr(backend, "critique_results", Mock(side_effect=RuntimeError("critique down")))
    result = backend.run_enzyme_atelier("query")
    assert result.status == "failed" and result.stop_reason == f"{phase}_failed"
    assert load_result(result.run_dir).error
    assert load_history(result.run_dir / "events.jsonl")[-1]["event"] == "run_finished"
    assert not (result.run_dir / "exports").exists()


def test_interruption_is_saved(external_tools, monkeypatch):
    monkeypatch.setattr(backend, "evaluate_one", Mock(side_effect=KeyboardInterrupt()))
    result = backend.run_enzyme_atelier("query")
    assert result.status == "cancelled" and load_result(result.run_dir).status == "cancelled"


def test_concurrent_runs_are_isolated_and_preserve_old_files(external_tools):
    Path("outputs").mkdir()
    Path("outputs/final_summary.json").write_text("historical artifact")
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(backend.run_enzyme_atelier, ["first query", "second query"]))
    assert len({run.run_dir for run in runs}) == 2
    assert all(run.status == "pending_review" for run in runs)
    assert Path("outputs/final_summary.json").read_text() == "historical artifact"
    assert not Path("data/episodic_memory.jsonl").exists()
    for run in runs:
        assert load_result(run.run_dir).config.query == run.config.query
        assert all(entry["run_id"] == run.run_id for entry in load_history(run.run_dir / "events.jsonl"))


def test_cli_and_backend_share_query_and_outcome(external_tools, monkeypatch):
    monkeypatch.setattr(cli, "human_approval_gate", lambda sequence: True)
    assert cli.main(["--mode", "progen2", "--query", "custom query", "--review", "--output-root", "cli-runs"]) == 0
    cli_result = load_result(next(Path("cli-runs").iterdir()))
    direct = backend.run_enzyme_atelier("custom query", approval_callback=lambda sequence: True)
    assert cli_result.config == direct.config
    assert cli_result.best == direct.best and cli_result.status == direct.status


def test_cli_pending_and_saved_review(external_tools, monkeypatch):
    assert cli.main(["--mode", "progen2", "--query", "query"]) == 2
    run_dir = next(Path("outputs/runs").iterdir())
    before = external_tools[1].call_count
    monkeypatch.setattr(cli, "human_approval_gate", lambda sequence: False)
    assert cli.main(["--review-run", str(run_dir)]) == 1
    assert load_result(run_dir).status == "rejected"
    assert external_tools[1].call_count == before


def test_cli_validates_settings_without_running_tools(external_tools):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--mode", "progen2", "--query", "query", "--max-iter", "0"])
    assert exc.value.code == 2
    external_tools[0].assert_not_called()


def test_memory_multiple_records_and_legacy_format(tmp_path):
    path = tmp_path / "memory.jsonl"
    log_run("first °C", "A" * 290, None, path=path, run_id="one")
    log_run("second", "G" * 290, 80, path=path, run_id="two")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert load_history(path)[0]["best_seq"] == "A" * 290
    assert load_history(path)[0]["score"] is None
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text('{"query":"old1"}{"query":"old2"}', encoding="utf-8")
    log_run("new", "AAA", None, path=legacy)
    assert len(load_history(legacy)) == 3


def test_reports_use_selected_run_and_preserve_approval(external_tools):
    result = backend.run_enzyme_atelier("query", approval_callback=lambda sequence: True)
    before = (result.run_dir / "result.json").read_bytes()
    summary_before = (result.run_dir / "final_summary.json").read_bytes()
    report_dir = evaluation.plot_run_metrics(result.run_dir)
    assert read_json(report_dir / "summary.json")["status"] == "approved"
    assert (report_dir / "iteration_ii.png").exists()
    assert (report_dir / "eval_table.csv").exists()
    assert (result.run_dir / "result.json").read_bytes() == before
    assert (result.run_dir / "final_summary.json").read_bytes() == summary_before


def test_human_gate_requires_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert human_approval_gate("A" * 290) is False


def test_failed_export_publishes_no_partial_final_files(external_tools, monkeypatch):
    result = backend.run_enzyme_atelier("query")
    monkeypatch.setattr(backend.SeqIO, "write", Mock(side_effect=OSError("disk error")))
    result = backend.review_run(result.run_dir, True)
    assert result.status == "failed" and result.stop_reason == "export_failed"
    assert result.approval == "approved" and result.exported_files == []
    assert not (result.run_dir / "exports").exists()
    assert not (result.run_dir / "review.lock").exists()
    assert not list(result.run_dir.glob(".export-*"))


def test_review_lock_prevents_simultaneous_export(external_tools):
    result = backend.run_enzyme_atelier("query")
    (result.run_dir / "review.lock").touch()
    with pytest.raises(ValueError, match="already being reviewed"):
        backend.review_run(result.run_dir, True)
    assert not (result.run_dir / "exports").exists()


def test_harness_uses_backend_without_implicit_approval(external_tools, monkeypatch):
    from eval import eval_harness
    results = eval_harness.run_all(n=1)
    assert results[0]["status"] == "pending_review" and results[0]["screening_passes"] is True
    run = next(Path("outputs/evaluations").glob("*/runs/*"))
    assert not (run / "exports").exists()
