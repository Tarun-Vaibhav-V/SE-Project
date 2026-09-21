"""PS3 — LLM intervention planner (brief steps 14–17).

Reads the computed PWI outcome for one or many sites (the 3×3 gaps, matrix,
water balance and LIVE basin context) and asks Groq to recommend interventions
tailored to the basin's conditions — each with duration, estimated water benefit,
expected PWI gain, cost band, priority and phase — plus a phased implementation
roadmap and a portfolio narrative.

Honesty rules (same spine as explain.py):
- FACTS (which gap, current score, basin numbers) come from the computed engine data.
- ESTIMATES (duration, cost, m³ benefit, PWI gain) are planning figures anchored to the
  methodology's own typical ranges (INTERVENTION_META, from the WSM 4-Step framework),
  labelled `basis: planning-estimate` with a confidence — never sold as measured.
- Expected PWI gain is clamped to the cell's actual gap so no recommendation can
  over-promise past 100%.
- If Groq is unavailable or returns junk → deterministic fallback straight from the
  catalog + gaps (engine: "template"), so a plan is always produced.
"""
import json
import os

# Candidate interventions with methodology-grounded metadata (WSM Step 2/3 sheets):
# (pillar, dimension) -> list of {name, duration, cost_band, benefit_basis, suits_when}
INTERVENTION_META = {
    ("P1", "Availability"): [
        {"name": "Water-efficiency programme (metering, leak repair, process opt.)",
         "duration": "6–18 months", "cost_band": "Low–Medium",
         "benefit_basis": "cuts withdrawal ~10–30%", "suits_when": "high withdrawal or water-stressed basin"},
        {"name": "Recycling / reuse system",
         "duration": "6–12 months", "cost_band": "Medium–High",
         "benefit_basis": "displaces freshwater by recycled volume", "suits_when": "large effluent volume"},
        {"name": "Rainwater harvesting",
         "duration": "3–6 months", "cost_band": "Low",
         "benefit_basis": "yield = roof area × rainfall × runoff coeff", "suits_when": "adequate rainfall"},
    ],
    ("P1", "Quality"): [
        {"name": "WWTP upgrade / optimization",
         "duration": "6–18 months", "cost_band": "Medium–High",
         "benefit_basis": "raises pollutant removal toward ≥90%", "suits_when": "effluent near/over limits"},
        {"name": "Chemical substitution (ZDHC MRSL)",
         "duration": "6–12 months", "cost_band": "Low–Medium",
         "benefit_basis": "reduces hazardous chemical load", "suits_when": "textile / chemical-intensive site"},
    ],
    ("P1", "Access"): [
        {"name": "Install WASH facilities (toilets / handwash / drinking water)",
         "duration": "3–6 months", "cost_band": "Low",
         "benefit_basis": "meets ILO ratios (≤22:1 toilets, ≤6:1 handwash)", "suits_when": "ratios below standard"},
        {"name": "WASH awareness & training",
         "duration": "ongoing", "cost_band": "Low",
         "benefit_basis": "raises worker WASH satisfaction", "suits_when": "low hygiene awareness"},
    ],
    ("P2", "Availability"): [
        {"name": "Replenishment (wetland restoration / managed aquifer recharge)",
         "duration": "12–24 months", "cost_band": "High",
         "benefit_basis": "m³ replenished toward site withdrawal", "suits_when": "over-abstracted sub-basin"},
        {"name": "Basin stakeholder engagement",
         "duration": "ongoing", "cost_band": "Low",
         "benefit_basis": "enables shared water action", "suits_when": "many competing basin users"},
    ],
    ("P2", "Quality"): [
        {"name": "Constructed wetland / riparian buffer zones",
         "duration": "12–24 months", "cost_band": "Medium",
         "benefit_basis": "cuts downstream pollutant load", "suits_when": "degraded receiving water"},
    ],
    ("P2", "Access"): [
        {"name": "Community WASH project (water points, sanitation, hygiene)",
         "duration": "6–18 months", "cost_band": "Medium",
         "benefit_basis": "people gaining safe water/sanitation", "suits_when": "community WASH gap near site"},
    ],
    ("P3", "Availability"): [
        {"name": "Basin stewardship coalition & policy engagement",
         "duration": "multi-year (ongoing)", "cost_band": "Low–Medium",
         "benefit_basis": "collective withdrawal management", "suits_when": "WRC priority / high-stress basin"},
        {"name": "Large-scale basin replenishment (landscape NBS)",
         "duration": "12–24 months", "cost_band": "High",
         "benefit_basis": "landscape-scale m³ recharged", "suits_when": "high basin water stress"},
    ],
    ("P3", "Quality"): [
        {"name": "Basin pollution-reduction collaboration",
         "duration": "12–24 months", "cost_band": "Medium",
         "benefit_basis": "share of basin load reduction", "suits_when": "polluted basin, many dischargers"},
    ],
    ("P3", "Access"): [
        {"name": "Basin WASH public-private partnership (SDG 6)",
         "duration": "12–24 months", "cost_band": "High",
         "benefit_basis": "basin WASH gap closure", "suits_when": "low national/basin WASH coverage"},
    ],
}

