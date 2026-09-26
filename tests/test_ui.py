"""Job submission, isolation, cancellation, and Streamlit interaction tests."""
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from eval.design_scenarios import FIXTURE, FixturePlanner, measured, run_case
from src.agents import reference_workflow as workflow
from src.agents.orchestrator import run_enzyme_atelier
from src.evidence import RetrievalResult
from src.run_models import RunConfig
from src.run_store import create_run, save_result
from src.ui_jobs import JobManager, JobRequest, read_events

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


@pytest.mark.parametrize("persistent", [False, True])
def test_checkpoint_replacement_handles_temporary_file_lock(tmp_path, monkeypatch, persistent):
    from src.run_store import write_json
    destination = tmp_path / "result.json"
    destination.write_text('{"old": true}', encoding="utf-8")
    replace = Path.replace
    attempts = []

    def locked(path, target):
        attempts.append(path)
        if persistent or len(attempts) == 1:
            raise PermissionError("fixture lock")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("src.run_store.time.sleep", lambda seconds: None)
    if persistent:
        with pytest.raises(PermissionError):
            write_json(destination, {"new": True})
        assert '"old"' in destination.read_text() and len(attempts) == 5
    else:
        write_json(destination, {"new": True})
        assert '"new"' in destination.read_text() and len(attempts) == 2
    assert list(tmp_path.iterdir()) == [destination]


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    monkeypatch.setattr("requests.post", Mock(side_effect=AssertionError("Unexpected network call")))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL", "")


def wait_job(manager, owner, job_id):
    assert manager._jobs[job_id].done.wait(10), "Background test job did not finish"
    return manager.snapshot(owner, job_id)


def test_duplicate_submission_remains_idempotent_after_completion(tmp_path):
    manager = JobManager(tmp_path)
    request = JobRequest()
    first = manager.start("owner", "token", request)
    wait_job(manager, "owner", first)
    assert manager.start("owner", "token", request) == first
    assert len(list(tmp_path.glob("**/result.json"))) == 1
    with pytest.raises(ValueError, match="cannot be changed"):
        manager.start("owner", "token", request.model_copy(update={"query": "different"}))


