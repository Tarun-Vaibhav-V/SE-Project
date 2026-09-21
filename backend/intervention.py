"""PS-X - Hydris Intervention Intelligence Engine (HIIE).

Turns Hydris from a *diagnostic* tool ("how risky is this factory, and why?")
into a *prescriptive* one ("what can we change, how much risk does it remove,
how much water does it save, what does it cost, which option wins?").

Pipeline
--------
    cached driver JSON (drivers.py)      <- the measured state
            |
            v
    INTERVENTION MODEL   effect(intensity, basin_context) -> per-driver severity delta
            |
            v
    COUNTERFACTUAL       re-run drivers.composite() on the modified severities
            |
            v
    OPTIMIZER            exhaustive portfolio search against a stated goal
            |
            v
    EVIDENCE GRAPH       recommendation -> driver -> dataset, traversable

Honesty spine (identical to explain.py / pwi_recommend.py)
---------------------------------------------------------
* FACTS  - baseline severities, weights, sources and confidences are read
  straight out of the computed driver JSON. Nothing is re-derived here.
* MODELS - intervention effect coefficients are *planning estimates* drawn from
  the WSM 4-Step framework and the WQBA guidebook's typical ranges. Every one
  is stamped `basis: planning-estimate` and carries its own confidence. They are
  never presented as measured outcomes.
* The counterfactual re-uses `drivers.composite()` verbatim, so a simulated
  score is computed by exactly the same renormalised-weighted-mean maths as the
  baseline score. No parallel implementation can drift from it.
* Confidence propagates by WEAKEST LINK: a projected reduction that leans on a
  `regional` driver (GRACE) can never be reported as `computed`.
* Effects are clamped so severity stays inside [0, 1]; a portfolio therefore
  shows genuine diminishing returns instead of unbounded stacking.
* No LLM is involved in any number on this path. The LLM (explain.py) may
  narrate the result afterwards - it is the interface to the science, never the
  source of it.
"""
from __future__ import annotations

import itertools
import math

from drivers import composite

# ---------------------------------------------------------------------------
# 0. Provenance constants
# ---------------------------------------------------------------------------
METHOD_SOURCE = ("Hydris Intervention Intelligence Engine - effect coefficients from the "
                 "Water Stewardship Module 4-Step framework and WQBA volumetric benefit "
                 "accounting typical ranges")

ESTIMATE_BASIS = "planning-estimate"

CONF_ORDER = ["computed", "proxy", "regional", "planning-estimate", "no-data"]


def _weakest(*confidences) -> str:
    """Weakest-link confidence: the least trustworthy input governs the output."""
    present = [c for c in confidences if c]
    if not present:
        return "no-data"
    return max(present, key=lambda c: CONF_ORDER.index(c) if c in CONF_ORDER else len(CONF_ORDER))


def _response(intensity: float) -> float:
    """Saturating response curve for intervention intensity.

    Physical interventions show diminishing returns: the first 20% of a leak
    programme finds the easy leaks. Modelled as 1 - exp(-2.2 * x), normalised so
    response(1.0) == 1.0. Documented rather than hidden so the shape is auditable.
    """
    x = max(0.0, min(1.0, float(intensity)))
    k = 2.2
    return (1.0 - math.exp(-k * x)) / (1.0 - math.exp(-k))