ALLOWED_NAMES = {i["name"] for lst in INTERVENTION_META.values() for i in lst}

SYSTEM_PROMPT = """You are a corporate water-stewardship strategist. You will receive computed
Positive Water Impact (PWI) results for one or more factory sites — the 3x3 pillar/dimension gaps,
plus LIVE basin water/WASH figures. Recommend an intervention plan.

HARD RULES:
- Choose interventions ONLY from the provided candidate catalog (use the exact `name`).
- Prioritise by the largest gaps and by fit to the basin conditions in the data (e.g. low renewable
  freshwater or high withdrawal% -> favour replenishment/efficiency; low sanitation% -> favour WASH).
- Each recommendation object MUST use these exact keys:
  - "site": Site name
  - "pillar": "P1" or "P2" or "P3"
  - "dimension": "Availability" or "Quality" or "Access"
  - "intervention": the exact catalog name
  - "problem": Clear description of the gap or stressor (e.g., "The Chennai plant has a critical 66.7% gap in wastewater treatment compliance.")
  - "solution_brief": What this intervention actually does to fix the problem (e.g., "Upgrade the on-site wastewater treatment plant to raise pollutant removal above 90%.")
  - "priority_rationale": A detailed, professional explanation of why this priority (High, Medium, Low) was selected. Be explicit about what High/Medium/Low means in terms of urgency, compliance risk, and impact (e.g., "High priority because uncompliant effluent represents an immediate regulatory and reputational threat to site operations.")
  - "duration": copy from catalog
  - "cost_band": copy from catalog
  - "priority": "High" or "Medium" or "Low"
  - "phase": 1 or 2 or 3
  - "est_pwi_gain_pct": PWI gain estimate, never larger than that cell's gap
  - "confidence": 0-100
- Include a spread across phases where gaps exist (not only basin-level items).
- Return STRICT JSON only: {"recommendations":[...],"roadmap":[{"phase":1,"focus":"...","items":["..."]}],
  "narrative":"<=3 sentences"}. No markdown, no preamble."""


def _site_brief(result: dict) -> dict:
    """Compact, LLM-friendly view of one computed site result."""
    site = result.get("site", {})
    gaps = [{"pillar": g["pillar"], "dimension": g["dimension"], "current_pct": g["current_pct"],
             "gap_pct": g["gap_pct"]} for g in result.get("targets_gap_projection", {}).get("gaps", [])]
    ctx = result.get("basin_context") or {}
    ctx_small = {m["indicator"]: f'{m["value"]} {m["unit"]}'
                 for m in ctx.get("metrics", []) if m.get("value") is not None}
    return {
        "site": site.get("name"), "industry": site.get("industry"),
        "site_pwi_pct": result.get("site_pwi", {}).get("value"),
        "pillar_scores": {p: result.get("pillars", {}).get(p, {}).get("value") for p in ("P1", "P2", "P3")},
        "gaps": gaps, "basin_context_real": ctx_small,
    }


def _catalog_for_prompt() -> list:
    return [{"pillar": p, "dimension": d, **i} for (p, d), lst in INTERVENTION_META.items() for i in lst]


def _clamp_gain(rec: dict, gap_lookup: dict) -> dict:
    """Never let an estimated PWI gain exceed the real gap for that (site,pillar,dimension)."""
    key = (rec.get("site"), rec.get("pillar"), rec.get("dimension"))
    gap = gap_lookup.get(key)
    try:
        g = float(rec.get("est_pwi_gain_pct"))
        if gap is not None:
            g = min(g, gap)
        rec["est_pwi_gain_pct"] = round(g, 1)
    except (TypeError, ValueError):
        rec["est_pwi_gain_pct"] = None
    return rec


def _fallback(briefs: list, gap_lookup: dict) -> dict:
    """Deterministic plan from the catalog + gaps (no LLM). Always grounded."""
    recs = []
    pnames = {"P1": "Site", "P2": "Sub-Basin", "P3": "Basin"}
    for b in briefs:
        # largest-gap dimension in EACH pillar -> a balanced roadmap across phases
        for pil in ("P1", "P2", "P3"):
            pil_gaps = [g for g in b["gaps"] if g["pillar"] == pil]
            if not pil_gaps:
                continue
            g = max(pil_gaps, key=lambda x: x["gap_pct"])
            cands = INTERVENTION_META.get((g["pillar"], g["dimension"]), [])
            if not cands:
                continue
            it = cands[0]
            phase = 1 if g["pillar"] == "P1" else 2 if g["pillar"] == "P2" else 3
            pri = "High" if g["gap_pct"] >= 60 else "Medium"
            recs.append({
                "site": b["site"], "pillar": g["pillar"], "dimension": g["dimension"],
                "intervention": it["name"],
                "problem": f'{g["dimension"]} score is currently {g["current_pct"]}% with a remaining gap of {g["gap_pct"]}%.',
                "solution_brief": f'Implement {it["name"]} to address {it["suits_when"]}.',
                "priority_rationale": f'{pri} priority chosen because this cell has a major gap of {g["gap_pct"]}% at the {pnames.get(pil, pil)} level, requiring urgent mitigation.',
                "duration": it["duration"], "cost_band": it["cost_band"],
                "priority": pri,
                "phase": phase, "est_pwi_gain_pct": round(g["gap_pct"] * 0.2, 1), "confidence": 55,
            })
    roadmap = [
        {"phase": 1, "focus": "Site (P1) quick wins — efficiency, WWTP, WASH", "items": [r["intervention"] for r in recs if r["phase"] == 1][:5]},
        {"phase": 2, "focus": "Sub-basin (P2) — replenishment, community WASH", "items": [r["intervention"] for r in recs if r["phase"] == 2][:5]},
        {"phase": 3, "focus": "Basin (P3) — coalitions, PPP, collective action", "items": [r["intervention"] for r in recs if r["phase"] == 3][:5]},
    ]
    return {"recommendations": recs, "roadmap": roadmap,
            "narrative": "Deterministic plan from the methodology catalog: close the largest gaps first at "
                         "site level, then sub-basin, then basin, on a 20/40/40 phasing.",
            "engine": "template"}


