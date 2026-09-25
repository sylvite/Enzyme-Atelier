"""Regression tests for real generation/biophysics boundaries; no model downloads."""
import builtins
from contextlib import nullcontext
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from Bio import SeqIO
from Bio.SeqUtils.ProtParam import ProteinAnalysis

from src.tools import progen2_tool as generation
from src.tools import biophys_tool as biophysics
from src.agents import designer_agent as designer
from src.agents import evaluator_agent as evaluator
from src.agents import orchestrator
from src.agents import critic_agent as critic
import evaluation
import main as cli


@pytest.fixture(autouse=True)
def no_live_tools(monkeypatch):
    monkeypatch.setattr(generation, "_load_model_with_fallback", Mock(side_effect=RuntimeError("model unavailable")))
    monkeypatch.setattr(evaluator, "esmfold_fold", Mock(side_effect=AssertionError("Unexpected live fold")))


def fake_model(monkeypatch, sequences):
    model = Mock()
    model.generate.return_value = sequences
    tokenizer = Mock(return_value={"input_ids": [1]})
    tokenizer.eos_token_id = 0
    tokenizer.decode.side_effect = lambda value, **kwargs: value
    monkeypatch.setattr(generation, "_load_model_with_fallback", lambda preferred: (model, tokenizer, "test-model"))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=nullcontext))
    return model


def test_model_load_failure_returns_no_sequences():
    result = generation.progen2_generate(generation.ProGen2Input(prompt_sequence="AAA", num_return=2))
    assert result.success is False and result.sequences == []
    assert result.status == "unavailable" and result.model_id == ""
    assert "model unavailable" in result.error


def test_inference_failure_preserves_model_identity(monkeypatch):
    model = fake_model(monkeypatch, [])
    model.generate.side_effect = RuntimeError("inference failed")
    result = generation.progen2_generate(generation.ProGen2Input(prompt_sequence="AAA", num_return=1))
    assert result.sequences == [] and result.status == "unavailable"
    assert result.model_id == "test-model" and "inference failed" in result.error


@pytest.mark.parametrize("sequences", [[], [""], ["AXA"], ["aaa"], ["A A"], ["AAA", "AAA"]])
def test_invalid_decoded_batch_returns_no_candidates(monkeypatch, sequences):
    fake_model(monkeypatch, sequences)
    result = generation.progen2_generate(generation.ProGen2Input(prompt_sequence="AAA", num_return=1))
    assert result.status == "invalid_output" and result.success is False
    assert result.sequences == []


def test_success_preserves_generated_sequence_and_model(monkeypatch):
    sequence = "ACDEFGHIKLMNPQRSTVWY" * 15
    fake_model(monkeypatch, [sequence])
    result = generation.progen2_generate(generation.ProGen2Input(prompt_sequence="AAA", num_return=1))
    assert result.sequences == [sequence] and result.status == "success"
    assert result.success is True and result.model_id == "test-model"


@pytest.mark.parametrize("sequence", ["A" * 121, "A" * 321, "A" * 289 + "X", "a" * 290])
def test_designer_rejects_without_replacing_existing_fasta(tmp_path, monkeypatch, sequence):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    fasta = tmp_path / "outputs/best_0.fasta"
    fasta.write_text(">old\nGGG\n")
    # Exercise the designer even when a provider incorrectly marks bad output as successful.
    monkeypatch.setattr(designer, "progen2_generate", lambda inp: generation.ProGen2Output(
        sequences=[sequence], model_id="test-model", success=True, status="success"))
    with pytest.raises(designer.GenerationFailure):
        designer.design_candidates("query", n=1)
    assert fasta.read_text() == ">old\nGGG\n"
    result = json.loads((tmp_path / "outputs/generation_result.json").read_text())
    assert result["generation_status"] == "invalid_output" and result["passes"] is False


def test_designer_success_never_mutates_or_truncates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sequence = "ACDEFGHIKLMNPQRSTVWY" * 15
    fake_model(monkeypatch, [sequence])
    path = designer.design_candidates("query", n=1)
    assert str(next(SeqIO.parse(path, "fasta")).seq) == sequence
    record = json.loads((tmp_path / "outputs/generation_result.json").read_text())
    assert record["generation_status"] == "success" and record["generation_model"] == "test-model"


