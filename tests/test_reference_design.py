"""Reference-design regression tests. All model and scientific results are fixtures."""
import json
from unittest.mock import Mock

import pytest

import main as cli
from eval.design_scenarios import CASES, FIXTURE, FixturePlanner, measured, mutation, run_all, run_case
from src.agents import reference_workflow as workflow
from src.agents.orchestrator import run_enzyme_atelier, review_run
from src.agents.planner_agent import OpenAIPlanner, PlannerUnavailable
from src.design_contract import DesignDecision, apply_substitutions, load_reference
from src.evidence import RetrievalResult
from src.run_store import load_result, save_result


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    monkeypatch.setattr("requests.post", Mock(side_effect=AssertionError("No live API calls in tests")))


@pytest.mark.parametrize("case,expected", CASES.items())
def test_controller_scenarios(tmp_path, case, expected):
    result = run_case(case, tmp_path)
    assert result.status == expected, result.error
    assert result.config.simulation is True
    assert load_result(result.run_dir).status == expected
    assert not (result.run_dir / "exports").exists()


def test_reference_numbering_and_exact_changes():
    reference = load_reference()
    assert len(reference["sequence"]) == 263
    assert reference["sequence"][160 - 28] == "S"
    variant = apply_substitutions([mutation("S238F")], [FIXTURE])
    assert len(variant) == 263 and variant[238 - 28] == "F"
    assert sum(left != right for left, right in zip(variant, reference["sequence"])) == 1


def test_revision_feedback_changes_sequence_and_retains_evidence(tmp_path):
    result = run_case("low_confidence_revision", tmp_path)
    assert len(result.history) == 2
    assert result.history[0][0]["sequence"] != result.history[1][0]["sequence"]
    context = json.loads((result.run_dir / "decisions/002_input.json").read_text())
    assert context["feedback"] == "low_structure_confidence"
    assert context["history"][0]["plddt"] == 60
    assert result.best["evidence"][0]["evidence_id"] == FIXTURE.evidence_id
    assert result.best["delta_plddt"] == 0  # relative to the measured WT, not an invented baseline


def test_synthetic_runs_cannot_be_exported(tmp_path):
    result = run_case("screening_pass", tmp_path)
    with pytest.raises(ValueError, match="Synthetic"):
        review_run(result.run_dir, True)
    assert not (result.run_dir / "exports").exists()


def test_reference_export_rechecks_protected_residues(tmp_path):
    result = run_case("screening_pass", tmp_path)
    result.config.simulation = False  # exercise the real export validator against tampered saved data
    row = result.history[0][0]
    row["sequence"] = row["sequence"][:132] + "A" + row["sequence"][133:]
    result.best = dict(row)
    save_result(result)
    checked = review_run(result.run_dir, True)
    assert checked.status == "invalid_output"
    assert not (result.run_dir / "exports").exists()


def test_ablation_compares_same_cases_without_feedback(tmp_path):
    _, report = run_all(tmp_path)
    assert report["matched"] == report["total"] == 15
    with_feedback = [row for row in report["ablation"] if row["feedback_enabled"]]
    without_feedback = [row for row in report["ablation"] if not row["feedback_enabled"]]
    assert sum(row["screening_passes"] for row in with_feedback) == 2
    assert sum(row["screening_passes"] for row in without_feedback) == 0
    assert report["simulation"] is True


def test_baseline_failure_is_saved_and_stops_before_planning(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "retrieve_evidence", lambda query: RetrievalResult(
        query=query, status="success", excerpts=[FIXTURE]))
    row = measured(load_reference()["sequence"])
    row.update(plddt=None, fold_status="unavailable")
    monkeypatch.setattr(workflow, "evaluate_one", lambda *a, **k: row)
    planner = FixturePlanner("screening_pass")
    result = run_enzyme_atelier("query", mode="reference", planner=planner, output_root=tmp_path)
    assert result.status == "unavailable" and planner.calls == 0
    assert json.loads((result.run_dir / "baseline.json").read_text())["plddt"] is None