def recommend(site_results: list) -> dict:
    """Portfolio-aware intervention plan. site_results = list of engine outputs (site_pwi())."""
    briefs = [_site_brief(r) for r in site_results]
    gap_lookup = {}
    for b in briefs:
        for g in b["gaps"]:
            gap_lookup[(b["site"], g["pillar"], g["dimension"])] = g["gap_pct"]

    portfolio_pwi = None
    vals = [b["site_pwi_pct"] for b in briefs if b["site_pwi_pct"] is not None]
    if vals:
        portfolio_pwi = round(sum(vals) / len(vals), 1)

    out = None
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                temperature=0.3, max_tokens=1400,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps({
                        "sites": briefs, "portfolio_pwi_pct": portfolio_pwi,
                        "candidate_catalog": _catalog_for_prompt(),
                        "phasing": "20% site / 40% sub-basin / 40% basin"})},
                ],
            )
            parsed = json.loads(resp.choices[0].message.content)
            recs = []
            for r in parsed.get("recommendations", []):
                # tolerate key drift (intervention / intervention_name / name)
                name = r.get("intervention") or r.get("intervention_name") or r.get("name")
                if name in ALLOWED_NAMES:
                    r["intervention"] = name
                    recs.append(r)
            if recs:
                recs = [_clamp_gain(r, gap_lookup) for r in recs]
                out = {"recommendations": recs,
                       "roadmap": parsed.get("roadmap", []),
                       "narrative": parsed.get("narrative", ""),
                       "engine": "groq"}
        except Exception:
            out = None

    if out is None:
        out = _fallback(briefs, gap_lookup)

    out.update({
        "portfolio_pwi_pct": portfolio_pwi,
        "n_sites": len(site_results),
        "disclaimer": ("Durations, cost bands and water/PWI benefits are PLANNING ESTIMATES anchored to "
                       "the methodology's typical ranges — not site-measured. Gaps and basin numbers are "
                       "from the computed engine data."),
        "source": "Groq LLM over computed PWI gaps + live basin context; catalog from WSM Step 2/3",
    })
    return out


def pwi_chat(message: str, history: list[dict], results: list[dict]) -> str:
    """Conversational assistant for the Positive Water Impact (PWI) plan, specifically tuned
    for senior Apple/Nvidia-grade reviewers to drill into the gaps and recommendations."""
    import os
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "The PWI Chat Assistant is offline because GROQ_API_KEY is not configured in the backend environment."
    
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        
        briefs = [_site_brief(r) for r in results]
        catalog = _catalog_for_prompt()
        
        system_content = f"""You are the Hydris Positive Water Impact (PWI) Strategic Advisor, an expert in water stewardship.
You are conversing with a senior reviewer (from Apple or Nvidia) who is evaluating this project.

Here is the context of the computed PWI Site results and the recommended intervention plan:
Computed Site Results: {json.dumps(briefs)}
Candidate Interventions: {json.dumps(catalog)}

Your role:
- Answer the user's questions about their Positive Water Impact (PWI) score, 3x3 matrix, and the recommended intervention roadmap.
- Provide professional, technically sound, and data-grounded insights.
- Cite specific metrics from the results (e.g. current scores, gaps, World Bank context) and specific recommendations (WWTP upgrades, efficiency programs).
- Keep answers structured, concise (maximum 3-4 sentences/paragraphs), and executive-consumable.
- Maintain a premium, professional, helpful tone suitable for senior tech executives.
- If the user asks about the certification process, explain the trust ladder (Self-Certified, Conditional, In Progress, etc.) and penalties (like XV-05).
- Do not make up numbers. Use the computed results provided.
"""
        messages = [{"role": "system", "content": system_content}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})
        
        resp = client.chat.completions.create(
            model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=0.7,
            max_tokens=600,
            messages=messages
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Sorry, I encountered an error while processing your request: {str(e)}"

