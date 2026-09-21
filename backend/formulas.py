"""PS5 — Intervention formula recompute + claim verification + A–F grading.

Implements the 9 intervention formulas from the attached audit
("PWI Formula Validation & GEE Audit"), independently recomputes each claimed
benefit (using the document's own parameters + GEE rainfall where the formula
needs it), compares claimed vs recomputed, and grades the claim.

Design locked with the user:
- Threshold: ±20% for SOUND formulas, ±35% for calibration/oversimplified;
  the two WEAK formulas (wetland, afforestation) are "not numerically verifiable".
- Grade A–F from deviation, CAPPED by formula soundness (weak → max C).
- Confidence = 0.35·DocQuality + 0.25·EngValidation + 0.20·ExtDataMatch
  + 0.10·ImageVerification + 0.10·HistoricalConsistency  (the audit's composite).
- GEE supplies rainfall (CHIRPS); the document supplies areas/dims/volumes.
"""
from __future__ import annotations

GRADE_ORDER = ["A", "B", "C", "D", "F"]


def _worse(g1: str, g2: str) -> str:
    """Return the lower (worse) of two letter grades."""
    return g1 if GRADE_ORDER.index(g1) >= GRADE_ORDER.index(g2) else g2


def _band(dev_pct: float) -> str:
    if dev_pct <= 10:
        return "A"
    if dev_pct <= 20:
        return "B"
    if dev_pct <= 35:
        return "C"
    if dev_pct <= 50:
        return "D"
    return "F"


# soundness -> (numeric threshold %, grade cap, engineering-validation score 0-1)
SOUNDNESS = {
    "sound":              {"threshold": 20, "cap": "A", "eng": 1.00},
    "needs_calibration":  {"threshold": 35, "cap": "B", "eng": 0.70},
    "oversimplified":     {"threshold": 35, "cap": "B", "eng": 0.60},
    "needs_correction":   {"threshold": 35, "cap": "B", "eng": 0.60},
    "needs_normalisation": {"threshold": 35, "cap": "B", "eng": 0.60},
    "weak":               {"threshold": None, "cap": "C", "eng": 0.40},
}


# ---------------------------------------------------------------------------
# recompute functions — return (value|None, inputs_used dict)
# rain_m = GEE annual rainfall in metres (or None)
# ---------------------------------------------------------------------------
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rwh(p, rain_m):
    area = _num(p.get("catchment_area_m2"))
    rain = _num(p.get("rainfall_mm"))
    rain = (rain / 1000.0) if rain is not None else rain_m
    coeff = _num(p.get("runoff_coeff")) or 0.775  # midpoint of 0.6–0.95
    if area is None or rain is None:
        return None, {}
    return area * rain * coeff, {"area_m2": area, "rainfall_m": round(rain, 3), "runoff_coeff": coeff}


def _recharge(p, rain_m):
    area = _num(p.get("area_m2"))
    rain = _num(p.get("rainfall_mm"))
    rain = (rain / 1000.0) if rain is not None else rain_m
    coeff = _num(p.get("recharge_coeff")) or 0.225  # midpoint of 0.05–0.4
    if area is None or rain is None:
        return None, {}
    return area * rain * coeff, {"area_m2": area, "rainfall_m": round(rain, 3), "recharge_coeff": coeff}


def _check_dam(p, rain_m):
    L, W, D = _num(p.get("length_m")), _num(p.get("width_m")), _num(p.get("depth_m"))
    eff = _num(p.get("recharge_efficiency")) or 0.5
    if None in (L, W, D):
        return None, {}
    return L * W * D * eff, {"L_m": L, "W_m": W, "D_m": D, "recharge_efficiency": eff}


def _subtract(a_key, b_key):
    def fn(p, rain_m):
        a, b = _num(p.get(a_key)), _num(p.get(b_key))
        if a is None or b is None:
            return None, {}
        return a - b, {a_key: a, b_key: b}
    return fn


def _wetland(p, rain_m):
    area = _num(p.get("wetland_area_ha"))
    rate = _num(p.get("recharge_rate"))  # m3/ha/yr
    if area is None or rate is None:
        return None, {}
    return area * rate, {"wetland_area_ha": area, "recharge_rate_m3_ha_yr": rate}


def _afforest(p, rain_m):
    area = _num(p.get("forest_area_ha"))
    factor = _num(p.get("recharge_improvement_factor"))
    if area is None or factor is None:
        return None, {}
    return area * factor, {"forest_area_ha": area, "recharge_improvement_factor": factor}