def test_action_budget_stops_retrieval_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "retrieve_evidence", lambda query: RetrievalResult(
        query=query, status="success", excerpts=[FIXTURE]))
    monkeypatch.setattr(workflow, "evaluate_one", lambda seq, **kw: measured(seq))
    planner = FixturePlanner("screening_pass")
    planner.decide = lambda context: DesignDecision(action="retrieve", reason="Need evidence",
        query="new query", reference_accession="A0A0K8P6T7", substitutions=[])
    result = run_enzyme_atelier("query", mode="reference", planner=planner, output_root=tmp_path,
                                max_actions=1)
    assert result.stop_reason == "action_budget_exhausted" and result.history == []


def test_cli_requires_explicit_api_enable(monkeypatch):
    constructor = Mock(side_effect=AssertionError("Must not initialize planner"))
    monkeypatch.setattr("src.agents.planner_agent.OpenAIPlanner", constructor)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--query", "PETase"])
    assert exc.value.code == 2
    constructor.assert_not_called()


def api_response(decision, **overrides):
    return dict({"id": "fixture-response", "model": "test-model", "status": "completed",
                 "usage": {"input_tokens": 1, "output_tokens": 1},
                 "output": [{"type": "message", "content": [
                     {"type": "output_text", "text": decision.model_dump_json()}]}]}, **overrides)


def test_openai_request_uses_strict_schema_and_records_usage(monkeypatch):
    decision = FixturePlanner("screening_pass").decide({"feedback": "initial_design"})
    response = Mock(status_code=200)
    response.json.return_value = api_response(decision)
    post = Mock(return_value=response)
    monkeypatch.setattr("requests.post", post)
    planner = OpenAIPlanner("test-model", api_key="test-only-not-a-key")
    assert planner.decide({"feedback": "initial_design"}) == decision
    payload = post.call_args.kwargs["json"]
    assert payload["store"] is False and payload["text"]["format"]["strict"] is True
    assert payload["max_output_tokens"] == 2000
    assert planner.last_metadata["usage"]["output_tokens"] == 1
    assert "test-only-not-a-key" not in json.dumps(planner.last_metadata)


@pytest.mark.parametrize("kind", ["http", "incomplete", "refusal", "invalid_json", "timeout"])
def test_openai_failures_are_explicit_and_never_retried(monkeypatch, kind):
    import requests
    decision = FixturePlanner("screening_pass").decide({"feedback": "initial_design"})
    body = api_response(decision)
    if kind == "incomplete":
        body["status"] = "incomplete"
    if kind == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "fixture"}]
    if kind == "invalid_json":
        body["output"][0]["content"][0]["text"] = "{}"
    response = Mock(status_code=429 if kind == "http" else 200)
    response.json.return_value = body
    post = Mock(return_value=response)
    if kind == "timeout":
        post.side_effect = requests.Timeout()
    monkeypatch.setattr("requests.post", post)
    with pytest.raises(PlannerUnavailable):
        OpenAIPlanner("test-model", api_key="test-only").decide({})
    assert post.call_count == 1

def test_reference_review_displays_evidence_before_decision(tmp_path, monkeypatch, capsys):
    result = run_case("screening_pass", tmp_path)
    result.config.simulation = False  # Exercise the human-review presentation with synthetic inputs.
    save_result(result)
    monkeypatch.setattr(cli, "human_approval_gate", lambda sequence: False)
    reviewed = cli.review_saved_result(result)
    output = capsys.readouterr().out
    assert "S121E" in output and "SYNTHETIC_FIXTURE.pdf, page 1" in output
    assert "Changes from measured WT" in output
    assert reviewed.status == "rejected" and not (result.run_dir / "exports").exists()


def test_reference_export_includes_exact_design_evidence(tmp_path):
    result = run_case("screening_pass", tmp_path)
    result.config.simulation = False  # Exercise export serialization, not a scientific claim.
    save_result(result)
    reviewed = review_run(result.run_dir, True)
    assert reviewed.status == "approved"
    exported = json.loads((result.run_dir / "exports/design_evidence.json").read_text())
    assert exported["substitutions"] == result.best["substitutions"]
    assert exported["evidence"] == result.best["evidence"]
    from Bio import SeqIO
    assert str(next(SeqIO.parse(result.run_dir / "exports/best.fasta", "fasta")).seq) == result.best["sequence"]
