from dotenv import load_dotenv
from src.agents.designer_agent import design_candidates
from src.agents.evaluator_agent import evaluate_batch
from src.agents.critic_agent import critique_eval_results
from src.agents.rag_agent import rag_constraints
import argparse
import json
import shutil
from pathlib import Path

load_dotenv()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=int, default=2)
    parser.add_argument("--max-iter", type=int, default=2)
    args = parser.parse_args()

    # Clean stale artifacts from previous failed runs
    Path("outputs").mkdir(exist_ok=True)
    # Remove files that are only valid if critic/eval runs
    for stale in ["critique.json", "plots/iteration_ii.png", "eval_results.json", "episodic_log.jsonl"]:
        p = Path(f"outputs/{stale}")
        if p.exists():
            # Optional: archive instead of delete
            p.unlink()
            print(f"[Cleanup] Removed stale {stale} from previous run")

    print(f"[Orchestrator] Starting agentic loop max_iter={args.max_iter}")

    constraints = rag_constraints("PETase thermostability")
    prompt = constraints if constraints else "PETase thermostable variant"

    for iteration in range(args.max_iter):
        print(f"\n=== ITERATION {iteration+1}/{args.max_iter} ===")

        fasta_path = design_candidates(prompt, n=args.candidates)
        eval_results = evaluate_batch(fasta_path)

        passing = [r for r in eval_results if r["passes"]]
        if passing:
            print(f"\n[Orchestrator] SUCCESS at iteration {iteration+1}: Found {len(passing)} passing")
            break

        if iteration < args.max_iter - 1:
            critique = critique_eval_results()
            if critique and critique["action"] == "redesign":
                failure = critique.get("failure_reason", "")
                # Use RAG-derived FIXED concepts, not filename list
                if "II" in failure:
                    prompt = "Thermostable PETase with disulfide N233C S282C and D186N mutation low instability index stable"
                else:
                    prompt = "Thermostable PETase with D186N disulfide N233C S282C high plDDT thermostable"

                print(f"[Orchestrator] Next prompt: {prompt}")
            else:
                break
        else:
            print("[Orchestrator] Max iterations reached")

if __name__ == "__main__":
    main()