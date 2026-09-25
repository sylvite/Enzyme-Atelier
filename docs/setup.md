# Reproducible local setup

Supported baseline: **Windows x64, Python 3.11.9**, CPU inference. Other operating
systems, Python versions, and GPU installations have not been verified.

## Environment

Run these commands from the project root in PowerShell. `venv` is separate from
any older `.venv`; select `venv\Scripts\python.exe` as the PyCharm interpreter.
If Python 3.11 is not registered with `py`, use its full executable path instead.

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install --use-feature=truststore -r requirements-lock.txt
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp venv/test-tmp
.\venv\Scripts\python.exe main.py --help
```

The truststore option lets the bundled pip 24 use Windows' certificate store;
it does not disable HTTPS verification. Newer pip versions use that store by
default. No activation or PowerShell execution-policy change is necessary.

`requirements.txt` lists direct dependencies. `requirements-lock.txt` captures
all installed runtime/test dependency versions for this baseline. The lock is a
version snapshot, not a cross-platform or wheel-hash lock. After intentional
dependency updates, recreate a separate environment, test, run `pip check`, and
regenerate the lock with `python -m pip freeze`. Do not freeze the old `.venv`.
The supported Transformers/tokenizers pair is 4.44.2 / 0.19.1. Unused LangChain,
LangGraph, and Accelerate dependencies have been removed.

## Models and external services

Generation uses `hugohrban/progen2-small` at revision
`43237a0b733c6629226a079266d2985c9fdce9b7`, including its remote Python code.
The initial load downloads the weights (about 605 MB), configuration, and
`tokenizer.json` into the Hugging Face cache. Later loads reuse them. An optional
`HF_TOKEN` can be supplied in `.env`; the reference-design planner separately requires `OPENAI_API_KEY` and
`OPENAI_MODEL` when explicitly enabled. The loader does not silently change models when loading fails.

The wrapper loads the repository's tokenizer JSON directly and uses ProGen's
forward-sequence start/end markers (`1` and `2`). See the
[upstream sampling code](https://github.com/salesforce/progen/blob/main/progen2/sample.py)
and [pinned model files](https://huggingface.co/hugohrban/progen2-small/tree/43237a0b733c6629226a079266d2985c9fdce9b7).
Generation is stochastic; pinning dependencies does not promise identical
sequences on every run. A successful inference is not evidence of PETase activity.

Folding sends sequences to ESM Atlas over HTTPS. Offline tests mock this service;
they neither send sequences nor download generation/embedding models.

## Ingest the literature

Place text-based PDFs in `data/corpus`, then run:

```powershell
.\venv\Scripts\python.exe -m src.memory.semantic_store --corpus-dir data/corpus --db-path data/chroma
```

The application uses `data/chroma` relative to the project root. Chroma's default
embedding model may download on first ingestion/query. PDF text chunks retain
filename and page metadata. Scanned PDFs need separate OCR. Missing, unreadable,
or textless inputs produce an error before modifying the collection; no canned
paper titles or scientific constraints substitute for missing evidence.

Re-ingestion upserts the supplied filenames and removes their obsolete chunks
only after the upsert succeeds. Other stored papers remain. This is incremental
ingestion, not a full collection replacement, and the upsert/cleanup sequence is
not a database-wide transaction. Keep normal backups of `data/chroma`. Oversized
batches fail explicitly at Chroma's batch limit; large-corpus batching is not yet
implemented. Existing local corpus contents were not rebuilt during this repair.

## Run and report

The reference command below enables billable API calls. First configure the
planner and read the [reference design contract](reference_design.md). Use
`python -m eval.design_scenarios` for offline checks without external calls.

```powershell
.\venv\Scripts\python.exe main.py --mode reference --enable-api --query "PETase thermostability" --candidates 1 --max-iter 1
.\venv\Scripts\python.exe main.py --review-run "outputs/runs/<run-id>"
.\venv\Scripts\python.exe evaluation.py --run-dir "outputs/runs/<run-id>"
```

See [run workflow](run_workflow.md) for statuses, review, and output files.
Reference mode uses structured planning and explicit substitutions. The optional
ProGen2 mode retains metadata-only prose conditioning. Biological performance
validation and a frontend remain subsequent work.

## Verification performed

The separate environment passed `pip check` and the Stage 2C **128 offline tests**.
PDF extraction plus Chroma persistence/query was tested using deterministic test
embeddings. A real CPU inference check used the pinned cached model, seed 42,
prefix `MNFPRASRLM`, and ten new tokens; it completed successfully. This was a
short model compatibility check, not a candidate validation or folding run.
The production embedding download and live folding endpoint remain unverified.

Stage 3 adds reference design, planner, evidence, and scenario tests; see
[reference design](reference_design.md) and the latest audit update.
