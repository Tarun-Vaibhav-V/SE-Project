"""PS5 — Evidence & Disclosure Agent.

Pipeline (matches the brief): Ingest → Classify → Extract → Map → Gap-detect →
Citation-backed CDP disclosure draft.

- INGEST     : accept document text (PDFs/xlsx are turned to text upstream).
- CLASSIFY   : Groq tags each artefact type (permit, lab report, WWTP, meter,
               WASH audit, stewardship, ZDHC, policy). Keyword fallback if no LLM.
- EXTRACT    : Groq pulls structured metadata + a verbatim citation span per doc.
- MAP        : rule-based artefact-type → CDP Water Security question(s).
- GAP-DETECT : CDP questions with no evidence (MISSING), permits past validity
               (EXPIRED), reports older than 12 months (STALE).
- DRAFT      : Groq writes each covered CDP response, citing the source document.
               Deterministic template fallback so a draft is always produced.

Honesty spine (same as the rest of Hydris): every drafted claim cites a real
document; missing evidence is reported as a GAP, never fabricated; extraction
carries a confidence; nothing is invented.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import formulas

# ---------------------------------------------------------------------------
# CDP Water Security question catalogue (subset a factory's docs typically feed)
# ---------------------------------------------------------------------------
CDP_QUESTIONS = {
    "W1.2":  {"module": "W1 Current state", "text": "Total water withdrawals, discharges and consumption for the reporting year."},
    "W1.2b": {"module": "W1 Current state", "text": "Water withdrawals by source (ground / surface / municipal / rain / recycled)."},
    "W1.4":  {"module": "W1 Current state", "text": "Provision of safe WASH (water, sanitation, hygiene) in own operations."},
    "W5.1":  {"module": "W5 Facility-level water accounting", "text": "Facility-level water accounting (withdrawal, discharge, consumption)."},
    "W5.1a": {"module": "W5 Facility-level water accounting", "text": "Wastewater discharge quality and treatment (BOD/COD/TSS/pH vs permit limits)."},
    "W6.1":  {"module": "W6 Governance", "text": "Water policy, regulatory permits and compliance."},
    "W8.1":  {"module": "W8 Targets & goals", "text": "Water targets/goals and stewardship (replenishment, efficiency)."},
    "W9.1":  {"module": "W9 Verification", "text": "Third-party verification / assurance of reported water data."},
}

# artefact type -> the CDP questions it can evidence
ARTEFACT_CDP_MAP = {
    "discharge_permit":        ["W5.1a", "W6.1"],
    "effluent_lab_report":     ["W5.1a", "W9.1"],
    "wwtp_performance":        ["W5.1a"],
    "meter_water_balance":     ["W1.2", "W1.2b", "W5.1"],
    "wash_audit":              ["W1.4"],
    "stewardship_replenishment": ["W8.1"],
    "zdhc_chemical":           ["W5.1a"],
    "policy":                  ["W6.1"],
    "other":                   [],
}

ARTEFACT_LABEL = {
    "discharge_permit": "Discharge Permit", "effluent_lab_report": "Effluent Lab Report",
    "wwtp_performance": "WWTP Performance Report", "meter_water_balance": "Meter / Water-Balance Record",
    "wash_audit": "WASH Audit", "stewardship_replenishment": "Stewardship / Replenishment Report",
    "zdhc_chemical": "ZDHC / Chemical Record", "policy": "Policy / Governance", "other": "Other",
}

STALE_MONTHS = 12

# ---------------------------------------------------------------------------
# Labeled SYNTHETIC sample documents (⚠ not real — for demonstrating the pipeline)
# ---------------------------------------------------------------------------
SAMPLE_DOCS = [
    {"name": "Consent_to_Operate_TNPCB.pdf", "text": """