# ---------------------------------------------------------------------------
# 1. Intervention catalogue
# ---------------------------------------------------------------------------
# `effects` maps a driver key (exactly as produced by drivers.py) to the maximum
# severity reduction achievable at intensity 1.0, in severity units (0-1 scale).
# `feasibility` names a driver whose severity modulates how well the measure can
# work in THIS basin - e.g. rainwater harvesting is worth less where rainfall is
# already the scarce factor. `water_model` documents the volumetric formula.
CATALOG = {
    "rainwater_harvesting": {
        "name": "Rooftop rainwater harvesting",
        "pillar": "P1", "dimension": "Availability",
        "effects": {"extraction_pressure": 0.16, "recharge_worry": 0.10, "runoff_SCS_CN": 0.06},
        "feasibility": {"driver": "rainfall_SPI", "mode": "wetter_is_better"},
        "water_model": "yield = roof_area_m2 x annual_rainfall_m x runoff_coeff(0.8) x filter_eff(0.9)",
        "duration": "3-6 months",
        "cost_band": "Low",
        "cost_lakh_inr": [3.0, 12.0],
        "difficulty": "Low",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 2 - onsite supply augmentation; yield scales with roof area and rainfall",
    },
    "wastewater_recycling": {
        "name": "Wastewater recycling / reuse (RO + MBR)",
        "pillar": "P1", "dimension": "Availability",
        "effects": {"extraction_pressure": 0.30, "aquifer_decline": 0.08},
        "feasibility": None,
        "water_model": "offset = effluent_m3_yr x recovery_rate(0.75)",
        "duration": "6-12 months",
        "cost_band": "High",
        "cost_lakh_inr": [45.0, 140.0],
        "difficulty": "High",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 2 - displaces freshwater intake by the recycled volume",
    },
    "leak_reduction": {
        "name": "Leak detection & repair programme",
        "pillar": "P1", "dimension": "Availability",
        "effects": {"extraction_pressure": 0.11},
        "feasibility": None,
        "water_model": "saving = withdrawal_m3_yr x assumed_loss_rate(0.15) x recovery(0.6)",
        "duration": "3-9 months",
        "cost_band": "Low",
        "cost_lakh_inr": [2.0, 9.0],
        "difficulty": "Low",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 2 - non-revenue water recovery, typically 10-20% of intake",
    },
    "process_optimization": {
        "name": "Process water optimisation (CIP, cooling, rinse)",
        "pillar": "P1", "dimension": "Availability",
        "effects": {"extraction_pressure": 0.22},
        "feasibility": None,
        "water_model": "saving = withdrawal_m3_yr x process_share(0.55) x efficiency_gain(0.25)",
        "duration": "6-18 months",
        "cost_band": "Medium",
        "cost_lakh_inr": [12.0, 48.0],
        "difficulty": "Medium",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 2 - cuts withdrawal 10-30% in water-intensive processes",
    },
    "managed_aquifer_recharge": {
        "name": "Managed aquifer recharge (recharge shafts / ponds)",
        "pillar": "P2", "dimension": "Availability",
        "effects": {"recharge_worry": 0.26, "aquifer_decline": 0.16, "extraction_pressure": 0.05},
        "feasibility": {"driver": "recharge_worry", "mode": "worse_is_better"},
        "water_model": "recharge = catchment_area_m2 x rainfall_m x infiltration_frac(0.35)",
        "duration": "12-24 months",
        "cost_band": "High",
        "cost_lakh_inr": [35.0, 120.0],
        "difficulty": "High",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 3 - basin replenishment; effectiveness rises where recharge deficit is large",
    },
    "green_cover_permeable": {
        "name": "Green cover & permeable surfaces",
        "pillar": "P2", "dimension": "Availability",
        "effects": {"runoff_SCS_CN": 0.20, "urbanization": 0.14,
                    "recharge_worry": 0.09, "soil_moisture": 0.08},
        "feasibility": {"driver": "urbanization", "mode": "worse_is_better"},
        "water_model": "infiltration gain = depaved_area_m2 x rainfall_m x delta_CN_infiltration(0.30)",
        "duration": "6-12 months",
        "cost_band": "Medium",
        "cost_lakh_inr": [8.0, 35.0],
        "difficulty": "Medium",
        "confidence": "planning-estimate",
        "basis_note": "NRCS TR-55 - lowering the curve number cuts direct runoff and raises infiltration",
    },
    "stormwater_detention": {
        "name": "Stormwater detention & conveyance upgrade",
        "pillar": "P1", "dimension": "Availability",
        "effects": {"runoff_SCS_CN": 0.18, "catchment": 0.10, "soil_saturation": 0.07},
        "feasibility": None,
        "water_model": "peak attenuation = detention_volume_m3 / design_storm_volume_m3",
        "duration": "6-18 months",
        "cost_band": "Medium",
        "cost_lakh_inr": [15.0, 60.0],
        "difficulty": "Medium",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 2 - flood hazard mitigation at the site boundary",
    },
    "soil_moisture_conservation": {
        "name": "Soil moisture conservation (mulching, contour bunds)",
        "pillar": "P2", "dimension": "Availability",
        "effects": {"soil_moisture": 0.15, "vegetation_NDVI": 0.10, "recharge_worry": 0.06},
        "feasibility": {"driver": "soil_moisture", "mode": "worse_is_better"},
        "water_model": "retention = treated_area_m2 x root_zone_depth_m x porosity_gain(0.04)",
        "duration": "6-12 months",
        "cost_band": "Low",
        "cost_lakh_inr": [2.5, 11.0],
        "difficulty": "Low",
        "confidence": "planning-estimate",
        "basis_note": "WSM Step 3 - catchment-side retention, supports drought resilience",
    },
}

