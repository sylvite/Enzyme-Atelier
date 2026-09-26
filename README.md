# Enzyme Atelier - ProGen2 Thermostable PETase Designer

## Supported setup

Use Windows x64 with Python 3.11.9 and the pinned environment described in
[setup and PDF ingestion](docs/setup.md). The local replacement environment is
`venv`; the previous `.venv` is retained. Select `venv/Scripts/python.exe` when
running the commands below. The full documentation rewrite is still pending.

## Current workflow

Launch the local browser interface with:

```powershell
.\venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Start with **Offline demonstration** for a synthetic example without API calls.
The interface includes progress, cancellation, candidate comparisons, evidence,
saved runs, explicit review, and downloads. See the [interface guide](docs/streamlit_ui.md).

The default CLI path designs constrained variants of a pinned PETase reference.
An optional OpenAI planner selects evidence-linked substitutions; Python enforces
sequence, evidence, tool, and budget checks. Passing screening requires explicit
human review before final export. See [reference design](docs/reference_design.md)
for the scientific contract, configuration, and limitations, and
[run workflow](docs/run_workflow.md) for saved artifacts and review.

Run the offline checks without API keys or model downloads:

```powershell
python -m eval.design_scenarios
python -m pytest tests -q -p no:cacheprovider --basetemp venv/test-tmp
```

After configuring `OPENAI_API_KEY`, `OPENAI_MODEL`, and the PDF corpus, this
command explicitly enables billable planner calls and external folding:

```powershell
python main.py --mode reference --enable-api --query "Find evidence-backed PETase stability variants" --max-iter 2 --candidates 1
python main.py --review-run "outputs/runs/<run-id>"
python evaluation.py --run-dir "outputs/runs/<run-id>"
```

Add `--review` to review immediately after screening. The exploratory ProGen2
path is still available with `--mode progen2`. It does not implement the
reference-based scientific contract. No paid calls were made during Stage 3
implementation. The submission-era sections below await the planned rewrite.

## Tool-result integrity

Folding failures now return `plddt: null`, `fold_status: unavailable`, and
`passes: false`. The folding wrapper sends the full candidate once per attempt,
records attempts/errors, and requires a matching full-sequence PDB response.
It no longer generates random fallback scores. The critic stops when folding
evidence is unavailable. Reports use explicit provenance; old results without
that provenance are labeled unknown, and no iteration trajectory is invented.

Generation failures return an empty batch with an explicit error. The designer
rejects invalid batches without padding, truncating, deleting residues, or
injecting substitutions. Valid generated sequences are saved unchanged.
Each run records generation status and model identity in its iteration folder;
failed generation stops the CLI with a nonzero exit code. Existing runs and
historical artifacts remain untouched.

Biophysics uses BioPython measurements only. Invalid input or a calculation
failure returns missing metrics with a recorded status/error, skips folding,
and cannot pass evaluation. The critic does not propose biological redesigns
based on unavailable measurements. Existing historical FASTA files are preserved
on failure; they must not be interpreted as output from the failed attempt.

The parser defaults to the 0–100 B-factor convention in the
[official ESM example](https://github.com/facebookresearch/esm#esmfold-structure-prediction).
It never guesses the scale from a low score. Direct wrapper callers can explicitly
set `plddt_scale=1` for a verified provider using normalized values. Live endpoint
availability and scale have not been verified during this repair.

Run the offline regression suite from the project root:
`python -m pytest tests -q`.

Verification: the offline suite covers tool failures, backend/CLI parity,
isolated concurrent runs, and approval/export behavior. No live generation or
folding was performed during these repairs.

This is still a project under repair. The local Transformers/tokenizers conflict,
scientific validation, and evidence-conditioned generation remain outstanding.
See [the baseline audit and repair updates](docs/project_audit.md).
The submission-era notes and reference metrics below describe the old demo;
they are not validation of the repaired application. In particular, their
random-fallback behavior and production-ready claims are obsolete.

Repair work and regression tests were implemented with Codex assistance; the
AI-assistance paragraph in the historical notes describes the original submission.

## Original submission notes (historical)

Agentic AI system that designs thermostable PETase variants using ProGen2 + ESMFold. Demonstrates 8 agentic patterns with production-ready evaluation (Week 9).

## Model Choice
- **Specialist Biology LLM**: `hugohrban/progen2-small` (151M) generative model via HuggingFace Transformers local inference. Fallback chain handles Salesforce/progen2-small 404 removal (attempt Salesforce/progen2-small -> hugohrban/progen2-small). No API key needed, reproducible. [ProGen2 paper: https://arxiv.org/abs/2206.13384]
- **Folding**: ESMFold API (ESM Atlas) - no key, returns plDDT. 504 Gateway Timeout expected under load -> fallback plDDT 56-73 + 3 retries demonstrates MLOps resilience.
- **Biophysics**: BioPython Instability Index II<40 fast filter (no API), MW, GRAVY.
- **RAG**: ChromaDB vector store, 3 chunks retrieved per failure.
- **No reasoning LLM used**: System is rule-based + generative biology model, no Gemini/Claude API required. This reduces cost and makes demo reproducible offline except ESMFold.
- **Limitations**: progen2-small CPU quality lower than base (764M needs 8GB GPU), ESMFold rate-limited ~20 req/min, transformers==4.32.0 pinned due to ProGenConfig legacy fields n_layer.

## Setup
1. Clone repo
2. `python -m venv .venv && source .venv/bin/activate` (Python 3.11 required, 3.12 fails tokenizers wheel)
3. `pip install -r requirements.txt`
4. `cp .env.example .env` - HF_TOKEN optional for ProGen2 download, no GEMINI_API_KEY needed (no reasoning LLM)
5. Place 5 PDFs in `data/corpus/` for RAG (open-access only, see below)

## How to Run Demo
```bash
# Clean stale artifacts from previous failed runs (important)
rm -rf outputs/critique.json outputs/plots/iteration_ii.png outputs/eval_results.json

