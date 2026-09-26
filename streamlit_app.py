"""Local Streamlit frontend. Rendering and polling never start a workflow."""
import io
import json
import os
from pathlib import Path
from uuid import uuid4
import zipfile

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

from src.agents.orchestrator import review_run
from src.agents.evaluator_agent import recorded_biophys_success, recorded_fold_success
from src.run_store import load_result
from src.ui_jobs import JobManager, JobRequest, read_events, saved_runs

load_dotenv()
st.set_page_config(page_title="Enzyme Atelier", page_icon="🧬", layout="wide")
OUTPUT_ROOT = Path(os.getenv("ATELIER_OUTPUT_ROOT", "outputs/runs")).resolve()


@st.cache_resource
def get_manager(root):
    return JobManager(Path(root) / "ui")


manager = get_manager(str(OUTPUT_ROOT))
for key, value in {"owner": uuid4().hex, "submission": uuid4().hex,
                   "job_id": None, "selected_run": None, "completion_seen": False}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def job_snapshot():
    if not st.session_state.job_id:
        return None
    try:
        return manager.snapshot(st.session_state.owner, st.session_state.job_id)
    except ValueError:
        return {"done": True, "error": "The worker is no longer attached. Open its saved run; it will not restart automatically.",
                "cancel_requested": False, "run_dir": None}


def prepare_new_run():
    st.session_state.job_id = None
    st.session_state.submission = uuid4().hex
    st.session_state.completion_seen = False
    st.session_state.allow_paid = False


def metric_text(value):
    return "Unavailable" if value is None else f"{value:.2f}"


