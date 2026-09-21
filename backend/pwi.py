"""PS3 — Positive Water Impact (PWI) Quantification Engine.

Implements the OFFICIAL methodology from the provided resource pack
(`Water Stewardship Module_Hydris_xlsx.xlsx`): a 3x3 matrix of
Pillars (P1 Site / P2 Sub-Basin / P3 Basin) x Dimensions (Availability /
Quality / Access), scored from a 52-question self-assessment, rolled up with
confidence bands and a 5-tier certification decision.

Nothing here is assumed: formulas, weights, question map, cross-validation
rules, confidence rule and certification tiers are transcribed from that
workbook (sheets: PWI 4-Step Framework, 3. Baseline & Targets,
5. Self-Assessment, 7. PWI Dashboard). The per-intervention water benefit
(m3/yr) is a FACTORY INPUT (the brief says: use the provided WQBA benefit
outputs, do not recompute them).

Every computed number is returned as a `traced()` object carrying
{value, unit, formula, source, assumptions, confidence}.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 0. Provenance constant stamped onto outputs
# ---------------------------------------------------------------------------
METHOD_SOURCE = ("Hydris Water Stewardship Module (WQBA/WRC PWI methodology) — "
                 "sheets: 3. Baseline & Targets, 5. Self-Assessment, 7. PWI Dashboard")

PILLARS = ["P1", "P2", "P3"]
PILLAR_NAME = {"P1": "Site", "P2": "Sub-Basin", "P3": "Basin"}
DIMENSIONS = ["Availability", "Quality", "Access"]

# Dimension weights inside a pillar (Baseline & Targets §C):
#   Pillar = Availability*0.4 + Quality*0.3 + Access*0.3
DIM_WEIGHTS = {"Availability": 0.40, "Quality": 0.30, "Access": 0.30}

# ---------------------------------------------------------------------------
# 1. The 52-question instrument -> (pillar, dimension), per Self-Assessment §A/§B
#    P1 Avail Q1-8 · P1 Qual Q9-16 · P1 Access Q17-22
#    P2 Avail Q23-28 · P2 Qual Q29-33 · P2 Access Q34-38
#    P3 Avail Q39-43 · P3 Qual Q44-48 · P3 Access Q49-52   (52 total)
# ---------------------------------------------------------------------------
_RANGES = [
    ("P1", "Availability", 1, 8), ("P1", "Quality", 9, 16), ("P1", "Access", 17, 22),
    ("P2", "Availability", 23, 28), ("P2", "Quality", 29, 33), ("P2", "Access", 34, 38),
    ("P3", "Availability", 39, 43), ("P3", "Quality", 44, 48), ("P3", "Access", 49, 52),
]

QUESTION_CELL: dict[int, tuple[str, str]] = {}
for _p, _d, _lo, _hi in _RANGES:
    for _q in range(_lo, _hi + 1):
        QUESTION_CELL[_q] = (_p, _d)

# short titles (Self-Assessment §A) — kept for the instrument endpoint
QUESTION_TITLE = {
    1: "Complete water metering on all intake points", 2: "Water balance reconciled monthly",
    3: "Water efficiency target set and tracked", 4: "Water recycling/reuse system operational",
    5: "Rainwater harvesting where feasible", 6: "Withdrawal decreased vs baseline",
    7: "Water intensity (m3/unit) improving", 8: "Emergency water backup in place",
    9: "WWTP operational & compliant effluent", 10: "All discharge meets regulatory standards",
    11: "Pollutant monitoring at required frequency", 12: "TSS within target",
    13: "Nutrients (N,P) within target", 14: "Chemical management plan implemented",
    15: "Zero untreated wastewater discharge", 16: "Eco-friendly chemical alternatives adopted",
    17: "All workers have safe drinking water", 18: "Washbasins >=1 per 6 workers",
    19: "Toilets >=1 per 22 workers", 20: "Annual hygiene awareness training",
    21: "Drinking-water quality tested at frequency", 22: "WASH facilities maintained/cleaned",
    23: "Replenishment project identified & scoped", 24: "Replenishment target >= withdrawal",
    25: "Wetland / nature-based solution implemented", 26: "Replenishment independently verified",
    27: "Replenishment benefits local water balance", 28: "Long-term sustainability plan",
    29: "Sub-basin water-quality assessment done", 30: "Contribution to pollutant reduction",
    31: "Collaborative water-quality project", 32: "Measurable sub-basin quality improvement",
    33: "Monitoring beyond factory boundary", 34: "Employee household WASH needs assessed",
    35: "Water filtration distributed to households", 36: "Community WASH services supported",
    37: "People reached by WASH tracked", 38: "Collaboration with local municipality",
    39: "Basin collective-action group joined", 40: "Basin policy engagement initiated",
    41: "Contributed to large-scale restoration", 42: "Basin water-balance improvement shown",
    43: "Multi-stakeholder partnership formalized", 44: "Basin water-quality challenges identified",
    45: "Collective action for basin quality", 46: "Measurable basin-quality contribution",
    47: "Government WQ-policy collaboration", 48: "Basin quality monitoring shared publicly",
    49: "Basin WASH gap analysis conducted", 50: "PPP for basin WASH established",
    51: "Advocacy for national WASH standards", 52: "Measurable basin WASH improvement",
}

# ---------------------------------------------------------------------------
# 2. Confidence rule (Self-Assessment §A/§B) + 10 cross-validation rules (§C)
# ---------------------------------------------------------------------------
EVIDENCE_CONF = {"Yes": 100.0, "Partial": 70.0, "No": 50.0}

# XV rule: (id, description, predicate(scores)->bool fired, penalty_points, action)
def _s(scores, q):  # safe score lookup (missing -> 0)
    return scores.get(q, 0)

XV_RULES = [
    ("XV-01", "Metering required before water balance",
     lambda s: _s(s, 2) >= 2 and _s(s, 1) < 2, 20, "Install meters before claiming a balance"),
    ("XV-02", "WWTP needed before quality claims",
     lambda s: _s(s, 15) >= 2 and _s(s, 9) < 2, 30, "Cannot claim zero discharge without a WWTP"),
    ("XV-03", "Zero-discharge requires monitoring proof",
     lambda s: _s(s, 15) == 3 and _s(s, 11) < 2, 20, "Need monitoring to verify zero discharge"),
    ("XV-04", "Drinking water needs quality testing",
     lambda s: _s(s, 17) >= 2 and _s(s, 21) < 2, 15, "Cannot claim safe water without testing"),
    ("XV-05", "Replenishment needs feasibility first",
     lambda s: _s(s, 25) >= 2 and _s(s, 23) < 2, 20, "Scope before implementation"),
    ("XV-06", "NBS verification needs monitoring",
     lambda s: _s(s, 25) >= 2 and _s(s, 26) < 1, 25, "NBS needs independent verification"),
    ("XV-07", "Household WASH needs assessment first",
     lambda s: _s(s, 35) >= 2 and _s(s, 34) < 2, 15, "Assess needs before distributing"),
    ("XV-08", "Collective action needs partnership",
     lambda s: _s(s, 39) >= 2 and _s(s, 43) < 1, 15, "Formalize partnerships"),
    ("XV-09", "Basin quality needs assessment",
     lambda s: _s(s, 46) >= 2 and _s(s, 44) < 2, 20, "Assess before claiming improvement"),
    ("XV-10", "Basin WASH needs gap analysis",
     lambda s: _s(s, 52) >= 2 and _s(s, 49) < 2, 15, "Gap analysis before claiming improvement"),
]

# ---------------------------------------------------------------------------
# 3. Certification decision matrix (Self-Assessment §D)
# ---------------------------------------------------------------------------
def certify(score_pct: float, confidence_pct: float) -> dict:
    if confidence_pct < 50:
        r, action, validity = "LOW CONFIDENCE: fix data quality", "Improve data collection", None
    elif score_pct >= 100 and confidence_pct >= 75:
        r, action, validity = "SELF-CERTIFIED: Positive Water Impact achieved", "Annual self-report", "3 years"
    elif score_pct >= 80 and confidence_pct >= 75:
        r, action, validity = "CONDITIONAL: partial desk audit", "Submit evidence + desk audit", "1 year"
    elif score_pct >= 60 and confidence_pct >= 50:
        r, action, validity = "IN PROGRESS: external audit needed", "Full 3rd-party audit", None
    else:
        r, action, validity = "NOT ACHIEVED: revised plan required", "Complete reassessment", None
    return {"result": r, "action_required": action, "validity": validity,
            "source": "Self-Assessment §D certification matrix"}

# ---------------------------------------------------------------------------
# 4. Traceability wrapper — every emitted number carries its lineage
# ---------------------------------------------------------------------------
def traced(value, unit, formula, source=METHOD_SOURCE, assumptions=None, confidence=None):
    return {"value": None if value is None else round(value, 2), "unit": unit,
            "formula": formula, "source": source,
            "assumptions": assumptions or [], "confidence_pct": confidence}


# ---------------------------------------------------------------------------
# 5. Core: score the 52-question self-assessment -> 3x3 matrix -> Site PWI
# ---------------------------------------------------------------------------
def score_self_assessment(answers: dict) -> dict:
    """answers: {q_id(int|str): {"score": 0..3, "evidence": "Yes|Partial|No"}}.
    Returns the 9-cell matrix, pillar scores, site PWI, confidence and certification."""
    scores = {int(q): int(a.get("score", 0)) for q, a in answers.items()}
    evid = {int(q): a.get("evidence", "No") for q, a in answers.items()}

    # 5a. per-cell dimension score % = sum(scores)/max * 100 ; max = 3 * n_questions
    cell_raw = {(p, d): [] for _p, _d, *_ in _RANGES for p, d in [(_p, _d)]}
    cell_conf = {(p, d): [] for p, d in cell_raw}
    for q, (p, d) in QUESTION_CELL.items():
        cell_raw[(p, d)].append(scores.get(q, 0))
        cell_conf[(p, d)].append(EVIDENCE_CONF.get(evid.get(q, "No"), 50.0))

    matrix = {}          # pillar -> dim -> traced score%
    dim_conf = {}        # (pillar,dim) -> avg confidence
    for (p, d), vals in cell_raw.items():
        mx = 3 * len(vals)
        pct = 100.0 * sum(vals) / mx if mx else None
        conf = sum(cell_conf[(p, d)]) / len(cell_conf[(p, d)]) if cell_conf[(p, d)] else None
        dim_conf[(p, d)] = conf
        matrix.setdefault(p, {})[d] = traced(
            pct, "%", "Σ(question scores) / (3 × n_questions) × 100",
            assumptions=[f"{len(vals)} questions, max {mx} pts"], confidence=None if conf is None else round(conf, 1))

    # 5b. pillar score = Avail*0.4 + Quality*0.3 + Access*0.3
    pillar = {}
    for p in PILLARS:
        val = sum(matrix[p][d]["value"] * DIM_WEIGHTS[d] for d in DIMENSIONS)
        pillar[p] = traced(val, "%", "Availability×0.4 + Quality×0.3 + Access×0.3",
                           assumptions=[f"{PILLAR_NAME[p]} pillar"])

    # 5c. Site PWI = (P1 + P2 + P3) / 3
    site_val = sum(pillar[p]["value"] for p in PILLARS) / 3
    site_pwi = traced(site_val, "%", "(P1 + P2 + P3) / 3")

    # 5d. confidence: raw = mean question confidence ; adjusted = raw - Σ XV penalties
    raw_conf = sum(EVIDENCE_CONF.get(evid.get(q, "No"), 50.0) for q in QUESTION_CELL) / len(QUESTION_CELL)
    xv = []
    penalty = 0.0
    for xid, desc, pred, pen, action in XV_RULES:
        fired = bool(pred(scores))
        if fired:
            penalty += pen
        xv.append({"id": xid, "check": desc, "result": "FAIL" if fired else "PASS",
                   "penalty_points": pen if fired else 0, "action": action if fired else None})
    adj_conf = max(0.0, raw_conf - penalty)
    confidence = {
        "raw_pct": round(raw_conf, 1),
        "xv_penalty_points": round(penalty, 1),
        "adjusted_pct": round(adj_conf, 1),
        "formula": "adjusted = mean(evidence confidence: Yes100/Partial70/No50) − Σ XV penalties",
        "source": "Self-Assessment §A confidence rule + §C cross-validation",
        "rules": xv,
    }

    cert = certify(site_val, adj_conf)
    return {"matrix": matrix, "pillars": pillar, "site_pwi": site_pwi,
            "confidence": confidence, "certification": cert}


# ---------------------------------------------------------------------------
# 6. Operational water balance -> quantitative dimension proxies (Baseline & Targets)
#    Availability% = replenishment / withdrawal × 100 (net-positive at ≥100)
#    Quality%      = wastewater treated / generated × 100 (pollutant-removal proxy)
#    Access%       = WASH fulfilment (toilets ≤22:1, washbasins ≤6:1, drinking water)
# ---------------------------------------------------------------------------
def water_balance(op: dict) -> dict:
    wd = op.get("annual_withdrawal_m3")
    reuse = (op.get("water_recycled_m3") or 0) + (op.get("water_reused_m3") or 0)
    benefits = op.get("intervention_benefits_m3") or []
    replenishment = sum(benefits) + reuse
    ww_gen = op.get("wastewater_generated_m3")
    ww_treated = op.get("wastewater_treated_m3")
    emp = op.get("employees")
    toilets = op.get("toilets")
    washbasins = op.get("washbasins")
    safe_dw = op.get("safe_drinking_water", True)

    avail = traced(
        100.0 * replenishment / wd if wd else None, "%",
        "replenishment (Σ intervention benefits + recycled + reused) / annual withdrawal × 100",
        assumptions=["net-positive availability at ≥100%", f"replenishment={replenishment} m³/yr"])
    qual = traced(
        100.0 * ww_treated / ww_gen if ww_gen else None, "%",
        "wastewater treated / wastewater generated × 100 (pollutant-removal proxy)")

    # Access: fraction of three WASH conditions met (ILO ratios + safe drinking water)
    if emp:
        met = 0
        checks = 0
        if toilets is not None:
            checks += 1; met += 1 if emp / toilets <= 22 else 0
        if washbasins is not None:
            checks += 1; met += 1 if emp / washbasins <= 6 else 0
        checks += 1; met += 1 if safe_dw else 0
        acc_val = 100.0 * met / checks if checks else None
    else:
        acc_val = None
    acc = traced(acc_val, "%",
                 "share of WASH conditions met (toilets ≤22:1, washbasins ≤6:1, safe drinking water)",
                 assumptions=["ILO WASH ratios"])

    return {"withdrawal_m3": wd, "replenishment_m3": replenishment,
            "required_replenishment_m3": traced((wd - reuse) if wd is not None else None, "m³/yr",
                                                 "withdrawal − reuse", source="Baseline & Targets §A"),
            "quant_dimensions": {"Availability": avail, "Quality": qual, "Access": acc}}


# ---------------------------------------------------------------------------
# 7. Targets (20/40/40), gap analysis, intervention catalog, projected PWI
# ---------------------------------------------------------------------------
INTERVENTION_CATALOG = {
    ("P1", "Availability"): ["Water-efficiency programme", "Recycling/reuse system", "Rainwater harvesting"],
    ("P1", "Quality"): ["WWTP upgrade / optimization", "Chemical substitution (ZDHC MRSL)"],
    ("P1", "Access"): ["Install WASH facilities (toilets/handwash/drinking water)", "WASH training"],
    ("P2", "Availability"): ["Replenishment (wetland restoration / managed aquifer recharge)", "Stakeholder engagement"],
    ("P2", "Quality"): ["Constructed wetland / buffer zones"],
    ("P2", "Access"): ["Community WASH project (water points, sanitation, hygiene)"],
    ("P3", "Availability"): ["Basin stewardship coalition & policy engagement", "Large-scale basin replenishment"],
    ("P3", "Quality"): ["Basin pollution-reduction collaboration"],
    ("P3", "Access"): ["Basin WASH public-private partnership (SDG 6)"],
}

# 20/40/40 phasing: Phase-1 (Year 1-2) closes 20% of the remaining gap, Site-level first
PHASE1_CLOSE = 0.20


def gap_and_projection(matrix: dict) -> dict:
    """For every cell below the 100% positive-impact threshold, compute the gap,
    recommend interventions, and project the Phase-1 (20/40/40) post-implementation PWI.
    Projected values are labeled PLANNED (not verified)."""
    THRESHOLD = 100.0
    gaps = []
    projected_matrix = {p: {} for p in PILLARS}
    for p in PILLARS:
        for d in DIMENSIONS:
            cur = matrix[p][d]["value"]
            gap = max(0.0, THRESHOLD - cur)
            planned_gain = round(gap * PHASE1_CLOSE, 2)
            proj = round(min(THRESHOLD, cur + planned_gain), 2)
            projected_matrix[p][d] = proj
            if gap > 0:
                gaps.append({
                    "pillar": p, "pillar_name": PILLAR_NAME[p], "dimension": d,
                    "current_pct": round(cur, 1), "target_pct": THRESHOLD, "gap_pct": round(gap, 1),
                    "recommended_interventions": INTERVENTION_CATALOG.get((p, d), []),
                    "phase1_planned_gain_pct": planned_gain, "projected_pct": proj,
                    "basis": "20/40/40 phasing — Phase 1 closes 20% of the gap",
                })
    proj_pillars = {p: sum(projected_matrix[p][d] * DIM_WEIGHTS[d] for d in DIMENSIONS) for p in PILLARS}
    proj_site = sum(proj_pillars.values()) / 3
    gaps.sort(key=lambda g: -g["gap_pct"])
    return {
        "target_threshold_pct": THRESHOLD,
        "gaps": gaps,
        "projected_pillars": {p: round(v, 2) for p, v in proj_pillars.items()},
        "projected_site_pwi": traced(proj_site, "%", "(P1'+P2'+P3')/3 after Phase-1 interventions",
                                     assumptions=["PLANNED, not verified", "Phase-1 = 20% gap closure"]),
        "source": "Baseline & Targets §B (20/40/40) + Step 2 intervention catalog",
    }


# ---------------------------------------------------------------------------
# 8. Whole-site engine + portfolio rollup
# ---------------------------------------------------------------------------
def site_pwi(site: dict) -> dict:
    """site = {id, name, ..., self_assessment:{q:{score,evidence}}, operational:{...}}"""
    sa = score_self_assessment(site.get("self_assessment", {}))
    wb = water_balance(site.get("operational", {})) if site.get("operational") else None
    gp = gap_and_projection(sa["matrix"])
    return {
        "site": {k: site.get(k) for k in ("id", "name", "company", "lat", "lng", "pfaf_id",
                                          "industry", "basin_name")},
        "data_grade": site.get("data_grade", "unspecified"),
        "matrix_3x3": sa["matrix"],
        "pillars": sa["pillars"],
        "site_pwi": sa["site_pwi"],
        "confidence": sa["confidence"],
        "certification": sa["certification"],
        "water_balance": wb,
        "targets_gap_projection": gp,
        "method_source": METHOD_SOURCE,
    }


def portfolio_pwi(sites: list[dict]) -> dict:
    """Portfolio PWI = Σ Site scores / #Sites × 100 (Baseline & Targets §C, values already %)."""
    results = [site_pwi(s) for s in sites]
    vals = [r["site_pwi"]["value"] for r in results if r["site_pwi"]["value"] is not None]
    port = sum(vals) / len(vals) if vals else None
    ranked = sorted(results, key=lambda r: (r["site_pwi"]["value"] or -1), reverse=True)
    return {
        "portfolio_pwi": traced(port, "%", "Σ Site PWI / #Sites (equal-weighted mean of site %)",
                                assumptions=[f"{len(vals)} scored sites"]),
        "n_sites": len(sites),
        "ranked_sites": [{"id": r["site"]["id"], "name": r["site"]["name"],
                          "site_pwi": r["site_pwi"]["value"],
                          "certification": r["certification"]["result"],
                          "adjusted_confidence": r["confidence"]["adjusted_pct"]} for r in ranked],
        "sites": results,
        "method_source": METHOD_SOURCE,
    }


def instrument() -> dict:
    """The 52-question instrument + 3x3 matrix definition (for the frontend)."""
    return {
        "pillars": {p: PILLAR_NAME[p] for p in PILLARS},
        "dimensions": DIMENSIONS,
        "dimension_weights": DIM_WEIGHTS,
        "questions": [{"id": q, "pillar": QUESTION_CELL[q][0], "pillar_name": PILLAR_NAME[QUESTION_CELL[q][0]],
                       "dimension": QUESTION_CELL[q][1], "title": QUESTION_TITLE.get(q, ""),
                       "scale": "0=not done, 1=partial/planned, 2=implemented, 3=fully implemented & verified"}
                      for q in sorted(QUESTION_CELL)],
        "confidence_rule": EVIDENCE_CONF,
        "certification_matrix": "score≥100 & conf≥75 → self-certified; 80-99 → conditional; 60-79 → in progress; <60 → not achieved; conf<50 → low confidence",
        "source": METHOD_SOURCE,
    }