# Demo - 2 iterations max, 1 candidate
python main.py --query "Design a thermostable PETase for 70C reactor" --max-iter 2 --candidates 1
```
Outputs to outputs/:

    best_0.fasta (290 AA enforced, cleaned from initial 121 AA)
    eval_results.json (II, plDDT, PASS/FAIL)
    final_summary.json (dynamic status real vs fallback)
    episodic_log.jsonl (traces)
    critique.json (only if FAIL, not present on clean PASS)
    plots/ii_vs_plddt.png, plots/iteration_ii.png, plots/rag_evidence.txt, plots/eval_table.csv

Two reference runs included (demonstrate both resilience and success):

    console2.txt - FAIL->retry path (resilience demo): Iter1 ProGen2 121 AA -> cleaned 290 AA enforced, II 40.9 FAIL (>=40), RAG retrieved D186N "1.86x and 3.69x at 30 and 40 degC", Critic proposes N233C/S282C + D186N, Iter2 II 76.3 FAIL, ESMFold 504 x3 retries -> fallback keeps loop alive. Shows paywall handling + API failure handling + length enforcement. critique.json present, iteration_ii.png shows FAIL->retry.
    console3.txt - Clean PASS path (happy path): Iter1 II 38.16 <40 PASS + ESMFold Success avg plDDT 83.1 >70 PASS, SUCCESS at iteration 1, no critique invoked (correct). final_summary.json shows real ESMFold API not fallback. ii_vs_plddt.png shows green dot in PASS quadrant. Stale critique.json 

## How to Run Tests
```bash
pytest tests/test_tools.py tests/test_agents.py -v
# 5+ tests covering guardrails, biophysics, RAG recall, ESMFold fallback, trajectory assertions
```

## How to Run Evaluation
```bash
python evaluation.py
# Handles both paths: clean PASS (no critique) vs FAIL->critic loop
# Fixes Windows cp1252 \u25e6 white bullet degree char via sanitize_text() + utf-8 encoding
```

## AI Assistance
Used Meta AI for coding assistance with boilerplate tool wrappers and evaluation.py plot fixes (Windows cp1252 \u25e6). All agent logic, RAG corpus selection (Brott 2022, Qu 2024 replacing Son 2019), ProGen2 fallback chain, II/plDDT evaluation design, guardrail logic, and Week 9 framing is own work.

## Project Structure
See docs/architecture.md for system diagram and patterns-used map. Main entry main.py is thin wrapper (10 lines) calling src/agents/orchestrator.py engine.

## Limitations & Dependency Resolution
HF Hub 404: Salesforce/progen2-* removed -> mitigated with fallback chain hugohrban/progen2-small + hf_search_tool
tokenizers wheel: 0.13.3 no py3.12 wheel on Windows -> requires Rust -> resolved py3.11 venv
transformers compat: ProGenConfig n_layer vs num_hidden_layers on >=4.33 -> pinned to 4.32.0
ESMFold 504: public API overloaded -> fallback 56-73 + retry = resilience not failure
Stale artifact issue: critique.json and iteration_ii.png left over from failed runs if not cleaned - fixed by cleanup at start of orchestrator (rm stale) + dynamic detection is_clean_pass in evaluation.py (if PASS, remove stale iteration_ii.png, create SUCCESS plot)
Unicode \u25e6: white bullet misread for degree symbol from PDF extraction -> sanitize_text() replaces \u25e6, °, ◦ with "deg" + utf-8 encoding errors="replace"
Final env: Python 3.11 + transformers 4.32.0 + hugohrban/progen2-small + BioPython + Chroma

## RAG Corpus - Open-Access Strategy (Paywall Resilience)
Due to paywall restriction on Son et al 2019 (abstract only), corpus adapted to open-access alternatives covering same mechanisms:

    Joo et al 2018 - PETase structure, catalytic triad S160-D206-H237, disulfide DS1 (43-58)
    Brott et al 2022 - Systematic evaluation of thermostable IsPETase variants, Tm via disulfide N233C/S282C and salt bridges (DOI: 10.1002/elsc.202100105) - REPLACES Son 2019, CC-BY
    Qu et al 2024 - D186N mechanism, salt bridge stabilization (DOI: 10.3390/molecules29061338), 1.86x/3.69x at 30/40C
    Mandani et al 2023  - Large language models generate functional protein sequences across diverse families
    Nijkamp et al 2023 - ProGen2: Exploring the boundaries of protein language models

All CC-BY or PMC open-access, reproducible RAG without paywall. Example chunk: "PETaseD186N had highest degradation efficiency... at 30 and 40 degC"

## Evaluation (Week 9 Addendum - Module A+B)
See architecture.md §3b for full Week 9 mapping. Summary:

    Outcome+Trajectory deterministic assertions (len 240-320, canonical AA, triad preserved, RAG 3 chunks, ESM retries <=3)
    RAGAS: Recall@5=0.75, Precision=1.0, Faithfulness PASS, Answer Relevance PASS
    Guardrails: Input/Output/Action, Traces episodic_log.jsonl, Alerts groundedness<92% 15min, Cost per success total/successful including retries

## Reference runs (committed in docs/reference_runs/ for reproducibility):**
- `docs/reference_runs/console2_FAIL_retry_504_fallback.txt`
- `docs/reference_runs/console3_PASS_II38_plDDT83.txt`
