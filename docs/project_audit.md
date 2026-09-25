# Enzyme Atelier: baseline audit and repair plan

Audit date: 2026-09-24 (America/Chicago). Scope: local checkout, before application changes.

## Repair update: Stage 3 reference design and bounded planning

Implemented on 2026-09-25 after the user selected reference-based PETase variants
and an optional OpenAI planner, with no paid calls during implementation.

- Saved and checksum-verified UniProt A0A0K8P6T7 (sequence version 1), with a
  mature-chain/precursor coordinate contract. Variants contain one to three
  explicit substitutions; catalytic and annotated disulfide residues are protected.
- Added structured retrieval records with content-bound evidence IDs, complete
  excerpts, and source/page metadata. Missing/misaligned evidence is explicit.
- Added a bounded reference controller with a measured wild-type baseline,
  structured retrieve/revise/stop decisions, exact sequence construction,
  measured failure feedback, duplicate detection, and enforced budgets.
- Added an OpenAI Responses REST adapter with strict structured output,
  refusal/incomplete/error handling, output cap, timeout, no automatic retry,
  provider/model/usage recording, and no implicit API enablement in the CLI.
- Reference mode is the CLI default; the existing Python API default remains
  ProGen2 for backward compatibility. Reference callers pass mode and planner
  explicitly. ProGen2 remains an exploratory mode, not the reference contract.
- Revalidation before export reconstructs the variant from recorded changes and
  evidence. Human review displays substitutions, excerpts, source pages, and
  baseline deltas; approved exports include a design/evidence record.
- Added 15 executable synthetic scenarios plus a feedback ablation, using the
  real controller with fixture tools/planners. Synthetic runs are labeled and
  cannot be approved for export.

Verification: **163 tests passed**; dependency check and CLI help passed. All
**15/15 scenarios** matched their expected outcomes. The two scripted revision
cases passed screening in 2/2 with feedback versus 0/2 without feedback (duplicate
proposals blocked). These are controlled software results, not biological or
live-LLM performance claims. Raw scenario records are saved locally under
`outputs/evaluations/c7829dd6b7804744b636858f17e1e7bc/` and can be regenerated with
`python -m eval.design_scenarios`.

The implementation/offline acceptance scope is complete. No paid OpenAI calls,
production corpus rebuild, live embedding download, or live folding check was
performed. Citation matching does not prove scientific entailment or paper
numbering; experimental benefit is not inferred from screening passage. See
[reference design](reference_design.md) for the full contract and remaining
verification boundaries. Full README/architecture replacement remains deferred.

## Repair update: Step 2C reproducibility and cleanup

Completed on 2026-09-25:

- Built a separate Windows x64 Python 3.11.9 environment at `venv`; the older
  `.venv` and user's root `.gitignore` were retained. Direct requirements are
  pinned, and `requirements-lock.txt` captures the complete installed package set.
- Verified Transformers 4.44.2 / tokenizers 0.19.1 / Torch 2.6.0 compatibility.
  Removed unused LangChain, LangGraph, and Accelerate dependencies.
- Pinned ProGen2-small weights and remote code to revision
  `43237a0b733c6629226a079266d2985c9fdce9b7`. Corrected tokenizer JSON loading and
  sequence delimiters; removed the unverified model-family fallback chain.
  Load failures retain the attempted model/revision identity.
- A real CPU inference check with cached weights generated ten new amino acids
  successfully (seed 42, prefix `MNFPRASRLM`). This verifies the inference stack,
  not PETase identity, scientific performance, or full live end-to-end execution.
- Removed unused tool copies, shared-file agent/report adapters, inactive code,
  and test-local fake implementations. Regression coverage now uses current APIs.
- Added `python -m src.memory.semantic_store` for PDF ingestion. Inputs are parsed
  before database access; upserts retain source/page metadata and do not delete
  the collection. Missing evidence no longer becomes canned titles/citations.
  Existing user corpus data was not modified. Retrieval remains metadata-only
  for generation until Stage 3.
- Added [setup instructions](setup.md), updated current workflow notes, and
  removed unused provider/endpoint settings from `.env.example`. The requested
  full README/architecture rewrite remains deferred.

Verification: **128 offline tests passed**, including PDF extraction and a real
local Chroma ingest/query roundtrip with offline test embeddings. `pip check`
reported no broken requirements; all three documented CLI help commands ran;
the lock-file installation dry run required no changes. Live folding and the
production embedding-model download/retrieval quality were not tested.