# which risk engine owns each driver key -> lets one intervention span engines
DRIVER_RISK = {
    "rainfall_SPI": "drought", "water_balance_SPEI": "drought", "soil_moisture": "drought",
    "runoff": "drought", "vegetation_NDVI": "drought", "storage_GRACE": "drought",
    "extraction_pressure": "groundwater", "aquifer_decline": "groundwater",
    "recharge_worry": "groundwater", "quality_QD": "groundwater",
    "rainfall": "flood", "runoff_SCS_CN": "flood", "catchment": "flood",
    "soil_saturation": "flood", "urbanization": "flood",
}

RISKS = ["drought", "groundwater", "flood"]


def catalog():
    """Public catalogue with the modelling caveat attached to every entry."""
    out = []
    for key, spec in CATALOG.items():
        out.append({
            "id": key,
            **{k: v for k, v in spec.items() if k != "effects"},
            "affects": [{"driver": d, "risk": DRIVER_RISK.get(d), "max_severity_delta": v}
                        for d, v in spec["effects"].items()],
            "basis": ESTIMATE_BASIS,
            "method_source": METHOD_SOURCE,
        })
    return {"interventions": out,
            "note": ("Effect coefficients are planning estimates, not measured outcomes. "
                     "Baseline severities they are applied to are computed from satellite data.")}


# ---------------------------------------------------------------------------
# 2. Feasibility - how well does this measure suit THIS basin?
# ---------------------------------------------------------------------------
def _find_driver(baseline: dict, key: str):
    for risk in RISKS:
        blk = baseline.get(risk) or {}
        d = (blk.get("drivers") or {}).get(key)
        if d:
            return d
    return None


def _feasibility(spec, baseline: dict) -> dict:
    """Scale an intervention's effect by basin conditions read from real drivers.

    `wetter_is_better`: rainwater harvesting needs rain. Driver severity is a
      dryness score, so feasibility falls as the basin gets drier.
    `worse_is_better`: recharge / green cover / soil measures have the most
      headroom exactly where that driver is worst.
    Missing driver -> factor 1.0, flagged so the caller knows it was unmodulated.
    """
    if not spec.get("feasibility"):
        return {"factor": 1.0, "basis": "not basin-modulated", "confidence": ESTIMATE_BASIS}
    fk = spec["feasibility"]
    drv = _find_driver(baseline, fk["driver"])
    if not drv or drv.get("severity") is None:
        return {"factor": 1.0, "basis": f"{fk['driver']} unavailable - effect left unmodulated",
                "confidence": "no-data"}
    sev = float(drv["severity"])
    if fk["mode"] == "wetter_is_better":
        factor = round(0.55 + 0.45 * (1.0 - sev), 3)
        basis = f"{fk['driver']} severity {sev:.2f}; drier basin -> lower harvest yield"
    else:
        factor = round(0.55 + 0.45 * sev, 3)
        basis = f"{fk['driver']} severity {sev:.2f}; larger deficit -> more headroom to recover"
    return {"factor": factor, "basis": basis, "confidence": drv.get("confidence", ESTIMATE_BASIS)}


