"""Render recorded screening results without inventing folding provenance."""
from pathlib import Path
import json

from src.agents.evaluator_agent import recorded_fold_success, recorded_biophys_success, candidate_sort_key


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


def plot_run_metrics(run_dir):
    """Render one explicit run, using all iterations and preserving approval state."""
    import matplotlib.pyplot as plt
    import pandas as pd
    from src.run_store import load_result, write_json

    result = load_result(run_dir)
    output = result.run_dir / "reports"
    output.mkdir(exist_ok=True)
    rows = report_rows([row for batch in result.history for row in batch])
    measured = [row for row in rows if recorded_fold_success(row) and recorded_biophys_success(row)]
    fig, ax = plt.subplots(figsize=(6, 4))
    for row in measured:
        ax.scatter(row["ii"], row["plddt"], color="green" if row.get("eligible") else "red")
    ax.axvline(40, linestyle="--", color="red", label="II threshold 40")
    ax.axhline(70, linestyle="--", color="green", label="pLDDT threshold 70")
    label = "SYNTHETIC TEST: " if result.config.simulation else ""
    ax.set(xlabel="Instability index", ylabel="pLDDT", title=f"{label}Screening results: {result.status}")
    ax.text(0.02, 0.98, f"Unavailable metric pairs: {len(rows) - len(measured)}",
            transform=ax.transAxes, va="top")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "ii_vs_plddt.png", dpi=150)
    plt.close(fig)

    # Every plotted value comes from an actual iteration/candidate measurement.
    fig, ax = plt.subplots(figsize=(6, 3))
    trajectory = [row for row in rows if recorded_biophys_success(row)]
    for row in trajectory:
        ax.scatter(row["iteration"], row["ii"], color="green" if row.get("eligible") else "orange")
    if not trajectory:
        ax.text(0.5, 0.5, "No recorded biophysics measurements", ha="center", transform=ax.transAxes)
    ax.axhline(40, linestyle="--", color="red")
    ax.set(xlabel="Iteration", ylabel="Recorded instability index", title=label + "Recorded candidate history")
    if result.history:
        ax.set_xticks(range(1, len(result.history) + 1))
    fig.tight_layout()
    fig.savefig(output / "iteration_ii.png", dpi=150)
    plt.close(fig)
    pd.DataFrame(rows, columns=list(rows[0]) if rows else ["candidate_id", "iteration", "ii", "plddt"]).to_csv(
        output / "eval_table.csv", index=False)
    # Reporting never overwrites result.json or the authoritative final_summary.
    summary = json.loads((result.run_dir / "final_summary.json").read_text(encoding="utf-8"))
    write_json(output / "summary.json", summary)
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Report one saved run without calling tools")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    print(plot_run_metrics(args.run_dir))