## Repair update: Step 2B shared backend and run records

Completed on 2026-09-25:

- `main.py` now adapts CLI arguments to the same backend used by the evaluation
  harness. Query and budget validation occurs before tools or artifact creation.
- Typed configuration/result contracts and unique run directories replace shared
  pipeline filenames. Each iteration retains generation, evaluations, candidate
  identities and critique evidence; timestamped events record decisions.
- Candidate validation runs before evaluation and again before export. Ranking
  considers the entire recorded history. Passing screening creates a pending
  review; approval or rejection is explicit and can occur later without reruns.
- Final exports are published together after approval. Rejection, validation
  failure, missing measurements, and failed writes cannot publish a final export.
- Per-run memory uses valid UTF-8 JSONL and stores full sequences. The reader also
  supports the old concatenated-object format without rewriting historical files.
- Reports take an explicit run directory, plot actual iteration measurements,
  and preserve the authoritative run/approval records. New runtime output folders
  are ignored using `outputs/.gitignore`; the user's root `.gitignore` is unchanged.
- Replaced the critic's inline-mock tests with checks of the real component and
  added backend tests for CLI parity, retries, concurrent runs, interrupted/error
  paths, validation, approval/rejection, saved review, and export-write failures.

Verification: **122 offline tests passed without warnings**. Live models and
services were not invoked. No new dependencies were installed in this stage.
See [run_workflow.md](run_workflow.md) for current commands and known limitations.
Full README/architecture replacement is deferred as requested.

## Repair update: Step 2A tool-result integrity

Implemented after this baseline audit:

- Folding returns explicit status, source, attempt count, coverage and errors.
  Failed or malformed predictions have no score (`null` in JSON), and cannot pass.
- One full-sequence HTTP request per attempt; bounded retries and no sleep after
  the last attempt. Permanent HTTP errors stop immediately.
- Response checks reject missing atoms, invalid confidence/coordinates, and
  mismatched sequence coverage. Confidence scale is explicit, with no heuristic
  inflation of low scores; the default follows the official ESM 0–100 convention.
- Evaluation preserves provenance and handles missing measurements in ranking,
  persistence, and display. The critic stops on unavailable folding evidence.
  Orchestrator ranking and the legacy harness tolerate missing confidence values.
- Reports mark legacy results without provenance as unknown, and no longer infer
  API success from score magnitude or fabricate iteration plots/guardrail passes.
- README now distinguishes repaired behavior from historical submission notes.
- Generation loading/inference failures return no sequences, with explicit status
  and error information. Invalid decoded batches are rejected. The designer
  validates the entire batch before writing and never pads, truncates, deletes
  residues, or injects substitutions. It records the successful model identity.
- A generation failure stops either entry point before evaluation or final export.
  Current generation/evaluation/summary artifacts record the failure, and old
  evaluation results cannot be reported as success for the failed attempt.
  Historical FASTA files are preserved; isolated run directories remain Step 2B.
- Biophysics now uses measured BioPython values only. Invalid inputs and library
  failures return no numeric substitutes, with distinct statuses and errors.
  The evaluator preserves that provenance and skips folding when biophysics is
  unavailable. The critic stops instead of interpreting unavailable evidence as
  a biological failure. Reports and ranking tolerate missing values throughout.

Verification: **82 tests passed**, including 65 new offline regression cases,
with one existing Pydantic validator deprecation warning. HTTP was mocked, and
report/FASTA/JSON artifacts for integration checks were written only in temporary
test directories. Historical project outputs were preserved. `matplotlib` and
`pandas`, already declared in requirements but missing locally, were installed
with their dependencies to exercise real report generation.

Still outstanding: unified backend, export validation/approval, complete run
history, scientific reference/numbering
validation, and the Transformers/tokenizers conflict. Live endpoint availability
and confidence scale have not been verified. The original baseline below is
retained as the record of pre-repair behavior, not a claim that these fixed defects
remain present.

## Conclusion

The repository contains usable tool wrappers, PDF ingestion/retrieval code, and a bounded design/evaluation loop. However, a successful run currently does not establish that generation and folding succeeded, that validation was enforced, or that critique influenced generation. Fix result integrity and execution flow before adding a reasoning agent or UI.