# ---------------------------------------------------------------------------
# 3. Counterfactual - apply a portfolio, re-run the REAL composite
# ---------------------------------------------------------------------------
def simulate(baseline: dict, portfolio: dict) -> dict:
    """baseline: {risk: <driver-engine JSON>} for any subset of the 3 risks.
    portfolio: {intervention_id: intensity 0..1}.

    Returns before/after hazards per risk, per-driver deltas, PWI-dimension
    movement and a propagated confidence. Uses drivers.composite() unchanged.
    """
    applied, deltas = [], {}

    for iid, intensity in (portfolio or {}).items():
        spec = CATALOG.get(iid)
        if not spec or not intensity:
            continue
        resp = _response(intensity)
        feas = _feasibility(spec, baseline)
        eff_conf = _weakest(spec["confidence"], feas.get("confidence"))
        touched = []
        for dkey, max_delta in spec["effects"].items():
            drv = _find_driver(baseline, dkey)
            if not drv or drv.get("severity") is None:
                continue  # cannot improve what was never measured
            delta = max_delta * resp * feas["factor"]
            deltas[dkey] = deltas.get(dkey, 0.0) + delta
            touched.append({"driver": dkey, "risk": DRIVER_RISK.get(dkey),
                            "severity_delta": round(delta, 4),
                            "driver_source": drv.get("source"),
                            "driver_confidence": drv.get("confidence")})
        applied.append({
            "id": iid, "name": spec["name"], "intensity": round(float(intensity), 3),
            "response_factor": round(resp, 3), "feasibility": feas,
            "affects": touched, "basis": ESTIMATE_BASIS,
            "confidence": _weakest(eff_conf, *[t["driver_confidence"] for t in touched]),
            "cost_lakh_inr": round(spec["cost_lakh_inr"][0]
                                   + (spec["cost_lakh_inr"][1] - spec["cost_lakh_inr"][0])
                                   * float(intensity), 2),
        })

    results, conf_inputs = {}, []
    for risk in RISKS:
        blk = baseline.get(risk)
        if not blk or not blk.get("drivers"):
            continue
        before = composite(blk["drivers"])
        after_drivers = {}
        for dkey, d in blk["drivers"].items():
            nd = dict(d)
            if d.get("severity") is not None and dkey in deltas:
                nd["severity"] = round(max(0.0, min(1.0, d["severity"] - deltas[dkey])), 4)
                nd["severity_baseline"] = d["severity"]
                nd["severity_delta"] = round(nd["severity"] - d["severity"], 4)
                conf_inputs.append(d.get("confidence"))
            after_drivers[dkey] = nd
        after = composite(after_drivers)
        b5, a5 = before.get("hazard_0_5"), after.get("hazard_0_5")
        results[risk] = {
            "hazard_before_0_5": b5,
            "hazard_after_0_5": a5,
            "reduction_0_5": None if (b5 is None or a5 is None) else round(b5 - a5, 3),
            "reduction_pct": None if not b5 else round(100.0 * (b5 - a5) / b5, 1),
            "attribution_before": before.get("attribution_pct"),
            "attribution_after": after.get("attribution_pct"),
            "drivers_after": after_drivers,
        }

    return {
        "applied": applied,
        "per_risk": results,
        "overall": _overall(results),
        "pwi_delta": _pwi_delta(results),
        "total_cost_lakh_inr": round(sum(a["cost_lakh_inr"] for a in applied), 2),
        "confidence": _weakest(ESTIMATE_BASIS, *conf_inputs),
        "method_source": METHOD_SOURCE,
        "caveat": ("Projected reductions are model estimates on top of measured baselines, "
                   "not guaranteed outcomes. Effect coefficients are planning figures; the "
                   "baseline severities they modify are satellite-computed."),
    }


