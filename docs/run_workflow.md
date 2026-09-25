# Running and reviewing Enzyme Atelier

The CLI, evaluation harness, and future UI use the same backend:
`src.agents.orchestrator.run_enzyme_atelier`. A run passes generated candidates
and evaluation results in memory; shared output files are not component inputs.

## Commands

The CLI defaults to reference design. Configure `OPENAI_API_KEY`, `OPENAI_MODEL`,
and the corpus first; the following command explicitly enables billable calls.
See [reference design](reference_design.md) for the scientific contract. Run
`python -m eval.design_scenarios` for offline synthetic checks instead.

From the project root, using the project's Python environment:

```powershell
python main.py --mode reference --enable-api --query "Find evidence-backed PETase stability variants" --max-iter 2 --candidates 1
```

This command records a run under `outputs/runs/<run-id>/`. If a candidate passes
computational screening, the run stops at `pending_review`. It does not export
an approved final candidate. To prompt for review during a new run, add `--review`.

To review that candidate later without repeating model or retrieval calls:

```powershell
python main.py --review-run "outputs/runs/<run-id>"
```

Reference-mode review displays substitutions, evidence excerpts, source pages,
and baseline deltas. The prompt displays the sequence and accepts `y` for approval. Other answers
reject export. Closing input leaves the run pending. Review is final: a rejected
run cannot subsequently be approved through this interface. Repeating the same
decision through the backend is idempotent.

To generate charts and a candidate table from one saved run:

```powershell
python evaluation.py --run-dir "outputs/runs/<run-id>"
```

Reports go into that run's `reports/` directory and do not change its approval
state, final summary, or exported files. Iteration charts use recorded values.

`--output-root PATH` chooses a different parent directory for new runs. The query
must not be blank, iteration count must be a positive integer, and candidate
count must be 1 in reference mode, or 1–20 in exploratory ProGen2 mode. Invalid settings are rejected before tools or run-directory
creation. The default output directories are Git-ignored through `outputs/.gitignore`;
custom output directories are the caller's responsibility.

## Run files

Reference mode adds `reference.json`, `baseline.json`, `retrieval/`, and
`decisions/`; its generation records contain exact substitutions, and exports
include `design_evidence.json`. `retrieval.json` and `critique.json` below are
used by the exploratory ProGen2 path. All other shared storage rules apply.

```text
outputs/runs/<run-id>/
  config.json                 validated request and budgets
  retrieval.json              initial query and returned constraint text
  events.jsonl                timestamped tool boundaries and decisions
  memory.jsonl                full sequence and run-status snapshots
  result.json                 canonical backend result and complete history
  final_summary.json          selected candidate, status, approval, exports
  iterations/
    001/
      generation.json         model, prompt, returned sequences or failure
      candidates.fasta        valid intermediate candidates, not approved exports
      evaluation.json         candidate IDs, measurements, provenance, validation
      critique.json           decision and evidence when critique was requested
    002/...
  exports/                    created only after explicit approval
    best.fasta
    best.pdb                  when a structure was returned
  reports/                    generated only by the reporting command
```

Each run has a unique ID. Existing runs and historical root-level `outputs/`
files are left untouched. If an evaluation fails partway through, generated
sequences remain in `generation.json`; successfully evaluated candidates remain
in the recorded history. An interrupted run gets a `cancelled` checkpoint.

## Outcomes and approval

| Status | Meaning | Final export |
| --- | --- | --- |
| `pending_review` | At least one valid candidate passed recorded screening | None |
| `approved` | An explicit human decision allowed final export | FASTA, optional PDB |
| `rejected` | Human declined export | None |
| `no_candidate` | Measured candidates failed; budget exhausted or critic stopped | None |
| `unavailable` | Required generation or evaluation could not complete | None |
| `invalid_output` | Generated/saved candidate failed validation | None |
| `failed` | An unexpected tool or export error was recorded | None for an unsuccessful export |
| `cancelled` | Execution was interrupted | None |

The CLI returns 0 for approved export, 2 for pending review or argument errors,
and 1 for other completed outcomes. Inspect `status` and `error` in the saved
result to distinguish the precise cause.

Reference variants must also pass exact reference/residue/evidence validation
before evaluation and again before export. Synthetic evaluation runs cannot be
approved. All candidates must pass the length/alphabet validator.
Before export, the backend rechecks that validator, full-sequence folding
provenance, finite biophysics measurements, and the screening thresholds
(`pLDDT > 70`, `II < 40`). A saved PASS flag alone is insufficient. No missing
measurement can pass. The highest-ranked eligible candidate is selected from
all recorded iterations; when none is eligible, the best diagnostic candidate
can still appear in the summary but is never approved for export.

An approval lock prevents concurrent review operations on the same run. Export
files are prepared in a temporary directory and published together, so a failed
write does not expose a partial final export. If a process is forcibly killed
during review, its leftover `review.lock` requires inspection before recovery;
the application does not automatically break locks.

## Backend usage

```python
from src.agents.orchestrator import run_enzyme_atelier, review_run
from src.agents.planner_agent import OpenAIPlanner

result = run_enzyme_atelier(
    "Find evidence-backed PETase stability variants", max_iterations=2, n_candidates=1,
    mode="reference", planner=OpenAIPlanner()  # Executing this run makes API calls.
)
# Display result.best and result.history for a person to review.
# Only after that person explicitly approves:
# result = review_run(result.run_dir, approved=True)
```

The backend never reads console input. An optional `approval_callback(sequence)`
can return an explicit boolean; `None`, unavailable input, or an invalid callback
answer leaves the run pending. A UI can instead render the persisted result and
call `review_run` after its own review interaction.

## Verification and current limits

Run `python -m pytest tests -q` for the offline suite. Integration tests mock
external generation/retrieval/folding, while exercising actual orchestration,
BioPython measurements, validation, storage, reports, and review decisions.

Live generation/folding is not verified by these offline tests. Use the separate
pinned Python 3.11 environment described in [setup](setup.md).
Length/alphabet validation does not establish PETase identity, catalytic activity,
or stability at the requested temperature. Reference mode constrains sequence
changes; experimental validation and scientific performance evaluation remain
separate work.

In exploratory ProGen2 mode, natural-language critique remains generation
metadata. Reference mode instead applies exact evidence-linked substitutions. Missing retrieval is explicitly reported as
unavailable; it no longer supplies canned scientific claims.

Standalone shared-output adapters have been removed. Use the backend and
explicit run directories for generation, evaluation, critique, and reporting.