def result_views(result):
    if result.config.simulation:
        st.warning("SYNTHETIC DEMONSTRATION — measurements and evidence are fixtures, not scientific results. Export approval is disabled.")
    elif result.config.mode == "progen2":
        st.info("Exploratory ProGen2 screening. These candidates are not constrained variants of the PETase reference.")
    st.subheader(result.status.replace("_", " ").title())
    st.caption(f"Run {result.run_id} · {result.config.mode} · approval: {result.approval}")
    st.write(result.config.query)
    if result.error:
        st.error(result.error)
    if result.stop_reason:
        st.caption("Outcome: " + result.stop_reason.replace("_", " "))
    overview, candidates, decisions, downloads = st.tabs(["Overview", "Candidates & evidence", "Decision log", "Downloads"])
    rows = [row for batch in result.history for row in batch]
    with overview:
        cols = st.columns(4)
        best = result.best
        cols[0].metric("Candidates evaluated", len(rows))
        cols[1].metric("Selected pLDDT", metric_text(best.get("plddt") if recorded_fold_success(best) else None))
        cols[2].metric("Selected instability index", metric_text(best.get("ii") if recorded_biophys_success(best) else None))
        cols[3].metric("Iterations evaluated", len(result.history))
        st.caption("pLDDT is prediction confidence. Instability index is a screening proxy. Neither establishes melting temperature or PET degradation performance.")
        baseline_path = result.run_dir / "baseline.json"
        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            st.write("**Wild-type comparison**")
            st.dataframe(pd.DataFrame([
                {"Candidate": "Wild type", "pLDDT": baseline.get("plddt") if recorded_fold_success(baseline) else None, "Instability index": baseline.get("ii") if recorded_biophys_success(baseline) else None},
                {"Candidate": "Selected variant", "pLDDT": best.get("plddt") if recorded_fold_success(best) else None, "Instability index": best.get("ii") if recorded_biophys_success(best) else None},
            ]), hide_index=True, width="stretch")
        if rows:
            table = [{"Candidate": row.get("candidate_id"), "Iteration": row.get("iteration"),
                      "pLDDT": row.get("plddt") if recorded_fold_success(row) else None,
                      "Instability index": row.get("ii") if recorded_biophys_success(row) else None,
                      "Screening passed": row.get("eligible", False), "Folding": row.get("fold_status"),
                      "Biophysics": row.get("biophys_status")} for row in rows]
            st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        else:
            st.info("No candidate measurements have been recorded yet.")
        with st.expander("Run settings and budgets"):
            st.json(result.config.model_dump())
    with candidates:
        if not rows:
            st.info("Candidate sequences and supporting evidence appear here after evaluation.")
        for row in rows:
            with st.expander(str(row.get("candidate_id", "Candidate")), expanded=row.get("candidate_id") == result.best.get("candidate_id")):
                st.write(row.get("reason", "No evaluation explanation recorded"))
                if row.get("substitutions"):
                    st.caption("Mutation positions use the full precursor numbering; the sequence below is the mature chain.")
                    sources = {item["evidence_id"]: item for item in row.get("evidence", [])}
                    for mutation in row["substitutions"]:
                        source = sources.get(mutation["evidence_id"], {})
                        st.write(f"**{mutation['original']}{mutation['position']}{mutation['replacement']}**")
                        st.text(f"{source.get('source', 'Unknown source')} · page {source.get('page', 'unknown')}")
                        st.text(mutation["quote"])
                st.code(row.get("sequence", ""), language=None, wrap_lines=True)
    with decisions:
        entries = sorted((result.run_dir / "decisions").glob("*.json"))
        for path in entries:
            if path.stem.endswith("_input"):
                continue
            entry = json.loads(path.read_text(encoding="utf-8"))
            decision = entry["decision"]
            st.write(f"**Decision {path.stem}: {decision['action']}**")
            st.text(decision["reason"])
            with st.expander(f"Details for decision {path.stem}"):
                st.json(entry)
        with st.expander("Recorded events", expanded=not entries):
            st.json(read_events(result.run_dir))
    with downloads:
        if result.status == "running":
            st.info("Downloads become available when the run finishes or stops for review.")
        else:
            st.download_button("Download run record (JSON)", result.model_dump_json(indent=2),
                               file_name=f"{result.run_id}.json", mime="application/json", on_click="ignore")
            if result.status == "approved" and not result.config.simulation:
                for name in result.exported_files:
                    path = (result.run_dir / name).resolve()
                    if path.is_relative_to(result.run_dir.resolve()) and path.is_file():
                        st.download_button(f"Download {path.name}", path.read_bytes(), file_name=path.name,
                                           key=f"export-{result.run_id}-{path.name}", on_click="ignore")
            else:
                st.caption("Final FASTA/PDB exports require approval of a real screening run.")
            if st.button("Prepare complete run archive", key=f"archive-{result.run_id}"):
                try:
                    st.session_state[f"archive-{result.run_id}-data"] = run_archive(result.run_dir)
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
            archive = st.session_state.get(f"archive-{result.run_id}-data")
            if archive:
                st.download_button("Download run archive (ZIP)", archive, file_name=f"{result.run_id}.zip",
                                   mime="application/zip", on_click="ignore")
                st.caption("The archive includes intermediate, unapproved artifacts and recorded evidence.")
    if result.status == "pending_review" and not result.config.simulation:
        st.divider()
        st.subheader("Review selected candidate")
        st.caption("Review the selected sequence, paper context, numbering, and measurements above. Approval permits export; it is not a claim of experimental success.")
        checked = st.checkbox("I have reviewed the selected candidate and its evidence", key=f"review-check-{result.run_id}")
        yes, no = st.columns(2)
        approve = yes.button("Approve and export", disabled=not checked, type="primary", key=f"approve-{result.run_id}")
        reject = no.button("Reject candidate", key=f"reject-{result.run_id}")
        if approve or reject:
            try:
                review_run(result.run_dir, approved=approve)
                st.session_state.pop(f"archive-{result.run_id}-data", None)
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))