def _overall(results: dict):
    """Equal-weight mean across the risks that actually resolved (nulls excluded)."""
    b = [r["hazard_before_0_5"] for r in results.values() if r["hazard_before_0_5"] is not None]
    a = [r["hazard_after_0_5"] for r in results.values() if r["hazard_after_0_5"] is not None]
    if not b or not a:
        return {"before_0_5": None, "after_0_5": None, "reduction_0_5": None, "reduction_pct": None}
    bb, aa = sum(b) / len(b), sum(a) / len(a)
    return {"before_0_5": round(bb, 3), "after_0_5": round(aa, 3),
            "reduction_0_5": round(bb - aa, 3),
            "reduction_pct": round(100.0 * (bb - aa) / bb, 1) if bb else None,
            "risks_included": [k for k, v in results.items() if v["hazard_before_0_5"] is not None]}


def _pwi_delta(results: dict):
    """Map hazard movement onto the PWI dimensions the WSM spec assigns them to.

    Availability carries drought (drr), groundwater (gtd) and flood (rfr/cfr) in
    engine.derive_pwi_scores, so all three risks land there. Quality and
    Accessibility are NOT informed by these driver engines - reported as null
    with a reason rather than an invented number.
    """
    avail = [r["reduction_0_5"] for r in results.values() if r.get("reduction_0_5") is not None]
    improvement = round(100.0 * (sum(avail) / len(avail)) / 5.0, 1) if avail else None
    return {
        "Availability": {"improvement_pct": improvement,
                         "basis": "mean hazard reduction across drought/groundwater/flood, /5 scale",
                         "confidence": ESTIMATE_BASIS},
        "Quality": {"improvement_pct": None,
                    "basis": "not informed by the driver engines (needs effluent lab data)",
                    "confidence": "no-data"},
        "Accessibility": {"improvement_pct": None,
                          "basis": "not informed by the driver engines (needs WASH audit)",
                          "confidence": "no-data"},
    }


# ---------------------------------------------------------------------------
# 4. Volumetric benefit - m3/yr, from explicit site inputs
# ---------------------------------------------------------------------------
def water_benefit(iid: str, intensity: float, site: dict) -> dict:
    """Volumetric benefit in m3/yr. Every input is a declared site parameter or a
    documented default - never silently invented. Returns null when the required
    input is absent, with the missing field named."""
    spec = CATALOG.get(iid)
    if not spec:
        return {"m3_per_year": None, "reason": "unknown intervention"}
    resp = _response(intensity)
    roof = site.get("roof_area_m2")
    rain = site.get("annual_rainfall_mm")
    wd = site.get("withdrawal_m3_yr")
    eff = site.get("effluent_m3_yr")
    area = site.get("catchment_area_m2")
    missing, vol, formula = None, None, spec["water_model"]

    if iid == "rainwater_harvesting":
        if roof and rain:
            vol = roof * (rain / 1000.0) * 0.8 * 0.9 * resp
        else:
            missing = "roof_area_m2 and annual_rainfall_mm"
    elif iid == "wastewater_recycling":
        if eff:
            vol = eff * 0.75 * resp
        else:
            missing = "effluent_m3_yr"
    elif iid == "leak_reduction":
        if wd:
            vol = wd * 0.15 * 0.6 * resp
        else:
            missing = "withdrawal_m3_yr"
    elif iid == "process_optimization":
        if wd:
            vol = wd * 0.55 * 0.25 * resp
        else:
            missing = "withdrawal_m3_yr"
    elif iid == "managed_aquifer_recharge":
        if area and rain:
            vol = area * (rain / 1000.0) * 0.35 * resp
        else:
            missing = "catchment_area_m2 and annual_rainfall_mm"
    elif iid == "green_cover_permeable":
        if area and rain:
            vol = area * (rain / 1000.0) * 0.30 * resp
        else:
            missing = "catchment_area_m2 and annual_rainfall_mm"
    elif iid == "soil_moisture_conservation":
        if area:
            vol = area * 0.5 * 0.04 * resp
        else:
            missing = "catchment_area_m2"
    else:  # stormwater_detention - attenuation, not a consumptive saving
        return {"m3_per_year": None, "formula": formula, "basis": ESTIMATE_BASIS,
                "reason": "peak-flow attenuation, not a volumetric water saving"}

    return {"m3_per_year": None if vol is None else round(vol, 1),
            "litres_per_year": None if vol is None else round(vol * 1000.0),
            "formula": formula, "basis": ESTIMATE_BASIS, "confidence": ESTIMATE_BASIS,
            "missing_input": missing}