This audit preserves the original submission documents and historical outputs. The pre-existing `.gitignore` modification was left unchanged. No model downloads, live folding calls, corpus re-ingestion, or full pipeline runs were performed. The private `.env` was not displayed. No dependencies were installed or changed.

Evidence labels below distinguish **runtime verified** (an executed local check), **code verified** (inspection of executable source), and **unverified** (requires further evidence). File locations refer to this baseline and may move during repairs.

## 1. What runs today

### Documented CLI

`main.py:13` parses only `--candidates` and `--max-iter`. It deletes selected prior artifacts, retrieves constraints for a fixed query, then repeats generation and evaluation. On failure it calls the critic and chooses one of two fixed prompt strings. It stops at any passing candidate or the iteration limit.

It does **not** call `run_enzyme_atelier`, validate candidates with `PetaseValidator`, request approval, or invoke episodic memory logging. Critique itself appends a separate log when invoked.

### Separate orchestrator

`src/agents/orchestrator.py:18` contains a second loop, called by `eval/eval_harness.py`, not the CLI. It retrieves evidence, generates, evaluates, and optionally critiques. At the end it selects from the last batch, attempts validation, saves a sequence even if validation raises, and attempts episodic logging. The imported human-approval function is unused.

### Reporting

`evaluation.py` reads shared output files and generates plots, a CSV, and a summary. It does not execute the evaluation cases. `eval/eval_harness.py` executes only three defined cases despite its ten-case description; its success predicate expects a `triad` result field that the evaluator never emits.

## 2. Executed checks

All commands used the existing `.venv/Scripts/python.exe` from the project root.

| Check | Result | Meaning |
| --- | --- | --- |
| `-m pytest tests/test_tools.py tests/test_agents.py -v -p no:cacheprovider` | **17 passed**, one Pydantic deprecation warning, 16.60 seconds | Baseline tests are runnable, but their assertions do not cover key integration failures. |
| `main.py --query "Design a thermostable PETase for 70C reactor" --max-iter 2 --candidates 1` | Argument parser rejects `--query` | README demo cannot start as written. Failure occurred before pipeline execution. |
| `-m pip check` | Transformers 4.32.0 requires tokenizers below 0.14; installed version is 0.23.1 | Environment has an actual declared dependency conflict. |
| `import transformers` | `ImportError` for the tokenizers version | Local generation cannot load through the current wrapper in this environment. |
| Real evaluator with mocked biophysics (`ii=20`, stable) and failed folding (`plddt=74`, `success=False`) | `passes=True` | Tool failure can become a successful candidate. |
| Real folding wrapper with HTTP mocked to return 504 and sleeps disabled | Six POST calls for three configured attempts | Two requests occur in each attempt. |
| Real manual instability fallback on `MNFPRASRLM` repeated 29 times | Manual: 0.0; regular BioPython calculation: approximately 23.1348 | Manual fallback does not calculate the same metric. |
| Two real episodic writes to a temporary file, then `load_history()` | `JSONDecodeError: Extra data` | Records are concatenated without JSONL line separators. |
| Real designer called with two different natural-language constraints; generator and file writes mocked | Identical `ProGen2Input` values | Changing critique text does not change generation input. No FASTA was written in this probe. |

Offline probes exercised actual application functions and mocked their external boundaries. They were diagnostic checks, not additions to the permanent test suite. Convert them to regression tests during repairs.

Installed versions observed: Python 3.12.10; Transformers 4.32.0; tokenizers 0.23.1; Pydantic 2.13.4; BioPython 1.88; ChromaDB 1.5.9; Torch 2.13.0; pytest 9.1.1. The README describes Python 3.11, and `requirements.txt` constrains Torch to below 2.4. Thus the current environment is not a reproduction of the documented dependency set. A complete clean installation was not attempted.

## 3. Prioritized findings

### P1: Result integrity and enforced control flow

1. **Failed folding can pass — runtime verified.** `src/tools/esmfold_tool.py:59` supplies a random score between 55 and 75 after failures. `src/agents/evaluator_agent.py:34` ignores `success`; scores above 70 can pass with a low instability index. Preserve explicit failure/unavailable status and use no invented measurement. Simulation must be an explicit mode with simulated provenance.

2. **Failed generation becomes an ordinary candidate — code verified.** `src/tools/progen2_tool.py:102` returns synthetic alanine padding with `success=False`. `src/agents/designer_agent.py:118` uses those sequences without checking success or retaining model/error provenance. The verified Transformers import failure makes this path especially relevant locally. Synthetic fixtures must never masquerade as successful model output.

