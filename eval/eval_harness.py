"""
Evaluation harness - runs 10 test cases
"""
import json
from pathlib import Path
from src.agents.orchestrator import run_enzyme_atelier

TEST_CASES = [
    {"id": "t1", "query": "Thermostable PETase for 70C", "expect_len": (200,350)},
    {"id": "t2", "query": "PETase with disulfide for stability", "expect_len": (200,350)},
    {"id": "t3", "query": "High pLDDT PETase", "expect_len": (200,350)},
    # add 7 more
]

def run_all(n=10):
    results = []
    for tc in TEST_CASES[:n]:
        try:
            res = run_enzyme_atelier(tc["query"], max_iterations=1, n_candidates=3)
            success = res.best.get("plddt",0) > 60 and res.best.get("triad", False)
            results.append({"id": tc["id"], "success": success, "plddt": res.best.get("plddt")})
        except Exception as e:
            results.append({"id": tc["id"], "success": False, "error": str(e)})
    Path("eval/results.json").write_text(json.dumps(results, indent=2))
    # Compute metrics
    success_rate = sum(1 for r in results if r["success"])/len(results) if results else 0
    print(f"Success rate: {success_rate*100:.1f}%")
    return results

if __name__ == "__main__":
    run_all()