# ---------------------------------------------------------------------------
# 5. Optimiser - exhaustive portfolio search against a stated goal
# ---------------------------------------------------------------------------
def optimize(baseline: dict, site: dict | None = None, goal: str = "max_risk_reduction",
             intensity: float = 1.0, budget_lakh_inr: float | None = None,
             target_hazard_0_5: float | None = None, max_items: int = 4) -> dict:
    """Exhaustive search over intervention subsets (2^n, n=8 -> 256 evaluations).

    Exhaustive rather than greedy on purpose: effects interact through the [0,1]
    severity clamp and through weight renormalisation, so a greedy pick is not
    guaranteed optimal. The catalogue is small enough that we can be exact.

    goals:
      max_risk_reduction - biggest overall hazard drop within budget
      best_roi           - biggest hazard drop per lakh spent
      risk_budget        - cheapest portfolio reaching target_hazard_0_5
      max_water          - largest volumetric benefit within budget
    """
    site = site or {}
    ids = []
    for i in CATALOG:
        for d in CATALOG[i]["effects"]:
            drv = _find_driver(baseline, d)
            if drv and drv.get("severity") is not None:
                ids.append(i)
                break

    evaluated = []
    for r in range(1, min(max_items, len(ids)) + 1):
        for combo in itertools.combinations(ids, r):
            pf = {i: intensity for i in combo}
            sim = simulate(baseline, pf)
            cost = sim["total_cost_lakh_inr"]
            if budget_lakh_inr is not None and cost > budget_lakh_inr:
                continue
            water = 0.0
            for i in combo:
                wb = water_benefit(i, intensity, site)
                if wb.get("m3_per_year"):
                    water += wb["m3_per_year"]
            red = sim["overall"].get("reduction_0_5") or 0.0
            evaluated.append({
                "portfolio": list(combo),
                "names": [CATALOG[i]["name"] for i in combo],
                "cost_lakh_inr": cost,
                "hazard_before_0_5": sim["overall"].get("before_0_5"),
                "hazard_after_0_5": sim["overall"].get("after_0_5"),
                "reduction_0_5": red,
                "reduction_pct": sim["overall"].get("reduction_pct"),
                "water_m3_per_year": round(water, 1) if water else None,
                "roi_reduction_per_lakh": round(red / cost, 5) if cost else None,
                "confidence": sim["confidence"],
            })

    if not evaluated:
        return {"goal": goal, "best": None, "ranked": [],
                "reason": "no intervention affects a measured driver at this site"}

    if goal == "best_roi":
        ranked = sorted(evaluated, key=lambda e: -(e["roi_reduction_per_lakh"] or 0))
    elif goal == "max_water":
        ranked = sorted(evaluated, key=lambda e: -(e["water_m3_per_year"] or 0))
    elif goal == "risk_budget":
        if target_hazard_0_5 is None:
            return {"goal": goal, "best": None, "ranked": [],
                    "reason": "risk_budget goal requires target_hazard_0_5"}
        feasible = [e for e in evaluated
                    if e["hazard_after_0_5"] is not None
                    and e["hazard_after_0_5"] <= target_hazard_0_5]
        if not feasible:
            best_possible = min(evaluated, key=lambda e: e["hazard_after_0_5"] or 99)
            return {"goal": goal, "target_hazard_0_5": target_hazard_0_5, "best": None,
                    "ranked": sorted(evaluated, key=lambda e: e["hazard_after_0_5"] or 99)[:10],
                    "reason": ("target unreachable with the modelled catalogue; best achievable "
                               f"is {best_possible['hazard_after_0_5']}"),
                    "closest": best_possible}
        ranked = sorted(feasible, key=lambda e: (e["cost_lakh_inr"], -e["reduction_0_5"]))
    else:
        ranked = sorted(evaluated, key=lambda e: -e["reduction_0_5"])

    return {
        "goal": goal, "intensity": intensity, "budget_lakh_inr": budget_lakh_inr,
        "target_hazard_0_5": target_hazard_0_5,
        "evaluated_count": len(evaluated),
        "best": ranked[0], "ranked": ranked[:10],
        "method_source": METHOD_SOURCE,
        "caveat": ("Ranking is over modelled effect coefficients (planning estimates) applied "
                   "to satellite-computed baselines. Costs are indicative bands, not quotes."),
    }


