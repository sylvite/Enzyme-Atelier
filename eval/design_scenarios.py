"""Reproducible synthetic controller evaluation; no API, folding, or embeddings.

Metrics describe fixture routing/guardrails only, never enzyme performance.
"""
from pathlib import Path
from uuid import uuid4

from src.agents.orchestrator import run_enzyme_atelier
from src.agents.reference_workflow import ReferenceTools
from src.design_contract import DesignDecision, Substitution, load_reference
from src.evidence import EvidenceExcerpt, RetrievalResult
from src.run_store import write_json

FIXTURE = EvidenceExcerpt.from_chunk("synthetic-1", "Synthetic test labels: S238F D186H S121E T140D S160A.",
                                     {"source": "SYNTHETIC_FIXTURE.pdf", "page": 1})
CASES = {
    "screening_pass": "pending_review",
    "low_confidence_revision": "pending_review",
    "high_instability_revision": "pending_review",
    "folding_unavailable": "unavailable",
    "retrieval_unavailable": "unavailable",
    "no_evidence": "no_candidate",
    "unknown_citation": "invalid_output",
    "wrong_reference_residue": "invalid_output",
    "protected_residue": "invalid_output",
    "duplicate_mutation": "invalid_output",
    "signal_peptide_mutation": "invalid_output",
    "repeated_candidate": "invalid_output",
    "iteration_budget": "no_candidate",
    "planner_stop": "no_candidate",
    "additional_retrieval": "pending_review",
}


def mutation(label):
    return Substitution(position=int(label[1:-1]), original=label[0], replacement=label[-1],
                        evidence_id=FIXTURE.evidence_id, quote=FIXTURE.text)


class FixturePlanner:
    provider = "offline_fixture"
    model = "scripted-controller-fixture-v1"
    simulation = True

    def __init__(self, case, feedback_enabled=True):
        self.case, self.feedback_enabled = case, feedback_enabled
        self.calls = 0

    def decide(self, context):
        self.calls += 1
        base = dict(reason="Synthetic fixture decision", query="", reference_accession="A0A0K8P6T7")
        if self.case == "planner_stop":
            return DesignDecision(action="stop", substitutions=[], **base)
        if self.case == "additional_retrieval" and self.calls == 1:
            return DesignDecision(action="retrieve", substitutions=[], **dict(base, query="another fixture query"))
        label = "S121E"
        if self.case in ("low_confidence_revision", "repeated_candidate", "iteration_budget"):
            label = "S238F"
        if self.case == "high_instability_revision":
            label = "D186H"
        if self.feedback_enabled and self.case in ("low_confidence_revision", "high_instability_revision"):
            if context["feedback"] == "low_structure_confidence":
                label = "S121E"
            elif context["feedback"] == "high_instability_index":
                label = "T140D"
        substitutions = [mutation(label)]
        if self.case == "unknown_citation":
            substitutions[0].evidence_id = "invented"
        elif self.case == "wrong_reference_residue":
            substitutions[0].original = "A"
        elif self.case == "protected_residue":
            substitutions = [mutation("S160A")]
        elif self.case == "duplicate_mutation":
            substitutions *= 2
        elif self.case == "signal_peptide_mutation":
            substitutions[0].position = 1
        return DesignDecision(action="revise", substitutions=substitutions, **base)


def measured(sequence, *, confidence=85.0, instability=30.0):
    return {"sequence": sequence, "full_len": len(sequence), "fold_len": len(sequence),
            "fold_status": "success", "fold_source": "esm_atlas", "fold_attempts": 1,
            "plddt": confidence, "ii": instability, "mw": 28000.0, "gravy": 0.1,
            "is_stable": instability < 40, "biophys_status": "success", "biophys_source": "biopython",
            "passes": confidence > 70 and instability < 40, "pdb": "SYNTHETIC FIXTURE - NOT A STRUCTURE",
            "reason": "Synthetic screening result", "simulation": True}


def run_case(case, output_root, *, feedback_enabled=True, cancel_requested=None):
    reference = load_reference()["sequence"]

    def retrieve(query):
        status = {"retrieval_unavailable": "unavailable", "no_evidence": "empty"}.get(case, "success")
        return RetrievalResult(query=query, status=status,
                               excerpts=[FIXTURE] if status == "success" else [],
                               error="Synthetic retrieval failure" if status == "unavailable" else "")

    def evaluate(sequence, **kwargs):
        row = measured(sequence)
        if sequence != reference:
            if case == "folding_unavailable":
                row.update(plddt=None, fold_status="unavailable", passes=False)
            elif sequence[238 - 28] == "F":
                row.update(plddt=60.0, passes=False)
            elif sequence[186 - 28] == "H":
                row.update(ii=55.0, is_stable=False, passes=False)
        return row

    return run_enzyme_atelier("Synthetic PETase controller evaluation", mode="reference",
                              planner=FixturePlanner(case, feedback_enabled),
                              max_iterations=1 if case == "iteration_budget" else 2,
                              output_root=output_root, cancel_requested=cancel_requested,
                              reference_tools=ReferenceTools(retrieve, evaluate))



def run_all(output_root="outputs/evaluations"):
    directory = Path(output_root) / uuid4().hex
    outcomes = []
    for case, expected in CASES.items():
        result = run_case(case, directory / "runs")
        outcomes.append({"case": case, "expected": expected, "actual": result.status,
                         "matched": result.status == expected, "run_id": result.run_id,
                         "stop_reason": result.stop_reason, "error": result.error})
    ablation = []
    for case in ("low_confidence_revision", "high_instability_revision"):
        for enabled in (True, False):
            result = run_case(case, directory / "ablation", feedback_enabled=enabled)
            ablation.append({"case": case, "feedback_enabled": enabled, "status": result.status,
                             "screening_passes": result.best.get("eligible", False),
                             "run_id": result.run_id, "iterations": len(result.history)})
    report = {"simulation": True, "scope": "synthetic controller behavior, not biological performance",
              "cases": outcomes, "matched": sum(row["matched"] for row in outcomes),
              "total": len(outcomes), "ablation": ablation}
    write_json(directory / "results.json", report)
    return directory, report


if __name__ == "__main__":
    directory, report = run_all()
    print(f"Synthetic scenarios: {report['matched']}/{report['total']} matched. Results: {directory}")
    raise SystemExit(0 if report["matched"] == report["total"] else 1)
