"""Render recorded screening results without inventing folding provenance."""
from pathlib import Path
import json
import matplotlib.pyplot as plt
import pandas as pd

from src.agents.evaluator_agent import recorded_fold_success, recorded_biophys_success, candidate_sort_key


def load_history():
    """Read existing artifacts; do not run tools or modify the evidence store."""
    def read_json(path, default):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    eval_data = read_json(Path("outputs/eval_results.json"), [])
    critique = read_json(Path("outputs/critique.json"), {})
    path = Path("outputs/episodic_log.jsonl")
    episodic = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return eval_data, critique, episodic


def sanitize_text(text: str) -> str:
    """Keep legacy text exports compatible with Windows cp1252."""
    replacements = {"\u25e6": "deg", "°": "deg", "◦": "deg", "→": "->",
                    "←": "<-", "−": "-", "–": "-", "—": "-", "’": "'", "“": '"', "”": '"'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("cp1252", errors="replace").decode("cp1252")


def report_rows(eval_data):
    """Legacy scores without provenance are unknown, not verified API results."""
    rows = []
    for record in eval_data:
        row = dict(record)
        if not recorded_biophys_success(row):
            row.update(ii=None, mw=None, gravy=None, is_stable=None, passes=False)
            row["biophys_status"] = record.get("biophys_status") if record.get("biophys_status") in ("invalid_input", "unavailable") else "unknown"
            row["reason"] = record.get("biophys_error") or "No verified biophysics result"
        if not recorded_fold_success(row):
            row["plddt"] = None
            row["passes"] = False
            row["fold_status"] = record.get("fold_status") if record.get("fold_status") in ("unavailable", "not_run") else "unknown"
            row["reason"] = record.get("fold_error") or "No verified full-sequence folding result"
        rows.append(row)
    return sorted(rows, key=candidate_sort_key)


def build_summary(eval_data, generation=None):
    """Summarize a selected candidate using recorded status, never score guesses."""
    generation = generation or {}
    failed_generation = generation.get("generation_status") in ("unavailable", "invalid_output")
    rows = report_rows(eval_data) if not failed_generation else []
    best = rows[0] if rows else {}
    return {
        "final_ii": best.get("ii"),
        "final_plddt": best.get("plddt"),
        "passes": bool(best.get("passes", False)),
        "esmfold_status": best.get("fold_status", "not_run" if failed_generation else "unknown"),
        "esmfold_source": best.get("fold_source", "unknown"),
        "esmfold_attempts": best.get("fold_attempts"),
        "esmfold_error": best.get("fold_error", ""),
        "fold_len": best.get("fold_len"),
        "full_len": best.get("full_len"),
        "candidate_count": len(rows),
        "fold_unavailable_count": sum(not recorded_fold_success(row) for row in rows),
        "biophys_status": best.get("biophys_status", "not_run" if failed_generation else "unknown"),
        "biophys_source": best.get("biophys_source", "unknown"),
        "biophys_error": best.get("biophys_error", ""),
        "biophys_unavailable_count": sum(not recorded_biophys_success(row) for row in rows),
        "generation_status": generation.get("generation_status", "unknown"),
        "generation_error": generation.get("generation_error", ""),
        "generation_model": generation.get("generation_model", ""),
        "guardrail": "not recorded",
        "iteration_history": "not recorded in evaluation results",
    }


def plot_metrics():
    """Export final-batch metrics; unavailable measurements are omitted from plots."""
    eval_data, critique, _ = load_history()
    generation_path = Path("outputs/generation_result.json")
    generation = json.loads(generation_path.read_text(encoding="utf-8")) if generation_path.exists() else {}
    if generation.get("generation_status") in ("unavailable", "invalid_output"):
        eval_data = []
    rows = report_rows(eval_data)
    output = Path("outputs/plots")
    output.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4))
    measured = [row for row in rows if recorded_fold_success(row) and recorded_biophys_success(row)]
    for row in measured:
        ax.scatter(row["ii"], row["plddt"], color="green" if row["passes"] else "red")
    ax.axvline(40, color="r", linestyle="--", label="II threshold 40")
    ax.axhline(70, color="g", linestyle="--", label="pLDDT threshold 70")
    ax.set(xlabel="Instability index", ylabel="pLDDT", title="Recorded full-sequence screening results")
    ax.text(0.02, 0.98, f"Unavailable/unverified metric pairs: {len(rows) - len(measured)}",
            transform=ax.transAxes, va="top")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "ii_vs_plddt.png", dpi=150)
    plt.close(fig)
    pd.DataFrame(rows, columns=list(rows[0]) if rows else ["ii", "plddt", "passes", "fold_status"]).to_csv(output / "eval_table.csv", index=False)

    # Replace the old fabricated trajectory chart with an explicit absence notice.
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.axis("off")
    ax.text(0.5, 0.5, "Iteration history unavailable\nNo trajectory can be inferred from the final batch.",
            ha="center", va="center", transform=ax.transAxes)
    fig.tight_layout()
    fig.savefig(output / "iteration_ii.png", dpi=150)
    plt.close(fig)
    evidence = "Recorded critique artifact (run association is not recorded):\n"
    evidence += f"Sources: {critique.get('rag_sources', [])}\n"
    evidence += sanitize_text(critique.get("suggestion", critique.get("reason", "No critique recorded")))
    (output / "rag_evidence.txt").write_text(evidence, encoding="utf-8")
    summary = build_summary(eval_data, generation)
    Path("outputs/final_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    plot_metrics()