[SYNTHETIC SAMPLE — not a real permit]
TAMIL NADU POLLUTION CONTROL BOARD
CONSENT TO OPERATE under the Water (Prevention & Control of Pollution) Act 1974
Consent Order No: TNPCB/CTO/CHN/2023/44871
Industry: Demo Apparel Co. — Chennai textile unit, Ambattur, Chennai, Tamil Nadu
Valid from: 01-Jan-2023   Valid until: 31-Dec-2024
Prescribed effluent discharge limits: BOD 30 mg/L, COD 250 mg/L, TSS 100 mg/L, pH 6.5-8.5
Authorised discharge: 300 KLD to CETP. Zero liquid discharge not applicable.
"""},
    {"name": "Effluent_Lab_Report_May2026.pdf", "text": """
[SYNTHETIC SAMPLE — not a real lab report]
NABL-ACCREDITED ENVIRONMENTAL LABORATORY — Test Report
Client: Demo Apparel Co., Chennai unit    Sample: Final treated effluent (WWTP outlet)
Date of sampling: 15-May-2026    Monitoring frequency: monthly
Results (mg/L): BOD 22, COD 180, TSS 45, pH 7.2
Remark: all parameters within TNPCB consent limits. Lab accreditation: NABL ISO/IEC 17025.
"""},
    {"name": "Water_Balance_FY2025.xlsx", "text": """
[SYNTHETIC SAMPLE — not real meter data]
DEMO APPAREL CO. — CHENNAI — ANNUAL WATER BALANCE FY2025 (SCADA + meters)
Total freshwater withdrawal: 520,000 m3/yr
By source: groundwater 40%, surface 30%, municipal 20%, rainwater 5%, recycled 5%
Water recycled: 60,000 m3/yr   Water reused: 25,000 m3/yr
Wastewater generated: 300,000 m3/yr   Wastewater treated: 285,000 m3/yr   Discharged: 285,000 m3/yr
"""},
    {"name": "WASH_Audit_2026.pdf", "text": """
[SYNTHETIC SAMPLE — not a real audit]
WORKPLACE WASH AUDIT — Demo Apparel Co., Chennai
Workers: 1800.  Toilets: 90 (ratio 20:1).  Washbasins: 320 (ratio 5.6:1).
Drinking water: 6 stations, quality tested quarterly, compliant.
Hygiene training: annual. Overall WASH status: compliant with ILO ratios.
"""},
    {"name": "Replenishment_Project_Brief.pdf", "text": """
[SYNTHETIC SAMPLE — not a real project report]
SUB-BASIN REPLENISHMENT PROJECT — constructed wetland restoration
Site: near Chennai unit.  Wetland area: 12 ha.  Recharge rate: 3,750 m3/ha/yr.
Claimed annual recharge benefit: 45,000 m3/yr.
Status: implemented FY2025. Independent verification: PENDING (not yet third-party verified).
Water stewardship target: reach net-positive availability at sub-basin by 2030.
"""},
    {"name": "Rainwater_Harvesting_Claim.pdf", "text": """
[SYNTHETIC SAMPLE — not a real intervention report]
STEWARDSHIP INTERVENTION — ROOFTOP RAINWATER HARVESTING (Chennai unit)
Catchment (roof) area: 5,000 m2.  Runoff coefficient: 0.8 (metal roof).
Claimed annual harvested water benefit: 4,000 m3/yr.
(Rainfall not stated — to be verified against satellite rainfall.)
"""},
    {"name": "Groundwater_Recharge_Claim.pdf", "text": """
[SYNTHETIC SAMPLE — not a real intervention report]
STEWARDSHIP INTERVENTION — MANAGED GROUNDWATER RECHARGE (Chennai unit)
Recharge basin area: 10,000 m2.  Recharge coefficient: 0.3.
Claimed annual recharge benefit: 30,000 m3/yr.
"""},
]

# ---------------------------------------------------------------------------
# Groq helpers
# ---------------------------------------------------------------------------
_LAST_LLM_ERROR: str | None = None


def _note_llm_failure(e: Exception):
    """Remember WHY the LLM path degraded so the result can disclose it."""
    global _LAST_LLM_ERROR
    s = str(e)
    _LAST_LLM_ERROR = ("Groq rate limit reached (daily token cap) - retry later"
                       if "rate_limit" in s or "429" in s else f"Groq error: {s[:100]}")


def _groq():
    from groq import Groq
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def _model():
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


CLASSIFY_PROMPT = """You classify a single factory water-stewardship document and extract metadata.
Return STRICT JSON with keys:
"type" (one of: discharge_permit, effluent_lab_report, wwtp_performance, meter_water_balance,
 wash_audit, stewardship_replenishment, zdhc_chemical, policy, other),