# ---------------------------------------------------------------------------
# 6. Risk budget - how far over the acceptable threshold is this site?
# ---------------------------------------------------------------------------
def risk_budget(baseline: dict, max_acceptable_0_5: float = 3.0, site: dict | None = None,
                intensity: float = 1.0) -> dict:
    """Frames risk as a budget overrun and solves for the cheapest way back under."""
    per_risk = {}
    for risk in RISKS:
        blk = baseline.get(risk)
        if not blk or not blk.get("drivers"):
            continue
        per_risk[risk] = composite(blk["drivers"]).get("hazard_0_5")
    vals = [v for v in per_risk.values() if v is not None]
    current = round(sum(vals) / len(vals), 3) if vals else None
    if current is None:
        return {"current_0_5": None, "reason": "no measured drivers at this site"}

    over = round(current - max_acceptable_0_5, 3)
    out = {
        "max_acceptable_0_5": max_acceptable_0_5,
        "current_0_5": current,
        "per_risk": per_risk,
        "over_by_0_5": over if over > 0 else 0.0,
        "within_budget": over <= 0,
        "required_reduction_0_5": max(0.0, over),
    }
    if over <= 0:
        out["note"] = "site is already within the stated risk budget - no portfolio required"
        return out

    solution = optimize(baseline, site=site, goal="risk_budget", intensity=intensity,
                        target_hazard_0_5=max_acceptable_0_5)
    out["solution"] = solution

    singles = []
    for iid in CATALOG:
        sim = simulate(baseline, {iid: intensity})
        red = sim["overall"].get("reduction_0_5")
        if red:
            singles.append({"id": iid, "name": CATALOG[iid]["name"],
                            "reduction_0_5": red,
                            "cost_lakh_inr": sim["total_cost_lakh_inr"],
                            "confidence": sim["confidence"]})
    out["single_measure_contributions"] = sorted(singles, key=lambda s: -s["reduction_0_5"])
    return out


