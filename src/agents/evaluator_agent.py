"""Evaluate candidates without treating unavailable folding as a measurement."""

import math

from src.tools.esmfold_tool import esmfold_fold
from src.tools.biophys_tool import calc_instability


def recorded_fold_success(result):
    """Require explicit provenance and full coverage, including for saved results."""
    score = result.get("plddt")
    folded_length = result.get("fold_len")
    full_length = result.get("full_len")
    return (
        result.get("fold_status") == "success"
        and result.get("fold_source") == "esm_atlas"
        and isinstance(score, (int, float)) and not isinstance(score, bool)
        and math.isfinite(score) and 0 <= score <= 100
        and type(folded_length) is int and type(full_length) is int
        and folded_length == full_length and folded_length > 0
    )


def candidate_sort_key(result):
    """Put passing candidates first and unavailable measurements last."""
    available = recorded_fold_success(result) and recorded_biophys_success(result)
    return (not (available and result.get("passes", False)), not available,
            -result["plddt"] if available else 0,
            result["ii"] if recorded_biophys_success(result) else float("inf"))


def recorded_biophys_success(result):
    """Require measured, finite biophysics values and consistent classification."""
    values = [result.get(name) for name in ("ii", "mw", "gravy")]
    return (
        result.get("biophys_status") == "success"
        and result.get("biophys_source") == "biopython"
        and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) for value in values)
        and result["mw"] > 0
        and result.get("is_stable") is (result["ii"] < 40)
    )


def evaluate_one(seq: str, save_pdb=False):
    """Evaluate the full candidate and retain folding status, errors and attempts."""
    bio_res = calc_instability(seq)
    bio = {
        "ii": bio_res.get("ii"), "mw": bio_res.get("mw"),
        "gravy": bio_res.get("gravy"), "is_stable": bio_res.get("is_stable"),
        "biophys_status": bio_res.get("status", "unavailable"),
        "biophys_source": bio_res.get("source", "unknown"),
        "biophys_error": bio_res.get("error", ""),
    }
    bio_available = bio_res.get("success") is True and recorded_biophys_success(bio)
    if not bio_available:
        bio.update(ii=None, mw=None, gravy=None, is_stable=None)
        if bio["biophys_status"] != "invalid_input":
            bio["biophys_status"] = "unavailable"
        bio["biophys_error"] = bio["biophys_error"] or "Missing or invalid biophysics result"
    fold = esmfold_fold(seq) if bio_available else {"status": "not_run"}
    result = {
        "sequence": seq,
        "full_len": len(seq),
        "fold_len": fold.get("folded_length", 0),
        **bio,
        "plddt": fold.get("plddt"),
        "fold_status": fold.get("status", "unavailable"),
        "fold_source": fold.get("source", "unknown"),
        "fold_attempts": fold.get("attempts", 0),
        "fold_error": fold.get("error", ""),
        "fold_plddt_scale": fold.get("plddt_scale"),
        "passes": False,
        "pdb": "",
    }
    if not bio_available:
        result["reason"] = f"UNAVAILABLE: biophysics: {result['biophys_error']}"
    elif fold.get("success") is not True or not recorded_fold_success(result):
        result.update(plddt=None, fold_status="unavailable")
        result["fold_error"] = result["fold_error"] or "Missing or invalid folding result"
        result["reason"] = f"UNAVAILABLE: folding: {result['fold_error']}"
    else:
        if save_pdb:
            result["pdb"] = fold["pdb"]
        if not result["is_stable"]:
            result["reason"] = f"FAIL: II {result['ii']:.1f} >=40"
        elif result["plddt"] <= 70:
            result["reason"] = f"FAIL: plDDT {result['plddt']:.1f} <=70"
        else:
            result["passes"] = True
            result["reason"] = f"PASS: plDDT {result['plddt']:.1f} >70 and II {result['ii']:.1f} <40"
    print(f"[Evaluator] {result['reason']}")
    return result