"type_confidence" (0-100),
"site" (string|null), "issuing_authority" (string|null),
"doc_date" (YYYY-MM-DD|null), "validity_end" (YYYY-MM-DD|null),
"parameters" ({"BOD":num|null,"COD":num|null,"TSS":num|null,"pH":num|null}),
"volumes_m3_yr" ({"withdrawal":num|null,"discharge":num|null,"recycled":num|null,"replenished":num|null}),
"accredited" (true|false), "monitoring_frequency" (string|null),
"citation_quote" (a short verbatim span, <=140 chars, that justifies the classification).
Use ONLY facts present in the text; unknown fields = null. No markdown."""


# ---------------------------------------------------------------------------
# Keyword fallback classifier (no LLM)
# ---------------------------------------------------------------------------
_KW = [
    ("discharge_permit", ("consent to operate", "pollution control board", "consent order", "permit")),
    ("effluent_lab_report", ("lab report", "test report", "nabl", "sampling", "effluent")),
    ("wwtp_performance", ("wwtp", "treatment plant performance", "removal efficiency")),
    ("meter_water_balance", ("water balance", "withdrawal", "scada", "meter")),
    ("wash_audit", ("wash audit", "toilets", "washbasins", "drinking water")),
    ("stewardship_replenishment", ("replenish", "wetland", "aquifer recharge", "stewardship")),
    ("zdhc_chemical", ("zdhc", "mrsl", "chemical")),
    ("policy", ("policy", "governance")),
]


def _kw_classify(text: str) -> dict:
    low = text.lower()
    best, hits = "other", 0
    for typ, kws in _KW:
        n = sum(k in low for k in kws)
        if n > hits:
            best, hits = typ, n
    m = re.search(r"valid until[:\s]*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.I)
    return {"type": best, "type_confidence": 60 if hits else 30,
            "site": None, "issuing_authority": None, "doc_date": None,
            "validity_end": _norm_date(m.group(1)) if m else None,
            "parameters": {"BOD": None, "COD": None, "TSS": None, "pH": None},
            "volumes_m3_yr": {"withdrawal": None, "discharge": None, "recycled": None, "replenished": None},
            "accredited": "nabl" in low or "iso/iec 17025" in low,
            "monitoring_frequency": None,
            "citation_quote": text.strip().split("\n")[1][:140] if "\n" in text.strip() else text[:140]}


def _norm_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def classify_extract(doc: dict) -> dict:
    """One document -> {name, type, metadata..., engine}."""
    text = doc["text"]
    meta = None
    if os.environ.get("GROQ_API_KEY"):
        try:
            resp = _groq().chat.completions.create(
                model=_model(), temperature=0.0, max_tokens=600,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": CLASSIFY_PROMPT},
                          {"role": "user", "content": text[:4000]}])
            meta = json.loads(resp.choices[0].message.content)
            meta["validity_end"] = _norm_date(meta.get("validity_end"))
            meta["doc_date"] = _norm_date(meta.get("doc_date"))
            meta["_engine"] = "groq"
        except Exception as e:
            _note_llm_failure(e)
            meta = None
    if meta is None:
        meta = _kw_classify(text)
        meta["_engine"] = "keyword"
    meta["name"] = doc["name"]
    meta["type_label"] = ARTEFACT_LABEL.get(meta.get("type"), "Other")
    return meta


# ---------------------------------------------------------------------------
# EXTRACT intervention benefit CLAIMS (for formula verification)
# ---------------------------------------------------------------------------
CLAIMS_PROMPT = """Extract water-stewardship INTERVENTION benefit claims from the document.