INTERVENTION_FORMULAS = {
    "rainwater_harvesting": {
        "formula": "Catchment Area × Rainfall × Runoff Coefficient",
        "soundness": "sound", "needs_rainfall": True, "image_verifiable": True, "recompute": _rwh,
        "open_risk": "Unsourced runoff coefficient (0.6–0.95); no first-flush loss."},
    "groundwater_recharge": {
        "formula": "Area × Rainfall × Recharge Coefficient",
        "soundness": "needs_calibration", "needs_rainfall": True, "image_verifiable": True, "recompute": _recharge,
        "open_risk": "Recharge coefficient 0.05–0.4 (8× spread); no additionality check."},
    "check_dam": {
        "formula": "(Length × Width × Depth) × Recharge Efficiency",
        "soundness": "oversimplified", "needs_rainfall": False, "image_verifiable": True, "recompute": _check_dam,
        "open_risk": "Static pond volume, not seasonal fill-cycle throughput."},
    "wastewater_reuse": {
        "formula": "Treated Water − Discharged Water",
        "soundness": "sound", "needs_rainfall": False, "image_verifiable": False,
        "recompute": _subtract("treated_m3", "discharged_m3"),
        "open_risk": "Parameter/name mismatch; recovery-efficiency role undefined."},
    "leak_reduction": {
        "formula": "Baseline − Current",
        "soundness": "sound", "needs_rainfall": False, "image_verifiable": False,
        "recompute": _subtract("baseline_m3", "current_m3"),
        "open_risk": "Baseline definition unstated; demand growth not controlled."},
    "industrial_efficiency": {
        "formula": "Baseline Water Use − Current Water Use (should be production-normalised)",
        "soundness": "needs_correction", "needs_rainfall": False, "image_verifiable": False,
        "recompute": _subtract("baseline_m3", "current_m3"),
        "open_risk": "Not normalised to production output."},
    "drip_irrigation": {
        "formula": "Conventional Irrigation − Drip Irrigation",
        "soundness": "needs_normalisation", "needs_rainfall": False, "image_verifiable": False,
        "recompute": _subtract("conventional_m3", "drip_m3"),
        "open_risk": "Area/crop unused; no yield trade-off check."},
    "wetland_restoration": {
        "formula": "Wetland Area × Recharge Rate",
        "soundness": "weak", "needs_rainfall": False, "image_verifiable": True, "recompute": _wetland,
        "open_risk": "Bidirectional/seasonal; hydraulic conductivity omitted."},
    "afforestation": {
        "formula": "Forest Area × Recharge Improvement Factor",
        "soundness": "weak", "needs_rainfall": False, "image_verifiable": True, "recompute": _afforest,
        "open_risk": "Afforestation can REDUCE net recharge; factor unbounded."},
}


# ---------------------------------------------------------------------------
# GEE annual rainfall (CHIRPS) at a point, in metres/yr
# ---------------------------------------------------------------------------
def gee_annual_rainfall_m(lat: float, lng: float):
    try:
        import ee
        col = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").select("precipitation")
               .filterDate("2015-01-01", "2025-01-01"))
        total = col.sum()
        pt = ee.Geometry.Point([lng, lat]).buffer(5000)
        d = total.reduceRegion(ee.Reducer.mean(), pt, 5000, maxPixels=1e9, bestEffort=True).getInfo()
        vals = [v for v in (d or {}).values() if v is not None]
        if not vals:
            return None
        return (vals[0] / 10.0) / 1000.0   # 10-yr total mm -> annual mm -> annual m
    except Exception:
        return None


