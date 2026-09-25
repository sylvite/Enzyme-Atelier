"""Offline regressions for folding provenance through real application modules."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import matplotlib
matplotlib.use("Agg")
import pytest
import requests

from src.tools import esmfold_tool as folding
from src.agents import evaluator_agent as evaluator
from src.agents import critic_agent as critic
from src.agents import orchestrator
import evaluation


def pdb_for(sequence, score=82.5):
    names = {"A": "ALA", "G": "GLY"}
    return "\n".join(
        f"ATOM  {i:5d}  CA  {names[aa]:3s} A{i:4d}    {1.:8.3f}{2.:8.3f}{3.:8.3f}{1.:6.2f}{score:6.2f}           C"
        for i, aa in enumerate(sequence, 1)
    )


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    post = Mock(side_effect=AssertionError("Unexpected HTTP request"))
    sleep = Mock()
    monkeypatch.setattr(folding.requests, "post", post)
    monkeypatch.setattr(folding.time, "sleep", sleep)
    return post, sleep


def respond(post, code=200, text=""):
    post.side_effect = None
    post.return_value = SimpleNamespace(status_code=code, text=text)


def test_full_sequence_success_one_request(offline):
    post, sleep = offline
    sequence = "A" * 290
    respond(post, text=pdb_for(sequence))
    result = folding.esmfold_fold(sequence)
    assert result["success"] is True
    assert result["plddt"] == pytest.approx(82.5)
    assert result["folded_length"] == 290
    assert result["source"] == "esm_atlas"
    assert post.call_count == result["attempts"] == 1
    assert post.call_args.kwargs["data"] == sequence
    sleep.assert_not_called()


@pytest.mark.parametrize("code,attempts", [(504, 3), (429, 3), (400, 1)])
def test_http_failures_have_no_score(offline, code, attempts):
    post, sleep = offline
    respond(post, code=code)
    result = folding.esmfold_fold("AAA")
    assert result["status"] == "unavailable"
    assert result["plddt"] is None and result["pdb"] == ""
    assert result["folded_length"] == 0
    assert result["attempts"] == post.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert result["error"] == f"HTTP {code}"


def test_timeout_then_recovery(offline):
    post, sleep = offline
    post.side_effect = [requests.Timeout("timed out"), SimpleNamespace(status_code=200, text=pdb_for("AAA"))]
    result = folding.esmfold_fold("AAA")
    assert result["success"] is True and result["error"] == ""
    assert result["attempts"] == 2
    sleep.assert_called_once_with(5)


@pytest.mark.parametrize("body", ["", "<html>error</html>", "ATOM  bad", pdb_for("AA"), pdb_for("AAG"),
                                     pdb_for("AAA", float("nan")), pdb_for("AAA", 101), pdb_for("AAA", -1)])
def test_bad_predictions_remain_unavailable(offline, body):
    post, _ = offline
    respond(post, text=body)
    result = folding.esmfold_fold("AAA", max_retries=1)
    assert result["plddt"] is None and result["success"] is False
    assert result["error"]


def test_no_heuristic_rescaling(offline):
    post, _ = offline
    respond(post, text=pdb_for("AAA", .8))
    assert folding.esmfold_fold("AAA")["plddt"] == pytest.approx(.8)
    assert folding.esmfold_fold("AAA", plddt_scale=1)["plddt"] == pytest.approx(80)


@pytest.mark.parametrize("budget", [0, -1, 1.5, True])
def test_invalid_budget_never_calls_http(offline, budget):
    with pytest.raises(ValueError):
        folding.esmfold_fold("AAA", max_retries=budget)
    offline[0].assert_not_called()


@pytest.mark.parametrize("sequence", ["", "AXA"])
def test_invalid_sequence_never_calls_http(offline, sequence):
    result = folding.esmfold_fold(sequence)
    assert result["plddt"] is None and result["attempts"] == 0
    offline[0].assert_not_called()


def test_failed_fold_with_high_score_cannot_pass(monkeypatch):
    monkeypatch.setattr(evaluator, "esmfold_fold", lambda seq: {
        "success": False, "status": "success", "source": "esm_atlas",
        "folded_length": len(seq), "plddt": 95, "error": "timeout", "attempts": 3,
    })
    result = evaluator.evaluate_one("A" * 290)
    assert result["passes"] is False and result["plddt"] is None
    assert result["fold_status"] == "unavailable"
    assert result["fold_error"] == "timeout"


def test_batch_mixed_results_and_json_null(tmp_path, monkeypatch, offline):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "candidates.fasta").write_text(">one\n" + "A" * 290 + "\n>two\n" + "A" * 291 + "\n", encoding="utf-8")
    post, _ = offline
    post.side_effect = [SimpleNamespace(status_code=200, text=pdb_for("A" * 290))] + [SimpleNamespace(status_code=504, text="")] * 3
    rows = evaluator.evaluate_batch("candidates.fasta")
    assert [r["passes"] for r in rows] == [True, False]
    saved = json.loads((tmp_path / "outputs/eval_results.json").read_text())
    assert saved[1]["plddt"] is None and saved[1]["fold_attempts"] == 3
    assert saved[0]["fold_len"] == 290


def test_critic_stops_without_retrieval_for_unavailable(tmp_path, monkeypatch, offline):
    monkeypatch.chdir(tmp_path)
    respond(offline[0], code=504)
    result = evaluator.evaluate_one("AAA")
    (tmp_path / "results.json").write_text(json.dumps([result]))
    rag = Mock(side_effect=AssertionError("Unavailable fold must not prompt biological redesign"))
    monkeypatch.setattr(critic, "query_rag_for_fix", rag)
    decision = critic.critique_eval_results("results.json")
    assert decision["action"] == "stop"
    rag.assert_not_called()
    assert json.loads((tmp_path / "outputs/critique.json").read_text())["action"] == "stop"


@pytest.mark.parametrize("available", [True, False])
def test_orchestrator_handles_nullable_results(tmp_path, monkeypatch, offline, available):
    monkeypatch.chdir(tmp_path)
    respond(offline[0], code=200 if available else 504, text=pdb_for("A" * 290))
    result = evaluator.evaluate_one("A" * 290)
    monkeypatch.setattr(orchestrator, "rag_constraints", lambda query: "constraints")
    monkeypatch.setattr(orchestrator, "design_candidates", lambda *args, **kwargs: "unused.fasta")
    monkeypatch.setattr(orchestrator, "evaluate_batch", lambda path: [result])
    monkeypatch.setattr(orchestrator, "log_run", Mock())
    output = orchestrator.run_enzyme_atelier("query", max_iterations=1)
    assert output.best["passes"] is available
    assert (output.best["plddt"] is None) is (not available)


@pytest.mark.parametrize("kind", ["success", "unavailable", "legacy", "empty"])
def test_report_artifacts_use_provenance(tmp_path, monkeypatch, offline, kind):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    if kind in ("success", "unavailable"):
        respond(offline[0], code=200 if kind == "success" else 504, text=pdb_for("A" * 290, 75))
        rows = [evaluator.evaluate_one("A" * 290)]
    elif kind == "legacy":
        rows = [{"ii": 20, "plddt": 99, "passes": True, "reason": "old result"}]
    else:
        rows = []
    (tmp_path / "outputs/eval_results.json").write_text(json.dumps(rows))
    evaluation.plot_metrics()
    summary = json.loads((tmp_path / "outputs/final_summary.json").read_text())
    assert summary["passes"] is (kind == "success")
    assert summary["esmfold_status"] == {"legacy": "unknown", "empty": "unknown"}.get(kind, kind)
    assert summary["final_plddt"] == (75 if kind == "success" else None)
    assert summary["guardrail"] == "not recorded"
    assert (tmp_path / "outputs/plots/ii_vs_plddt.png").exists()
    assert (tmp_path / "outputs/plots/iteration_ii.png").exists()


def test_low_confidence_is_measured_failure(offline):
    respond(offline[0], text=pdb_for("A" * 290, 65))
    result = evaluator.evaluate_one("A" * 290)
    assert result["fold_status"] == "success"
    assert result["plddt"] == 65 and result["passes"] is False
    assert evaluation.build_summary([result])["esmfold_status"] == "success"


def test_rank_passing_before_higher_scoring_failure(offline):
    respond(offline[0], text=pdb_for("A" * 290, 75))
    passing = evaluator.evaluate_one("A" * 290)
    failing = dict(passing, plddt=95, ii=60, passes=False, is_stable=False)
    summary = evaluation.build_summary([failing, passing])
    assert summary["passes"] is True and summary["final_plddt"] == 75


def test_transport_failure_budget(offline):
    post, sleep = offline
    post.side_effect = requests.Timeout("timed out")
    result = folding.esmfold_fold("AAA", max_retries=2)
    assert result["plddt"] is None and result["error"] == "timed out"
    assert result["attempts"] == post.call_count == 2
    sleep.assert_called_once_with(5)