def run_archive(directory):
    files = [path for path in directory.rglob("*") if path.is_file()
             and path.suffix in {".json", ".jsonl", ".fasta", ".pdb", ".csv", ".png", ".txt"}
             and not any(part.startswith(".") for part in path.relative_to(directory).parts)
             and path.resolve().is_relative_to(directory.resolve())]
    if sum(path.stat().st_size for path in files) > 100 * 1024 * 1024:
        raise ValueError("This run exceeds the 100 MB browser archive limit. Open its local folder instead.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(directory))
    return buffer.getvalue()


st.title("Enzyme Atelier")
st.caption("Explore evidence. Propose a variant. Review the results.")

with st.sidebar:
    st.header("Saved runs")
    records = saved_runs(OUTPUT_ROOT)
    selected = st.selectbox("Open a saved run", [None] + [str(result.run_dir) for result in records],
                            format_func=lambda path: "Select a run" if path is None else next(
                                f"{'Demo · ' if item.config.simulation else ''}{item.run_id[:8]} · {item.status}"
                                for item in records if str(item.run_dir) == path), key="saved-choice")
    if st.button("Open selected run", disabled=selected is None):
        st.session_state.selected_run = selected
    st.caption("Saved runs are local to this project. Opening one does not restart tools.")
    st.button("Refresh saved runs")

snapshot = job_snapshot()
submitted = st.session_state.job_id is not None
with st.expander("Start a run", expanded=not submitted):
    mode_label = st.radio("Workflow", ["Offline demonstration", "Reference design", "Exploratory ProGen2"],
                          disabled=submitted, horizontal=True, key="workflow")
    mode = {"Offline demonstration": "demo", "Reference design": "reference", "Exploratory ProGen2": "progen2"}[mode_label]
    if mode == "demo":
        st.info("Try a two-iteration example with synthetic evidence and measurements. No downloads, API charges, or external tool calls.")
    elif mode == "reference":
        st.caption("Uses the pinned PETase reference and your ingested PDF corpus. Requires OPENAI_API_KEY in .env.")
    else:
        st.caption("Loads the pinned ProGen2 model and sends generated sequences to the folding service. This mode does not use reference-based mutation constraints.")
    query = "Find evidence-backed PETase stability variants"
    iterations, actions, retrievals, count = 2, 8, 3, 1
    model, enabled = "", False
    with st.form("new-run"):
        if mode != "demo":
            query = st.text_area("Design request", query, disabled=submitted)
            iterations = st.number_input("Maximum variant iterations", 1, 10, 2, disabled=submitted)
        if mode == "progen2":
            count = st.number_input("Candidates per iteration", 1, 20, 1, disabled=submitted)
        if mode == "reference":
            model = st.text_input("OpenAI model ID", os.getenv("OPENAI_MODEL", ""), disabled=submitted)
            enabled = st.checkbox("Allow paid OpenAI planner calls for this run", disabled=submitted, key="allow_paid")
            with st.expander("Planner budgets"):
                actions = st.number_input("Maximum planner decisions", 1, 30, 8, disabled=submitted)
                retrievals = st.number_input("Maximum retrievals", 1, 10, 3, disabled=submitted)
        start = st.form_submit_button("Start run", type="primary", disabled=submitted)
    if start:
        try:
            request = JobRequest(mode=mode, query=query, max_iterations=int(iterations), n_candidates=int(count),
                                 max_actions=int(actions), max_retrievals=int(retrievals), model=model, api_enabled=enabled)
            job_id = manager.start(st.session_state.owner, st.session_state.submission, request)
            st.session_state.job_id = job_id
            st.session_state.selected_run = None
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
if snapshot and snapshot["done"]:
    st.button("Prepare another run", on_click=prepare_new_run)


@st.fragment(run_every=2.0)
def monitor():
    current = job_snapshot()
    if current:
        if current["run_dir"] and st.session_state.selected_run is None:
            st.session_state.selected_run = str(current["run_dir"])
        if current["error"]:
            st.error(current["error"])
        if not current["done"]:
            events = read_events(current["run_dir"]) if current["run_dir"] else []
            label = events[-1]["event"].replace("_", " ").capitalize() if events else "Preparing run"
            with st.status(label, state="running", expanded=True):
                for event in events[-4:]:
                    st.text(event["event"].replace("_", " "))
            if current["cancel_requested"]:
                st.info("Cancellation requested. Waiting for the current tool call to finish; no further tools will start.")
            if st.button("Cancel run", disabled=current["cancel_requested"]):
                manager.cancel(st.session_state.owner, st.session_state.job_id)
                st.rerun()
        elif not st.session_state.completion_seen:
            st.session_state.completion_seen = True
            st.rerun()
    directory = st.session_state.selected_run
    if directory:
        try:
            path = Path(directory).resolve()
            if not path.is_relative_to(OUTPUT_ROOT):
                raise ValueError("Select a run inside this project's output directory")
            result = load_result(path)
            if result.status == "running" and (not current or current["done"] or current["run_dir"] != path):
                st.warning("This saved run is still marked running but is not attached to this session. It will not restart automatically.")
            result_views(result)
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"Could not read this saved run: {exc}")
    elif not current:
        st.info("Start an offline demonstration, configure a design run, or open a saved result from the sidebar.")


monitor()