# ---------------------------------------------------------------------------
# verify one claim -> deviation, verified, grade, confidence
# ---------------------------------------------------------------------------
def verify_claim(claim: dict, lat: float | None = None, lng: float | None = None,
                 doc_confidence: float = 70.0, rain_m: float | None = None) -> dict:
    itype = claim.get("intervention")
    spec = INTERVENTION_FORMULAS.get(itype)
    claimed = _num(claim.get("claimed_value"))
    out = {"intervention": itype, "claimed_value": claimed,
           "claimed_unit": claim.get("claimed_unit") or "m3/yr"}
    if spec is None:
        out.update({"status": "unknown_intervention", "verified": None, "grade": None,
                    "recomputed_value": None, "deviation_pct": None})
        return out

    snd = spec["soundness"]
    meta = SOUNDNESS[snd]
    out.update({"formula": spec["formula"], "formula_soundness": snd, "open_risk": spec["open_risk"],
                "threshold_pct": meta["threshold"]})

    # recompute (GEE rainfall only fetched if the formula needs it and doc lacks it)
    if spec.get("needs_rainfall") and rain_m is None and lat is not None and lng is not None \
            and _num(claim.get("params", {}).get("rainfall_mm")) is None:
        rain_m = gee_annual_rainfall_m(lat, lng)
    recomputed, inputs = spec["recompute"](claim.get("params", {}) or {}, rain_m)
    rainfall_source = ("GEE CHIRPS (annual)" if spec.get("needs_rainfall") and
                       _num((claim.get("params") or {}).get("rainfall_mm")) is None and rain_m is not None
                       else ("document" if spec.get("needs_rainfall") else None))
    out.update({"recomputed_value": None if recomputed is None else round(recomputed, 1),
                "inputs_used": inputs, "rainfall_source": rainfall_source})

    # deviation
    if recomputed is None or claimed is None:
        deviation = None
    elif recomputed == 0:
        deviation = 0.0 if claimed == 0 else 999.0
    else:
        deviation = round(abs(claimed - recomputed) / abs(recomputed) * 100, 1)
    out["deviation_pct"] = deviation

    # confidence composite (0.35/0.25/0.20/0.10/0.10)
    doc_q = max(0.0, min(1.0, (doc_confidence or 70) / 100.0))
    eng = meta["eng"]
    ext_match = 1.0 if deviation is None else max(0.0, 1.0 - deviation / 100.0)
    img = 0.6 if spec.get("image_verifiable") else 0.4
    hist = 0.6 if rainfall_source and "GEE" in rainfall_source else 0.5
    confidence = round(100 * (0.35 * doc_q + 0.25 * eng + 0.20 * ext_match + 0.10 * img + 0.10 * hist), 1)
    out["confidence_pct"] = confidence
    out["confidence_factors"] = {"document_quality": round(doc_q, 2), "engineering_validation": eng,
                                 "external_data_match": round(ext_match, 2),
                                 "image_verification": img, "historical_consistency": hist}

    # verdict + grade (capped by soundness)
    if meta["threshold"] is None:  # weak: not numerically verifiable
        out["status"] = "not_numerically_verifiable"
        out["verified"] = None
        base = "C" if confidence >= 60 else "D" if confidence >= 45 else "F"
        out["grade"] = _worse(base, meta["cap"])
        out["grade_note"] = "Formula is scientifically weak (bidirectional/seasonal) — capped at C by design."
    elif deviation is None:
        out["status"] = "insufficient_inputs"
        out["verified"] = None
        out["grade"] = "F"
        out["grade_note"] = "Not enough parameters in the document to recompute the claim."
    else:
        out["status"] = "verified" if deviation <= meta["threshold"] else "flagged"
        out["verified"] = deviation <= meta["threshold"]
        out["grade"] = _worse(_band(deviation), meta["cap"])
        direction = "over-stated" if claimed > recomputed else "under-stated" if claimed < recomputed else "matches"
        out["direction"] = direction
        out["grade_note"] = (f"Claim {direction} by {deviation}% vs independent recompute "
                             f"(threshold ±{meta['threshold']}%); grade capped at {meta['cap']} by formula soundness.")
    return out


def grade_to_gpa(g: str) -> float:
    return {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}.get(g, 0.0)


def overall_grade(claims: list, coverage_pct: float) -> dict:
    """Roll up per-claim grades + CDP coverage into an overall site disclosure grade."""
    graded = [c for c in claims if c.get("grade")]
    verified = [c for c in claims if c.get("verified") is True]
    gpa = sum(grade_to_gpa(c["grade"]) for c in graded) / len(graded) if graded else 0.0
    # coverage nudges the GPA (full CDP coverage worth up to +0.3)
    gpa_adj = min(4.0, gpa + (coverage_pct / 100.0) * 0.3)
    letter = ("A" if gpa_adj >= 3.5 else "B" if gpa_adj >= 2.5 else
              "C" if gpa_adj >= 1.5 else "D" if gpa_adj >= 0.75 else "F")
    verified_pct = round(100 * len(verified) / len(graded), 1) if graded else 0.0
    return {"cdp_grade": letter, "gpa": round(gpa_adj, 2),
            "claims_total": len(claims), "claims_graded": len(graded),
            "verified_pct": verified_pct,
            "verified_benefit_m3_yr": round(sum(_num(c.get("recomputed_value")) or 0 for c in verified), 1),
            "note": "Overall grade = mean claim GPA (A=4..F=0) adjusted for CDP coverage. "
                    "Only verified benefits feed the PWI Availability score."}