def test_api_opt_in_checked_before_job_creation(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    with pytest.raises(ValueError, match="Enable paid"):
        manager.start("owner", "token", JobRequest(mode="reference", model="test-model"))
    assert manager._jobs == {} and not list(tmp_path.iterdir())


def test_concurrent_sessions_are_isolated_and_cannot_cancel_each_other(tmp_path):
    manager = JobManager(tmp_path)
    one = manager.start("one", "token", JobRequest())
    two = manager.start("two", "token", JobRequest())
    with pytest.raises(ValueError, match="not available"):
        manager.cancel("one", two)
    first, second = wait_job(manager, "one", one), wait_job(manager, "two", two)
    assert first["run_dir"] != second["run_dir"]
    assert len(list(tmp_path.glob("**/result.json"))) == 2
    assert not first["error"] and not second["error"]


def test_running_job_blocks_another_submission_and_cancels(tmp_path, monkeypatch):
    entered, released = Event(), Event()

    def blocked(query, *, output_root, cancel_requested, **kwargs):
        result = create_run(RunConfig(query=query), output_root)
        entered.set()
        assert released.wait(10)
        result.status = "cancelled" if cancel_requested() else "no_candidate"
        save_result(result)
        return result

    monkeypatch.setattr("src.ui_jobs.run_enzyme_atelier", blocked)
    manager = JobManager(tmp_path)
    first = manager.start("owner", "first", JobRequest(mode="progen2"))
    try:
        assert entered.wait(5)
        with pytest.raises(ValueError, match="already has"):
            manager.start("owner", "second", JobRequest(mode="progen2"))
        manager.cancel("owner", first)
        assert manager.snapshot("owner", first)["cancel_requested"] is True
    finally:
        released.set()
    snapshot = wait_job(manager, "owner", first)
    from src.run_store import load_result
    assert load_result(snapshot["run_dir"]).status == "cancelled"


@pytest.mark.parametrize("phase", ["before_start", "baseline", "planner", "candidate"])
def test_reference_cancellation_stops_at_tool_boundaries(tmp_path, monkeypatch, phase):
    cancelled = Event()
    if phase == "before_start":
        cancelled.set()
    retrieval = Mock(return_value=RetrievalResult(query="query", status="success", excerpts=[FIXTURE]))
    monkeypatch.setattr(workflow, "retrieve_evidence", retrieval)
    calls = []

    def evaluate(sequence, **kwargs):
        calls.append(sequence)
        if phase == "baseline" or phase == "candidate" and len(calls) == 2:
            cancelled.set()
        return measured(sequence)

    monkeypatch.setattr(workflow, "evaluate_one", evaluate)
    planner = FixturePlanner("screening_pass")
    decide = planner.decide

    def planning(context):
        value = decide(context)
        if phase == "planner":
            cancelled.set()
        return value

    planner.decide = planning
    result = run_enzyme_atelier("query", mode="reference", planner=planner,
                                cancel_requested=cancelled.is_set, output_root=tmp_path)
    assert result.status == "cancelled" and result.approval == "not_requested"
    assert len(calls) == {"before_start": 0, "baseline": 1, "planner": 1, "candidate": 2}[phase]
    assert not (result.run_dir / "exports").exists()
    if phase == "candidate":
        assert len(result.history) == 1  # completed measurement survives cancellation


def test_progen_cancellation_before_generation(tmp_path, monkeypatch):
    cancelled = Event()
    from src.agents import orchestrator

    def retrieve(query):
        cancelled.set()
        return "Recorded evidence"

    monkeypatch.setattr(orchestrator, "rag_constraints", retrieve)
    generation = Mock(side_effect=AssertionError("Must not start generation"))
    monkeypatch.setattr(orchestrator, "generate_candidates", generation)
    result = run_enzyme_atelier("query", output_root=tmp_path, cancel_requested=cancelled.is_set)
    assert result.status == "cancelled"
    generation.assert_not_called()
    assert (result.run_dir / "retrieval.json").exists()


def test_progress_reader_tolerates_inflight_jsonl(tmp_path):
    (tmp_path / "events.jsonl").write_text('{"event":"started"}\n{"event":', encoding="utf-8")
    assert read_events(tmp_path) == [{"event": "started"}]


def button(app, label):
    return next(item for item in app.button if item.label == label)


def app_at(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_OUTPUT_ROOT", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    return app


def test_ui_demo_reruns_do_not_duplicate_work(tmp_path, monkeypatch):
    manager = JobManager(tmp_path / "ui")
    monkeypatch.setattr("src.ui_jobs.JobManager", lambda root: manager)
    app = app_at(tmp_path, monkeypatch)
    button(app, "Start run").click().run()
    wait_job(manager, app.session_state.owner, app.session_state.job_id)
    app.run()
    app.run()
    assert not app.exception
    assert len(list(tmp_path.glob("**/result.json"))) == 1
    assert button(app, "Start run").disabled
    assert not any(item.label == "Approve and export" for item in app.button)
    assert any("SYNTHETIC" in item.value for item in app.warning)
    button(app, "Prepare another run").click().run()
    assert not app.exception and not button(app, "Start run").disabled
    assert app.session_state.allow_paid is False


def test_ui_reference_run_requires_api_consent(tmp_path, monkeypatch):
    app = app_at(tmp_path, monkeypatch)
    app.radio(key="workflow").set_value("Reference design").run()
    button(app, "Start run").click().run()
    assert not app.exception
    assert any("Enable paid" in item.value for item in app.error)
    assert not list(tmp_path.glob("**/result.json"))


def test_ui_saved_unavailable_run_does_not_show_zero_or_approve(tmp_path, monkeypatch):
    result = run_case("folding_unavailable", tmp_path)
    app = app_at(tmp_path, monkeypatch)
    app.selectbox(key="saved-choice").select(str(result.run_dir)).run()
    button(app, "Open selected run").click().run()
    assert not app.exception
    assert next(item for item in app.metric if item.label == "Selected pLDDT").value == "Unavailable"
    assert not any(item.label == "Approve and export" for item in app.button)
    assert len(list(tmp_path.glob("**/result.json"))) == 1


@pytest.mark.parametrize("approve", [True, False])
def test_ui_explicit_review_and_downloads(tmp_path, monkeypatch, approve):
    result = run_case("screening_pass", tmp_path)
    # Test the review UI using fixtures; this is not a scientific result.
    result.config.simulation = False
    save_result(result)
    app = app_at(tmp_path, monkeypatch)
    app.selectbox(key="saved-choice").select(str(result.run_dir)).run()
    button(app, "Open selected run").click().run()
    assert button(app, "Approve and export").disabled
    if approve:
        app.checkbox(key=f"review-check-{result.run_id}").check().run()
        button(app, "Approve and export").click().run()
    else:
        button(app, "Reject candidate").click().run()
    assert not app.exception
    from src.run_store import load_result
    saved = load_result(result.run_dir)
    assert saved.status == ("approved" if approve else "rejected")
    assert bool(saved.exported_files) == approve
    button(app, "Prepare complete run archive").click().run()
    assert not app.exception
    assert app.session_state[f"archive-{result.run_id}-data"][:2] == b"PK"
