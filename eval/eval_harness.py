"""Small live evaluation harness using the same backend as the CLI.

This is not yet the planned ten-case scientific evaluation suite. Runs stop at
pending review and never approve export automatically.
"""
import json
from pathlib import Path
from uuid import uuid4
from src.agents.orchestrator import run_enzyme_atelier

TEST_CASES = [
    {"id": "t1", "query": "Thermostable PETase for 70C"},
    {"id": "t2", "query": "PETase with disulfide for stability"},
    {"id": "t3", "query": "High pLDDT PETase"},
]


def run_all(n=None, *, output_root="outputs/evaluations"):
    """Record each case's actual backend status without confusing it with approval."""
    if n is not None and (type(n) is not int or not 1 <= n <= len(TEST_CASES)):
        raise ValueError(f"n must be between 1 and {len(TEST_CASES)}")
    directory = Path(output_root) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    results = []
    for case in TEST_CASES[:n]:
        result = run_enzyme_atelier(case["query"], max_iterations=1, n_candidates=3,
                                    output_root=directory / "runs")
        results.append({"id": case["id"], "run_id": result.run_id,
                        "status": result.status, "screening_passes": result.best.get("eligible", False),
                        "plddt": result.best.get("plddt"), "error": result.error})
    (directory / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Evaluation records: {directory}")
    return results


if __name__ == "__main__":
    run_all()