3. **Validation and approval do not control export — code verified.** `main.py` bypasses both. `src/agents/orchestrator.py:87` catches validation errors and continues to `write_text` at line 97. The designer has already written candidate FASTA files before final validation. Separate intermediate artifacts from approved export; a rejected result must not be labeled an approved final candidate. `human_approval_gate` is never invoked by either path.

4. **Feedback does not change the generator's inputs — runtime verified.** `src/agents/designer_agent.py:125` always constructs the same sequence prefix and generation settings for the same candidate count. Revised prose is only printed and put into FASTA descriptions. The caller also ignores the critic's `new_designer_prompt`. A functional redesign loop requires a defined, testable translation from constraints to actual generation or revision actions.

5. **Summary provenance and trajectories are invented or inferred incorrectly — code verified.** `evaluation.py:107` plots fixed iteration values; line 156 unconditionally reports a passing guardrail; line 160 guesses folding provenance from score magnitude and inserts a fixed 83.1 score into a message. An all-pass final batch is treated as iteration-one success even though iteration information is absent. Generate every claim from recorded run events and tool results.

6. **Biophysics failure paths return misleading values — runtime/code verified.** `src/tools/biophys_tool.py:47` looks up two-letter keys in BioPython's nested dipeptide table, producing zero in the verified probe. Its ultimate fallback returns 35.0, while molecular weight and GRAVY can become fixed constants. `calc_instability` also drops the result's success flag. Preserve unavailable/error states and reject invalid inputs instead of silently cleaning them into a different sequence.

7. **Reported biological checks are absent — code verified.** The active validator checks only length and alphabet. No active catalytic-position check supports the report's triad PASS claims. The designer pads/truncates outputs and applies fixed substitutions using indices 186, 233, and 282; these address one-based positions 187, 234, and 283. There is no reference alignment or verification of the starting residue. Validate the reference sequence, numbering convention, and biological success criteria before implementing these claims. Computational threshold passage must be labeled as such; this code does not measure activity at 70C or melting temperature.

### P2: Reproducibility, data loss, and architecture

8. **CLI and orchestrator diverge — runtime/code verified.** The README's thin-wrapper description is inaccurate, and its query argument fails. Shared backend orchestration should be the single entry point for CLI, evaluation, and later UI. Validate iteration and candidate counts before invoking tools.

9. **Folding requests and sequence coverage are wrong or ambiguous — runtime/code verified.** `esmfold_tool.py:27-30` makes two requests and overwrites the first response. Both the evaluator and wrapper truncate to 250 residues, while reporting the full candidate sequence. Empty/unparseable successful responses default to a numeric confidence of 70.0. Use one request per attempt, explicit coverage and provenance, strict response parsing, and recorded attempt counts. The score-scaling heuristic needs validation against the selected provider's documented output before reuse.

10. **Best selection can replace a passing candidate with a failing one — code verified.** The orchestrator selects a passing candidate, then overwrites `best` by ranking the entire last batch by confidence. Earlier batches are not considered. Empty batches can raise an indexing error; zero iterations leave `i` undefined at export. Define ranking and termination semantics explicitly, including empty results and unavailable tools.

11. **Shared filenames discard history — code verified.** Each generation writes `outputs/best_0.fasta`; each evaluation overwrites `eval_results.json`; the critic reads shared files. CLI cleanup deletes selected logs but can leave an old summary. Concurrent UI sessions would collide. Use a unique run directory, per-iteration candidate IDs, and explicit result objects rather than shared files as messages.

12. **Episodic memory is malformed and unused for decisions — runtime/code verified.** `src/memory/episodic_store.py:14` omits a newline; subsequent reads fail after two writes. It retains only a sequence prefix and score. No active caller uses `load_history` to guide decisions. The critic has a different log in `outputs`. Define durable events separately from any memory used for future decisions.

13. **Retrieval exists, but grounding is incomplete — code verified.** `rag_agent.py:15` queries a Chroma collection and returns snippets with filenames. The critic performs another real query but mixes returned snippets with fixed suggestions and source claims. Retrieval failures return canned constraints. Ingestion (`semantic_store.py:23`) deletes the existing collection before validating the PDFs, and can replace it with paper titles. Metadata stores chunk numbers rather than actual PDF page locations. README setup does not explain invoking ingestion. Preserve explicit source/chunk provenance and distinguish missing evidence from successful retrieval.

