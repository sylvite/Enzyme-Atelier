# Local Streamlit interface

From the project root, using the environment in [setup](setup.md):

```powershell
.\venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open http://127.0.0.1:8501. The app defaults to **Offline demonstration**.
Click **Start run** to exercise the real orchestration loop with synthetic
evidence and measurements, including a revision after low confidence. This mode
needs no API key, corpus ingestion, model download, or external service. It is
visibly labeled synthetic and cannot approve final scientific exports.

## Workflows

- **Reference design** uses the pinned PETase sequence and the same backend as
  the CLI. Configure `OPENAI_API_KEY` in your local `.env`, ingest the PDF corpus,
  enter an OpenAI model ID, and explicitly enable paid planner calls for the run.
  See [reference design](reference_design.md) for configuration and limitations.
  Live runs also send sequences to the folding service. Starting a new run resets
  the payment opt-in; opening or refreshing results never invokes the planner.
- **Exploratory ProGen2** loads the pinned sequence model and uses external
  folding. It supports multiple candidates but does not constrain mutations to
  the PETase reference. First use may require model downloads and substantial
  local memory. It does not invoke the OpenAI planner.

Live integrations were not exercised during Stage 4 verification.

## Progress, results, and review

The interface reads saved checkpoints and events every two seconds. It presents
candidate measurements, a wild-type comparison when available, sequences,
mutation evidence with source/page/quotes, planner decisions, and failure states.
Missing measurements display as unavailable. pLDDT is prediction confidence and
the instability index is a proxy; neither demonstrates thermostability or PET
degradation performance.

For an eligible real run, check that you reviewed the candidate and its evidence
before **Approve and export**, or reject it. The backend revalidates the saved
candidate before export. Downloads include a JSON record and a ZIP of recorded
artifacts; the ZIP can include unapproved intermediate sequences. Final approved
FASTA/PDB files have separate download buttons. Archives are limited to 100 MB.

The sidebar opens existing runs without restarting tools. UI runs live under
`outputs/runs/ui/<job-directory>/<run-id>`; CLI runs in `outputs/runs` are also
discoverable. `ATELIER_OUTPUT_ROOT` can override the output directory.

## Job behavior and local-use boundary

Each submission has a stable token, so Streamlit rerenders cannot submit it twice.
Each session can have one active job, with at most two active jobs in the server.
Jobs use separate output directories and a session cannot cancel another session's
job. The saved-run library is shared: this is a local single-user application,
not a multi-user authorization system. The checked-in server configuration binds
to `127.0.0.1`; public deployment and authentication are outside this stage.

**Cancel run** requests cancellation at the next tool boundary. An in-flight model
or network call must return before cancellation finishes; completed measurements
are preserved. Cancellation cannot undo API charges already incurred.

Workers continue through Streamlit rerenders and browser disconnection while the
server process remains alive. A full browser refresh can lose the session's job
controls; results remain accessible through the sidebar. Restarting the server
does not resume interrupted jobs. A saved `running` record without an attached
worker is labeled accordingly and never restarted automatically.

## Verification

Stage 4 tests cover duplicate submission, concurrent session isolation, tool-boundary
cancellation, incomplete event lines, offline demonstration, paid-call opt-in,
unavailable metrics, explicit approval/rejection, and archive preparation using
Streamlit AppTest and controlled backend fixtures. No paid calls are made.

```powershell
.\venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp venv/t4
```
