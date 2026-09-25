# Reference design and scientific contract

Stage 3 supports evidence-linked substitutions to a fixed PETase reference.
The OpenAI planner chooses bounded actions; Python validates and executes them.
The default CLI mode is `reference`. The older ProGen2 path remains available
with `--mode progen2` as exploratory sequence screening.

## Reference and coordinates

The checked-in UniProt record is **A0A0K8P6T7**, sequence version 1, retrieved
2026-09-25. Record and sequence SHA-256 checksums are recorded in
`data/references/manifest.json` and checked at load time. The record annotates a
290-residue precursor, signal peptide 1-27, and mature chain 28-290. We evaluate
and export the 263-residue mature chain; mutation labels always use one-based
**full precursor** coordinates. Thus precursor S160 maps to mature residue 133.

Source: [UniProt reference record](https://rest.uniprot.org/uniprotkb/A0A0K8P6T7.json).
The source currently names the organism Piscinibacter sakaiensis; historical
papers use Ideonella sakaiensis. The fixed accession/sequence identifies this
implementation's reference.

A proposed variant is one to three substitutions relative to wild type, with no
insertions, deletions, signal-peptide edits, or sequential implicit parent edits.
The original residue must match the pinned precursor. Catalytic residues S160,
D206, H237 and the annotated disulfide endpoints C203/C239 and C273/C289 are
protected. Duplicate sites, unchanged residues, and previously tested sequences
are rejected before another folding call.

Each substitution needs an evidence ID from this run, a source filename, a page,
and an exact excerpt containing its mutation label, such as `S238F`. This checks
traceability and coordinate consistency. It does **not** prove that a paper
supports the claimed benefit, that its numbering matches this reference, or
that combining individually studied mutations is beneficial. The planner is
instructed to stop or retrieve when those points are ambiguous. Human review
must inspect the paper context. PDFs using only alternative numbering or mutation
notation are not automatically translated. Existing stores without page metadata
must be re-ingested using the current ingestion command before reference design.

## Controller behavior

1. Retrieve and save full excerpts with content-based evidence IDs. Empty evidence
   stops the run; retrieval failure remains unavailable.
2. Evaluate and save the mature wild-type baseline. Missing measurements stop
   before planning; no numerical baseline is substituted.
3. Send the reference, evidence, measurements, previous changes, failure category,
   and remaining budgets to the planner.
4. Validate a structured `retrieve`, `revise`, or `stop` decision. Retrieve uses
   the local corpus only. Revise constructs the exact proposed sequence and
   invokes the evaluator. Evaluate and human review are controller-owned actions;
   the model cannot override the checks or approve exports.
5. Feed measured low-confidence/high-instability outcomes back into planning.
   Each new variant must change the actual evaluator input. Tool failures stop
   rather than being treated as biological evidence for a revision.
6. Passing screening requests human review. The CLI shows changes, exact excerpts,
   sources/pages, and differences from wild type before asking for approval.

Defaults: two variant evaluations, eight planner decisions, three retrievals
including initial retrieval, and one variant per iteration. Limits are persisted
in `config.json`. OpenAI calls have a 2,000-output-token cap, a 90-second read
timeout, and no automatic retry. These are request/count limits, not a dollar
budget. Baseline folding is additional to the variant evaluations; each fold
retains the folding wrapper's bounded attempts. API failure, refusal, incomplete
output, schema failure, invalid action, and interrupted runs cannot produce an
approved export. There is no arbitrary code execution or model-directed URL tool.

## What screening means

The retained exploratory screening thresholds are pLDDT >70 and BioPython
instability index <40, with complete recorded folding coverage. They are not
validated acceptance criteria for industrial PETase performance. A passing
variant need not improve either metric relative to wild type; measured deltas
are recorded separately and shown during review. No conversion to melting
point, thermostability, PET degradation rate, or laboratory success is made.

Keeping a reference scaffold and protected residues establishes sequence
constraints, not preserved activity. Experimental validation and a scientifically
validated ranking model remain outside this implementation.

## Running

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in your local `.env`. Use an API model
available to your account that supports Responses Structured Outputs. No default
model is silently selected. The REST adapter uses the existing `requests`
dependency and [OpenAI's strict JSON schema interface](https://developers.openai.com/api/docs/guides/structured-outputs).
No new SDK or dependency change is required.

The following command **enables billable API calls** and external folding:

```powershell
.\venv\Scripts\python.exe main.py --mode reference --enable-api --query "Find evidence-backed PETase stability variants" --candidates 1 --max-iter 2 --max-actions 8 --max-retrievals 3
```

`--planner-model MODEL_ID` overrides `OPENAI_MODEL`. Supplying a key alone does
not enable API execution: the CLI requires `--enable-api`. No paid calls were
made while implementing or testing this stage. Provider integration has been
tested with mocked HTTP responses; live model compatibility remains to be checked.

For the backend, construct `OpenAIPlanner` explicitly and call
`run_enzyme_atelier(query, mode="reference", planner=planner)`. The Python API
retains its old `progen2` default for caller compatibility; new integrations must
specify `mode="reference"`. Constructing the planner does not call the API;
executing the workflow does. For offline testing, inject a fixture planner and
mock the retrieval/evaluation boundaries.

## Records and exports

Each reference run adds `reference.json`, `baseline.json`, numbered `retrieval/`
records, and `decisions/` inputs/validated outputs to the shared run folder.
Decision records include provider/model, response ID and token usage when
available. API keys are never included. Iteration records retain exact
substitutions, evidence, evaluated sequence, measurements, and baseline deltas.
The export validator reconstructs the sequence from the recorded substitutions.
Approved exports include `design_evidence.json` beside the FASTA and optional PDB.
Existing saved runs remain readable with their original mode/defaults.

## Offline evaluation and ablation

```powershell
.\venv\Scripts\python.exe -m eval.design_scenarios
.\venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp venv/test-tmp
```

The scenario harness runs 15 cases through the actual reference controller with
scripted planners and synthetic retrieval/screening results. Cases cover passing,
feedback-based revisions, unavailable tools/evidence, invalid citations/edits,
protected sites, duplicates, budgets, stop decisions, and additional retrieval.
It saves expectations, actual statuses, raw run records, and an ablation under
`outputs/evaluations/<id>/`.

In the two controlled revision cases, feedback-aware planning reaches fixture
screening passage in 2/2; the same scripted planner with feedback disabled reaches
0/2 and is stopped when it repeats a sequence. This checks that the feedback path
changes execution. It does not measure OpenAI reasoning quality, retrieval quality,
or biological improvement. Synthetic runs are visibly labeled and blocked from
final export. The production corpus and embedding download were not exercised,
and no live folding or paid OpenAI call was performed in this stage.