14. **Evaluation report is not reproducible from the harness — code verified.** The report lists 12 scenarios and aggregate/ablation results; the executable harness contains three cases and an incompatible success predicate. Several reported controls do not exist in active code. Historical console files are useful artifacts, but do not substantiate all rows. Classify unsupported numbers as unverified/illustrative until fresh, attributable runs produce them; do not treat them as measured baselines.

### P3: Cleanup and honest documentation

15. **Dead/unused code obscures the implementation — code verified.** Multiple modules contain older implementations in triple-quoted strings. `progen2_tool_old.py` is not imported by the active pipeline. `Hf-Search-Tool.py` is unwired and references `Field` without importing it. Its recovery prompt is text, not implemented recovery. Remove or archive only after checking callers and establishing regression coverage.

16. **Architecture claims exceed implementation — code verified.** No active MCP/UniProt integration, LangGraph shared state, ReAct planner, parallel evaluator, alerting window, or enforced HITL workflow was found in the source inspected. LangGraph is listed as a dependency but not used. A module named an agent is not by itself evidence of autonomous planning. Document implemented behavior and mark future capabilities explicitly.

17. **Documentation and dependency cleanup is needed — runtime/code verified.** Test count, Python version, CLI options, fallback ranges, retry/backoff descriptions, and artifact-generation instructions disagree with code or environment. The current folding wait is fixed at five seconds, not exponential. Pydantic emits a deprecated-validator warning. Update the README's AI-assistance attribution as this repair work proceeds.

## 4. Requirements and pattern mapping

The assignment requires at least four patterns, not every listed pattern. The repair should favor a small set implemented end-to-end instead of adding components just to match the old diagram.

| Requirement or claim | Current evidence | Status / next action |
| --- | --- | --- |
| Python 3.11+ and dependency file | Python 3.12 locally; requirements file exists | Language minimum met; dependency compatibility fails. Establish a reproducible environment. |
| Two or more external tools | ProGen wrapper, ESMFold wrapper, BioPython calculations | Implemented wrappers; preserve and test success/failure provenance. Live generation/folding not verified here. |
| RAG | PDF ingestion and Chroma retrieval | Implemented retrieval; corpus freshness and live quality not verified. Generation conditioning incomplete. |
| Reflection | Bounded retry, critique, retrieval | Partial; feedback does not reach generation inputs. |
| Planning | Fixed loops and conditional prompt strings | No implemented reasoning planner found. |
| Multi-agent | Designer/evaluator/critic/RAG modules | Specialized components exist; autonomous-agent interpretation unsupported by current behavior. |
| Parallelization | Thread pool in an inactive string block | Not implemented in active evaluator. |
| Memory, at least two types | Chroma store, in-run history in separate orchestrator, episodic files | Partial; episodic persistence broken and no decision-time recall. |
| Guardrails | Length/alphabet Pydantic validator | Unit behavior exists; not enforced end-to-end. Additional claimed checks absent. |
| Human review | Console input helper | Not wired into either execution path. |
| MCP | Diagram label only | Not implemented; optional unless chosen for the revised design. |
| Five meaningful unit tests | 17 collected tests | Some real unit coverage, substantial false reassurance; replace ineffective tests. |
| Ten evaluation cases and an ablation | Report has 12 scenarios; harness has 3 | Needs executable cases, expected behavior, raw results, and measured comparison. |
| Model/provider/setup documentation | README and requirements | Present but inaccurate/incomplete. |
| Secrets configuration | `.env` ignored; `.env.example` tracked | Basic structure present. No full repository-history secret audit performed. |
| Runnable clean setup | Dependency conflict, missing ingestion instructions, invalid CLI example | Not demonstrated. |
| Architecture document | Existing diagram and decisions | Needs rewrite against actual behavior. |
| Presentation | Grading feedback and local slides file | Video/submission not assessed in this code audit. |

## 5. Test quality assessment

Useful existing tests exercise real BioPython calculations, length validation, canonical validation, and a mocked HTTP failure path. They are a starting point, not sufficient end-to-end assurance.

Specific blind spots:

- Critic tests import a function that exists only in an inactive code block, then substitute a local fake and test that fake.
- RAG recall and faithfulness tests use literal sets/strings; they never query the retriever.
- Trajectory, cleanup, cost, and approval tests assert locally constructed constants rather than observed run behavior.
- Length-enforcement and text-sanitization tests duplicate simplified implementations instead of importing application functions.
- The triad test checks that S, D, and H appear somewhere and checks a field only if it exists; the real result lacks that field.
- Invalid-alphabet tests also use invalid lengths, so a length rejection alone satisfies them.
- The ESMFold test checks score bounds only if a dict has an attribute named `plddt`; it does not, so the assertion is skipped. It also does not check request count or downstream rejection.

## 6. Repair stages and completion criteria

### Stage 2A: Restore trustworthy tool results

First implementation slice: fix folding failure semantics and duplicate requests, propagate status into evaluation, and introduce focused regression tests against the real modules. Remove score-based guesses of provenance in reporting. Keep this slice small enough to review independently.

Acceptance: simulated HTTP failures never count as a successful fold; each configured attempt makes one request; missing/malformed results stay unavailable; summary status comes from explicit tool provenance; offline tests cover both success and failure. Then apply the same principle to generation and biophysics, including removal of silent production substitutes.

### Stage 2B: One backend and durable runs

Introduce typed run/candidate/tool results and configuration. Route CLI through a single backend; accept the query; validate counts; isolate run directories; preserve iteration history; rank only eligible candidates; define no-result and budget-exhausted outcomes. Enforce validation and any chosen approval policy before final export. Repair JSONL and replace file-based inter-component communication.

Acceptance: CLI and backend return the same outcome for deterministic fixtures; invalid candidates cannot become final approved exports; repeated runs cannot overwrite one another; full event history supports reporting; zero/empty/error cases are tested.

### Stage 2C: Reproducibility and cleanup

Choose and verify the supported Python/dependency combination in a separate environment. Document ingestion and offline test setup. Remove obsolete implementations and unused dependencies after confirming references. Update README and architecture to describe actual behavior; preserve submission artifacts as historical evidence.

Acceptance: documented setup works from a clean checkout, offline tests require no model download or service, and every advertised CLI command runs as described. Optional live integration checks are explicitly separate.

### Stage 3: Functional orchestration and scientific contract

Define the supported design task, reference/numbering conventions, admissible candidate transformations, evidence requirements, computational screening criteria, and limits on scientific conclusions. Review these choices with the user before committing to a generation strategy or model provider.

Build structured actions for retrieve, generate/revise, evaluate, review, and stop. Each revision must change a meaningful tool input, with the decision and evidence recorded. If a reasoning model is used, give it bounded actions and validate its structured decisions in ordinary code. Tool failures, retry budgets, and stopping rules must remain deterministic. Do not assume a protein sequence model accepts natural-language engineering instructions.

Acceptance: controlled tests demonstrate different observed failures produce different valid actions; evidence is traceable; loops stop at budgets; improvements are measured rather than inferred from the existence of retries. Implement at least ten executable evaluation scenarios and a reproducible component ablation before making performance claims.

### Stage 4: Streamlit interface

Wrap the same backend with query/configuration inputs, run progress, candidate comparison, evidence, explicit result statuses, review where applicable, and artifact downloads. Design execution so Streamlit reruns cannot accidentally restart a job. Support cancellation and error display.

Acceptance: the UI and CLI share orchestration; separate sessions have isolated artifacts; unavailable or simulated outputs are visibly labeled; displayed summaries derive from saved run results.

## 7. Open questions and verification boundaries

- Live availability and compatibility of the model mirrors and folding endpoint were not checked. Comments that assert availability or compatibility are not evidence.
- Model remote-code revisions and generation/tokenization semantics need explicit verification when choosing a supported model stack.
- The five local PDF filenames and retrieval implementation were inspected; PDF scientific claims, exact mutation evidence, Chroma chunk count, and retrieval quality were not independently validated in this stage.
- Historical run logs are not proof of today's environment or all reported experiments. No historical metrics were regenerated.
- The desired scope remains to be decided: constrained revision of a verified PETase reference versus broader sequence generation. This affects validation and the model/tool design.
- A reasoning provider, acceptable runtime/cost, and deployment target can be selected during Stage 3. None is needed to repair false-success behavior first.

Stage 1 is complete as a baseline code and offline-behavior audit. It does not certify scientific validity or successful live end-to-end execution.