Extract a claim ONLY when the document EXPLICITLY describes a stewardship intervention/project with a
stated annual benefit number (e.g. "rainwater harvesting ... claimed 4,000 m3/yr"). Do NOT invent claims
from a water-balance table, meter readings, permit limits or operational volumes — those are not
intervention claims. If a project combines techniques, output at most ONE claim for its primary technique.
If the document contains no explicit intervention claim, return {"claims":[]}.

For each claim return an object with:
"intervention" (one of: rainwater_harvesting, groundwater_recharge, check_dam, wastewater_reuse,
 leak_reduction, industrial_efficiency, drip_irrigation, wetland_restoration, afforestation),
"claimed_value" (number, the stated annual benefit), "claimed_unit" (e.g. "m3/yr"),
"params" (object with any of: catchment_area_m2, runoff_coeff, rainfall_mm, area_m2, recharge_coeff,
 length_m, width_m, depth_m, recharge_efficiency, treated_m3, discharged_m3, baseline_m3, current_m3,
 conventional_m3, drip_m3, wetland_area_ha, recharge_rate, forest_area_ha, recharge_improvement_factor).
Use ONLY numbers present in the text; unknown = null. Return STRICT JSON {"claims":[...]}. No markdown."""

_CLAIM_KW = {
    "rainwater": "rainwater_harvesting", "rooftop": "rainwater_harvesting",
    "groundwater recharge": "groundwater_recharge", "managed recharge": "groundwater_recharge",
    "check dam": "check_dam", "wastewater reuse": "wastewater_reuse", "reuse": "wastewater_reuse",
    "leak": "leak_reduction", "efficiency": "industrial_efficiency", "drip": "drip_irrigation",
    "wetland": "wetland_restoration", "afforest": "afforestation",
}


def extract_claims(doc: dict, doc_type: str | None = None) -> list:
    """Pull intervention benefit claims + their parameters from one document."""
    text = doc["text"]
    if os.environ.get("GROQ_API_KEY"):
        try:
            resp = _groq().chat.completions.create(
                model=_model(), temperature=0.0, max_tokens=700,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": CLAIMS_PROMPT},
                          {"role": "user", "content": text[:4000]}])
            claims = json.loads(resp.choices[0].message.content).get("claims", [])
            out = [c for c in claims if c.get("intervention") in formulas.INTERVENTION_FORMULAS]
            for c in out:
                c["engine"] = "groq"
            return out
        except Exception as e:
            _note_llm_failure(e)
    # keyword fallback. Intervention claims only live in stewardship documents —
    # never mint a "claim" out of a water-balance table, lab report or permit
    # (the old fallback turned the 520,000 m3/yr withdrawal row into a fake
    # rainwater-harvesting claim).
    if doc_type not in (None, "stewardship_replenishment", "other"):
        return []
    low = text.lower()
    itype = next((v for k, v in _CLAIM_KW.items() if k in low), None)
    if not itype:
        return []
    # prefer the m3/yr figure on the line that states the claim/benefit
    val = None
    for line in text.splitlines():
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*m3\s*/?\s*yr", line, re.I)
        if m and re.search(r"claim|benefit", line, re.I):
            val = float(m.group(1).replace(",", ""))
            break
    if val is None:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*m3\s*/?\s*yr", text, re.I)
        val = float(m.group(1).replace(",", "")) if m else None
    return [{"intervention": itype, "claimed_value": val, "claimed_unit": "m3/yr",
             "params": {}, "engine": "keyword"}]


# ---------------------------------------------------------------------------
# MAP + GAP-DETECT
# ---------------------------------------------------------------------------
def map_to_cdp(artefacts: list) -> dict:
    """cdp_id -> list of supporting document names."""
    cov = {q: [] for q in CDP_QUESTIONS}
    for a in artefacts:
        for q in ARTEFACT_CDP_MAP.get(a.get("type"), []):
            # W9.1 (verification) only if the report is accredited/verified
            if q == "W9.1" and not a.get("accredited"):
                continue
            cov[q].append(a["name"])
    return cov


def detect_gaps(artefacts: list, coverage: dict) -> list:
    today = date.today()
    gaps = []
    # MISSING: CDP questions with no supporting evidence
    for q, docs in coverage.items():
        if not docs:
            gaps.append({"kind": "MISSING", "cdp_id": q, "module": CDP_QUESTIONS[q]["module"],
                         "detail": f"No document evidences {q} — {CDP_QUESTIONS[q]['text']}"})
    # EXPIRED permits / STALE reports
    for a in artefacts:
        ve = a.get("validity_end")
        if ve:
            try:
                if datetime.fromisoformat(ve).date() < today:
                    gaps.append({"kind": "EXPIRED", "cdp_id": None, "document": a["name"],
                                 "detail": f"{a['type_label']} '{a['name']}' validity ended {ve} (before {today.isoformat()})."})
            except ValueError:
                pass
        dd = a.get("doc_date")
        if dd and a.get("type") == "effluent_lab_report":
            try:
                age_m = (today - datetime.fromisoformat(dd).date()).days / 30.4
                if age_m > STALE_MONTHS:
                    gaps.append({"kind": "STALE", "cdp_id": "W5.1a", "document": a["name"],
                                 "detail": f"Lab report '{a['name']}' is {age_m:.0f} months old (> {STALE_MONTHS})."})
            except ValueError:
                pass
    return gaps


# ---------------------------------------------------------------------------
# DRAFT (citation-backed)
# ---------------------------------------------------------------------------
DRAFT_PROMPT = """You are a corporate water-disclosure writer. Draft CDP Water Security responses.
You receive: the CDP questions to answer, and the extracted evidence artefacts (with metadata).
RULES:
- Use ONLY facts present in the artefacts. Never invent numbers, dates or authorities.
- Every response MUST cite the source document(s) inline like [Water_Balance_FY2025.xlsx].
- If a figure is not in the evidence, say it is not available — do not guess.
- 2-4 sentences per question, factual disclosure tone.
Return STRICT JSON: {"responses":[{"cdp_id":"W1.2","text":"...","citations":["doc.pdf"]}]}. No markdown."""


def _template_draft(coverage: dict, artefacts: list) -> dict:
    by_name = {a["name"]: a for a in artefacts}
    responses = []
    for q, docs in coverage.items():
        if not docs:
            continue
        bits = []
        for d in docs:
            a = by_name.get(d, {})
            facts = []
            for k, v in (a.get("volumes_m3_yr") or {}).items():
                if v is not None:
                    facts.append(f"{k} {v} m³/yr")
            for k, v in (a.get("parameters") or {}).items():
                if v is not None:
                    facts.append(f"{k} {v}")
            bits.append(f"{a.get('type_label','doc')} [{d}]" + (f": {', '.join(facts)}" if facts else ""))
        responses.append({"cdp_id": q, "text": f"Evidence for {q} ({CDP_QUESTIONS[q]['text']}): " + "; ".join(bits) + ".",
                          "citations": docs})
    return {"responses": responses, "engine": "template"}


def draft_disclosure(coverage: dict, artefacts: list) -> dict:
    covered = {q: docs for q, docs in coverage.items() if docs}
    if not covered:
        return {"responses": [], "engine": "template"}
    if os.environ.get("GROQ_API_KEY"):
        try:
            payload = {
                "cdp_questions": {q: CDP_QUESTIONS[q] for q in covered},
                "coverage": covered,
                "artefacts": [{k: a.get(k) for k in ("name", "type_label", "issuing_authority", "doc_date",
                                                     "validity_end", "parameters", "volumes_m3_yr",
                                                     "accredited", "citation_quote")} for a in artefacts],
            }
            resp = _groq().chat.completions.create(
                model=_model(), temperature=0.1, max_tokens=1600,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": DRAFT_PROMPT},
                          {"role": "user", "content": json.dumps(payload, default=str)}])
            parsed = json.loads(resp.choices[0].message.content)
            resps = [r for r in parsed.get("responses", []) if r.get("cdp_id") in covered]
            if resps:
                return {"responses": resps, "engine": "groq"}
        except Exception:
            pass
    return _template_draft(coverage, artefacts)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_pipeline(docs: list, lat: float | None = None, lng: float | None = None,
                 site: dict | None = None, persist: bool = False) -> dict:
    artefacts = [classify_extract(d) for d in docs]
    coverage = map_to_cdp(artefacts)
    gaps = detect_gaps(artefacts, coverage)
    draft = draft_disclosure(coverage, artefacts)
    answered = sum(1 for q, ds in coverage.items() if ds)
    coverage_pct = round(100 * answered / len(CDP_QUESTIONS), 1)

    # --- claim verification (recompute vs GEE/formula) + A–F grading ---
    rain_m = formulas.gee_annual_rainfall_m(lat, lng) if (lat is not None and lng is not None) else None
    verified_claims = []
    for a, d in zip(artefacts, docs):
        for cl in extract_claims(d, a.get("type")):
            v = formulas.verify_claim(cl, lat, lng, doc_confidence=a.get("type_confidence", 70), rain_m=rain_m)
            v["document"] = d["name"]
            v["extraction_engine"] = cl.get("engine")
            verified_claims.append(v)
    grading = formulas.overall_grade(verified_claims, coverage_pct)

    # disclose LLM degradation instead of silently grading everything F:
    # keyword extraction can't pull formula parameters, so claims land in
    # "insufficient_inputs" — the reader must know that's a quota issue, not fraud
    kw_steps = (sum(1 for x in artefacts if x.get("_engine") == "keyword")
                + sum(1 for c in verified_claims if c.get("extraction_engine") == "keyword"))
    llm_status = ({"degraded": True,
                   "reason": _LAST_LLM_ERROR or "GROQ_API_KEY not configured",
                   "impact": ("keyword fallback used for some extraction steps; formula "
                              "parameters may be missing, so affected claims read "
                              "'insufficient inputs' instead of being verified")}
                  if kw_steps else {"degraded": False})

    result = {
        "artefacts": artefacts,
        "coverage": {q: {"question": CDP_QUESTIONS[q]["text"], "module": CDP_QUESTIONS[q]["module"],
                         "documents": ds, "covered": bool(ds)} for q, ds in coverage.items()},
        "gaps": gaps,
        "claims": verified_claims,
        "grading": grading,
        "llm_status": llm_status,
        "draft": draft,
        "summary": {"documents": len(docs), "cdp_questions": len(CDP_QUESTIONS),
                    "answered": answered, "coverage_pct": coverage_pct, "gaps": len(gaps),
                    "claims": len(verified_claims), "cdp_grade": grading["cdp_grade"],
                    "verified_pct": grading["verified_pct"]},
        "disclaimer": ("Claims are independently recomputed from the intervention formula + GEE rainfall; the "
                       "grade (A–F) reflects deviation vs recompute, CAPPED by the formula's audited soundness. "
                       "Every drafted claim cites its source document; missing evidence is a gap, never fabricated."),
        "source": "PS5 Evidence & Disclosure Agent — formula verification + CDP Water Security",
    }
    if persist and site:
        try:
            import supa
            supa.save_evidence(site, result)
            result["persisted"] = True
        except Exception as e:
            result["persisted"] = False
            result["persist_error"] = str(e)[:160]
    return result


def demo() -> dict:
    out = run_pipeline(SAMPLE_DOCS, lat=13.0827, lng=80.2707)  # Chennai — GEE rainfall in play
    out["data_grade"] = "SYNTHETIC-DEMO"
    return out