@pytest.mark.parametrize("entrypoint", ["cli", "orchestrator"])
def test_generation_failure_stops_before_evaluation(tmp_path, monkeypatch, entrypoint):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs/eval_results.json").write_text('[{"passes": true, "plddt": 99}]')
    target = cli if entrypoint == "cli" else orchestrator
    monkeypatch.setattr(target, "rag_constraints", lambda query: "constraints")
    evaluate = Mock(side_effect=AssertionError("Must not evaluate stale candidates"))
    monkeypatch.setattr(target, "evaluate_batch", evaluate)
    if entrypoint == "cli":
        monkeypatch.setattr(sys, "argv", ["main.py", "--candidates", "1"])
        assert cli.main() == 1
    else:
        result = orchestrator.run_enzyme_atelier("query", n_candidates=1)
        assert result.status == "unavailable" and result.best == {}
        assert result.error
    evaluate.assert_not_called()
    assert not (tmp_path / "outputs/best_0.fasta").exists()
    assert json.loads((tmp_path / "outputs/eval_results.json").read_text()) == []
    summary = json.loads((tmp_path / "outputs/final_summary.json").read_text())
    assert summary["passes"] is False and summary["generation_status"] == "unavailable"


@pytest.mark.parametrize("sequence", ["", "AAA", "A" * 10 + "X", "a" * 10, " AAAAAAAAAA", "AAAAA\nAAAAA"])
def test_biophysics_rejects_input_without_cleaning(sequence):
    result = biophysics.calc_biophysics(biophysics.BioPhysInput(sequence=sequence))
    assert result.status == "invalid_input" and result.success is False
    assert result.ii is result.molecular_weight is result.gravy is result.is_stable is None


@pytest.mark.parametrize("method", ["instability_index", "molecular_weight", "gravy"])
@pytest.mark.parametrize("problem", [RuntimeError("calculation failed"), float("nan")])
def test_calculation_failures_supply_no_partial_or_fake_metrics(monkeypatch, method, problem):
    fake = Mock(side_effect=problem) if isinstance(problem, Exception) else Mock(return_value=problem)
    monkeypatch.setattr(ProteinAnalysis, method, fake)
    result = biophysics.calc_instability("A" * 290)
    assert result["status"] == "unavailable" and result["success"] is False
    assert result["ii"] is result["mw"] is result["gravy"] is result["is_stable"] is None
    assert result["error"]


def test_missing_biopython_is_unavailable(monkeypatch):
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == "Bio.SeqUtils.ProtParam":
            raise ImportError("BioPython unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    result = biophysics.calc_instability("A" * 290)
    assert result["status"] == "unavailable" and result["ii"] is None
    assert "ImportError" in result["error"]


def test_real_biophysics_retains_status_and_metrics():
    result = biophysics.calc_instability("A" * 290)
    assert result["ii"] == pytest.approx(10 * 289 / 290)
    assert result["mw"] > 0 and result["gravy"] == pytest.approx(1.8)
    assert result["success"] is True and result["status"] == "success"
    assert result["source"] == "biopython" and result["is_stable"] is True


def test_biophysics_failure_skips_folding_critique_and_plots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ProteinAnalysis, "instability_index", Mock(side_effect=RuntimeError("broken calculation")))
    (tmp_path / "input.fasta").write_text(">candidate\n" + "A" * 290)
    rows = evaluator.evaluate_batch("input.fasta")
    assert rows[0]["passes"] is False and rows[0]["ii"] is None
    assert rows[0]["fold_status"] == "not_run"
    evaluator.esmfold_fold.assert_not_called()
    rag = Mock(side_effect=AssertionError("Must not critique unavailable measurements"))
    monkeypatch.setattr(critic, "query_rag_for_fix", rag)
    assert critic.critique_eval_results()["action"] == "stop"
    rag.assert_not_called()
    evaluation.plot_metrics()
    summary = json.loads((tmp_path / "outputs/final_summary.json").read_text())
    assert summary["passes"] is False and summary["final_ii"] is None
    assert summary["biophys_status"] == "unavailable"
    assert summary["esmfold_status"] == "not_run"


def test_success_flag_cannot_override_missing_biophysics_provenance(monkeypatch):
    monkeypatch.setattr(evaluator, "calc_instability", lambda seq: {"ii": 20, "is_stable": True, "success": True})
    result = evaluator.evaluate_one("A" * 290)
    assert result["ii"] is None and result["passes"] is False
    evaluator.esmfold_fold.assert_not_called()


def test_failed_generation_report_cannot_reuse_old_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(designer.GenerationFailure):
        designer.design_candidates("query", n=1)
    # Even if a stale evaluation reappears, the recorded failed attempt wins.
    (tmp_path / "outputs/eval_results.json").write_text('[{"passes": true, "ii": 20, "plddt": 99}]')
    evaluation.plot_metrics()
    summary = json.loads((tmp_path / "outputs/final_summary.json").read_text())
    assert summary["generation_status"] == "unavailable"
    assert summary["passes"] is False and summary["final_plddt"] is None
    assert summary["candidate_count"] == 0
