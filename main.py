"""CLI adapter for the shared backend. No workflow logic or artifact cleanup."""
import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.agents.orchestrator import run_enzyme_atelier, review_run
from src.guards.petase_validator import human_approval_gate
from src.run_store import load_result


def review_saved_result(result):
    """Show the proposed changes and evidence before requesting a human decision."""
    if result.config.simulation:
        raise ValueError("Synthetic evaluation runs cannot be approved for export")
    if result.config.mode == "reference":
        print("Reference: A0A0K8P6T7; positions use the full precursor numbering.")
        sources = {item["evidence_id"]: item for item in result.best.get("evidence", [])}
        for mutation in result.best.get("substitutions", []):
            source = sources.get(mutation["evidence_id"], {})
            print(f"{mutation['original']}{mutation['position']}{mutation['replacement']}: "
                  f"{source.get('source', 'unknown')}, page {source.get('page')}")
            print("Evidence excerpt:", mutation["quote"])
        print("Changes from measured WT: II", result.best.get("delta_ii"),
              "; pLDDT", result.best.get("delta_plddt"))
        print("Review the paper context and numbering. Screening does not establish improved activity or melting temperature.")
    try:
        decision = human_approval_gate(result.best["sequence"])
    except (EOFError, KeyboardInterrupt):
        return result
    return review_run(result.run_dir, decision) if decision is not None else result


def main(argv=None):
    """Run a new query or review a saved run; return a meaningful exit code."""
    parser = argparse.ArgumentParser(description="Run PETase computational screening")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--query", help="Design request")
    action.add_argument("--review-run", type=Path, help="Review a saved pending run without repeating tools")
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--max-iter", type=int, default=2)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/runs"))
    parser.add_argument("--review", action="store_true", help="Prompt for approval if screening passes")
    parser.add_argument("--mode", choices=("reference", "progen2"), default="reference")
    parser.add_argument("--enable-api", action="store_true", help="Explicitly allow paid OpenAI planner calls")
    parser.add_argument("--planner-model", help="OpenAI model ID; otherwise use OPENAI_MODEL")
    parser.add_argument("--max-actions", type=int, default=8)
    parser.add_argument("--max-retrievals", type=int, default=3)
    args = parser.parse_args(argv)
    load_dotenv()
    try:
        if args.review_run:
            result = load_result(args.review_run)
            if result.status != "pending_review":
                parser.error(f"Run is not awaiting review: {result.status}")
            print(result.summary())
            result = review_saved_result(result)
        else:
            planner = None
            if args.mode == "reference":
                if not args.enable_api:
                    parser.error("Reference mode needs --enable-api to allow planner calls. Offline checks: python -m eval.design_scenarios")
                from src.agents.planner_agent import OpenAIPlanner
                planner = OpenAIPlanner(args.planner_model)
            result = run_enzyme_atelier(
                args.query, max_iterations=args.max_iter, n_candidates=args.candidates,
                output_root=args.output_root,
                mode=args.mode, planner=planner, max_actions=args.max_actions,
                max_retrievals=args.max_retrievals,
            )
            if args.review and result.status == "pending_review":
                result = review_saved_result(result)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(result.summary())
    if result.status == "pending_review":
        print(f'Awaiting approval. Review with: python main.py --review-run "{result.run_dir}"')
        return 2
    return 0 if result.status == "approved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