# ---------------------------------------------------------------------------
# 7. Evidence graph - traverse a recommendation back to the satellites
# ---------------------------------------------------------------------------
def evidence_graph(baseline: dict, iid: str, intensity: float = 1.0) -> dict:
    """Every edge is real: the recommendation's effect coefficient, the driver it
    moves, that driver's weight and attribution in the measured composite, and the
    dataset the driver was computed from."""
    spec = CATALOG.get(iid)
    if not spec:
        return {"error": "unknown intervention"}
    sim = simulate(baseline, {iid: intensity})
    nodes, edges = [], []
    root = f"rec:{iid}"
    nodes.append({"id": root, "kind": "recommendation", "label": spec["name"],
                  "basis": ESTIMATE_BASIS, "method_source": METHOD_SOURCE})
    feas_factor = _feasibility(spec, baseline)["factor"]

    for risk in RISKS:
        blk = baseline.get(risk)
        if not blk or not blk.get("drivers"):
            continue
        attr = (composite(blk["drivers"]).get("attribution_pct") or {})
        for dkey, max_delta in spec["effects"].items():
            drv = (blk.get("drivers") or {}).get(dkey)
            if not drv or drv.get("severity") is None:
                continue
            dnode = f"driver:{risk}:{dkey}"
            nodes.append({"id": dnode, "kind": "driver", "label": dkey, "risk": risk,
                          "severity": drv["severity"], "weight": drv.get("weight"),
                          "attribution_pct": attr.get(dkey),
                          "confidence": drv.get("confidence"),
                          "caveat": drv.get("caveat")})
            edges.append({"from": root, "to": dnode, "kind": "modelled_effect",
                          "max_severity_delta": max_delta,
                          "applied_delta": round(max_delta * _response(intensity) * feas_factor, 4),
                          "basis": ESTIMATE_BASIS})
            src = drv.get("source") or "unknown"
            snode = f"dataset:{src}"
            if not any(n["id"] == snode for n in nodes):
                nodes.append({"id": snode, "kind": "dataset", "label": src,
                              "confidence": drv.get("confidence")})
            edges.append({"from": dnode, "to": snode, "kind": "computed_from",
                          "confidence": drv.get("confidence")})
            rnode = f"risk:{risk}"
            if not any(n["id"] == rnode for n in nodes):
                r = sim["per_risk"].get(risk, {})
                nodes.append({"id": rnode, "kind": "risk", "label": risk,
                              "hazard_before_0_5": r.get("hazard_before_0_5"),
                              "hazard_after_0_5": r.get("hazard_after_0_5")})
            edges.append({"from": dnode, "to": rnode, "kind": "contributes_to",
                          "weight": drv.get("weight"), "attribution_pct": attr.get(dkey)})

    return {"intervention": iid, "name": spec["name"], "intensity": intensity,
            "nodes": nodes, "edges": edges,
            "projected": sim["overall"], "confidence": sim["confidence"],
            "legend": {"recommendation": "modelled action (planning estimate)",
                       "driver": "satellite-computed severity + its measured weight",
                       "dataset": "the Earth-observation source behind the driver",
                       "risk": "composite hazard, recomputed by drivers.composite()"}}


# ---------------------------------------------------------------------------
# 8. Confidence report - how trustworthy is this whole answer?
# ---------------------------------------------------------------------------
def confidence_report(baseline: dict) -> dict:
    """Per-risk evidence quality from the real confidence tags, weight-weighted."""
    SCORE = {"computed": 1.0, "proxy": 0.6, "regional": 0.5,
             "planning-estimate": 0.4, "no-data": 0.0}
    per_risk, notes = {}, []
    for risk in RISKS:
        blk = baseline.get(risk)
        if not blk or not blk.get("drivers"):
            continue
        num = den = 0.0
        tally = {}
        for dkey, d in blk["drivers"].items():
            w = d.get("weight") or 0.0
            c = d.get("confidence") or "no-data"
            tally[c] = tally.get(c, 0) + 1
            num += SCORE.get(c, 0.0) * w
            den += w
            if c == "regional" and d.get("caveat"):
                notes.append(f"{risk}/{dkey}: {d['caveat']}")
        per_risk[risk] = {"evidence_quality_pct": round(100.0 * num / den, 1) if den else None,
                          "confidence_mix": tally}
    vals = [v["evidence_quality_pct"] for v in per_risk.values()
            if v["evidence_quality_pct"] is not None]
    return {"per_risk": per_risk,
            "overall_evidence_pct": round(sum(vals) / len(vals), 1) if vals else None,
            "scale": SCORE, "notes": notes,
            "note": ("Evidence quality is weight-weighted over the driver confidence tags "
                     "already produced by the engines - no new judgement is introduced here.")}
