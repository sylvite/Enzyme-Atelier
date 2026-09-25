"""Tests of actual critic decisions; retrieval is the mocked external boundary."""
from unittest.mock import Mock
import pytest
from src.agents import critic_agent as critic


def measured_result(**overrides):
    row = {"sequence": "A" * 290, "full_len": 290, "fold_len": 290,
           "fold_status": "success", "fold_source": "esm_atlas", "plddt": 65,
           "biophys_status": "success", "biophys_source": "biopython",
           "ii": 20, "mw": 20000, "gravy": 1.8, "is_stable": True,
           "passes": False, "reason": "FAIL: plDDT 65 <=70"}
    return dict(row, **overrides)


@pytest.mark.parametrize("rows", [[], [measured_result(plddt=85, passes=True)],
                                  [measured_result(plddt=None, fold_status="unavailable")]])
def test_stop_decisions_do_not_query_retrieval(monkeypatch, rows):
    retrieval = Mock(side_effect=AssertionError("No retrieval needed"))
    monkeypatch.setattr(critic, "query_rag_for_fix", retrieval)
    assert critic.critique_results(rows)["action"] == "stop"
    retrieval.assert_not_called()


def test_retry_contains_actual_evidence_and_no_file_dependency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    retrieval = Mock(return_value=(["Recorded evidence excerpt"], [{"source": "paper.pdf"}]))
    monkeypatch.setattr(critic, "query_rag_for_fix", retrieval)
    result = critic.critique_results([measured_result()])
    assert result["action"] == "redesign"
    assert result["evidence"] == [{"text": "Recorded evidence excerpt", "source": "paper.pdf"}]
    assert "Recorded evidence excerpt" in result["new_designer_prompt"]
    assert not (tmp_path / "outputs").exists()


def test_no_evidence_stops_without_inventing_citations(monkeypatch):
    monkeypatch.setattr(critic, "query_rag_for_fix", lambda *args: ([], []))
    result = critic.critique_results([measured_result()])
    assert result["action"] == "stop" and result["rag_sources"] == []
