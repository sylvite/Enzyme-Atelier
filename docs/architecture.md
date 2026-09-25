# Architecture Document - Enzyme Atelier

> Current implementation: the CLI and evaluation harness call one backend in
> `src/agents/orchestrator.py`, which owns per-run state and artifacts, passes
> component results in memory, and requires human approval before final export.
> See [the current run workflow](run_workflow.md) for commands, statuses, storage,
> and tested behavior. See [setup](setup.md) for the pinned model/environment.
> Obsolete file adapters and unused framework dependencies have been removed. The submission-era design below remains a historical
> reference until the planned full documentation rewrite.

## Reference-design implementation

The default CLI path now runs a bounded planner/controller loop over a pinned
PETase reference. The planner chooses retrieve, revise, or stop; the controller
owns validation, exact sequence construction, evaluation, budgets, and human
review. The OpenAI Responses adapter is optional and requires explicit API
enablement. See [reference design](reference_design.md) for coordinates, protected
residues, evidence checks, action records, and the synthetic evaluation/ablation.
This is the current behavior; the historical diagram below is not its specification.

## 1. Problem Statement
Natural PETase unstable above 40C, need 70C for industrial PET recycling. Build agent that designs thermostable variants using ProGen2 + computational validation.

## 2. System Architecture
```
User Query -> Planner (ReAct) -> RAG Agent [ChromaDB + MCP:UniProt] 
-> Designer Agent [Tool: ProGen2] -> Shared Workspace (candidate_board)
-> Evaluator Agent [Parallel: ESMFold + Biophys] 
-> Critic Agent [Reflection]
-> Guardrail [Pydantic + HITL]
-> Output: .fasta + .pdb + citations
```

## 3. Agentic Patterns Used
See table in prior discussion. We implement 6 patterns:
- Tool Use (3 tools) + MCP
- RAG with citations
- Reflection / Self-Critique (loop max 3)
- Multi-Agent + Planning + Parallelization
- Memory Management: semantic (Chroma rules), episodic (past runs), shared workspace (LangGraph state)
- Guardrails + Evaluation Harness + Human-in-the-Loop

## 3b. Week 9 Evaluation Design (Added after Week 9 materials)
- **Assertion vs Judge decision (Slide 10)**: Deterministic for len/canonical/triad/II/plDDT, no LLM judge needed. Every failure becomes a test.
- **RAG Evaluation (RAGAS)**: Recall@5, Precision@k, Faithfulness, Answer Relevance - split retriever vs generator failure
- **Guardrails are runtime controls (Slide 15)**: Input/Output/Action guards, eval measures, guard constrains
- **Traces**: state, decisions, evidence, approvals, cost - episodic_log.jsonl
- **Alerts**: signal+threshold+window+severity+owner+response
- **Cost per successful task**: total cost / successful tasks includes retries, failed runs, retrieval

## 4. Key Design Decisions
1. **Local ProGen2 vs API**: Use open weights `Salesforce/progen2-small` for reproducibility and cost. Trade: needs GPU for base model.
2. **Parallel eval**: Fan-out to ESMFold API cuts time 5x. Need retry + rate-limit handling.
3. **Pydantic guardrail before export**: Blocks invalid AA, pathogen motifs, human-in-the-loop gate.
4. **RAG over papers**: Grounding triad preservation not in LLM weights.

## 5. Model Choice
- Specialist: progen2-small / base via HF Transformers
- Folding: ESMFold Atlas API

## 6. Secret Handling
All keys in .env, .env.example with placeholders, .env in .gitignore. No keys in code/notebook/video.

## 7. Limitations
- ProGen2-small quality lower than ProGen3 3B
- ESMFold pLDDT proxy, not wet lab Tm
- No experimental validation

## 8. Patterns Not Used
- Routing: All queries protein-centric, routing adds complexity. Future V2 will route DNA vs protein (Evo2 vs ProGen2).

### Dependency Resolution Log
- Issue 1: Salesforce/progen2-* removed from HF Hub (404) -> mitigated with fallback chain + hf_search_tool
- Issue 2: tokenizers 0.13.3 has no py3.12 wheel on Windows -> requires Rust -> resolved by moving to py3.11 venv
- Issue 3: ProGenConfig n_layer vs num_hidden_layers on transformers>=4.33 -> pinned to 4.32.0
- Final working env: Python 3.11 + transformers 4.32.0 + hugohrban/progen2-small mirror
