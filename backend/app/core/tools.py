"""Copilot tools = the retrieval layer.

Two families:
  * STRUCTURED (SQLite)  -> deterministic rankings/filters/joins with exact
    numbers.  Every result carries citations (source sheet + Data Status).
  * SEMANTIC (FAISS)     -> search_standard() over the AWS PDFs + narrative.

The contract: a tool never returns a bare number; it returns data + the
citation(s) that back it, so the copilot can ground every claim.
"""
from __future__ import annotations
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.core import db
from app.core.vectorstore import VectorStore
from app.config import TOP_K

_SITE_CODE = re.compile(r"S\d{2}")
_PROJ_CODE = re.compile(r"P\d{2}")

_vs = None


def _vecstore() -> VectorStore:
    global _vs
    if _vs is None:
        _vs = VectorStore()
    return _vs


def _cite(table: str, data_status=None, detail=None) -> dict:
    s = db.sheet_for(table)
    return {
        "source": "Portfolio Workbook",
        "sheet": s["sheet"] if s else table,
        "data_status": data_status,
        "detail": detail,
    }


def _code(val, pat) -> str | None:
    if val is None:
        return None
    m = pat.search(str(val))
    return m.group() if m else None


# ----------------------------------------------------------------------
# Overview
# ----------------------------------------------------------------------
def describe_portfolio() -> dict:
    """High-level portfolio overview: company facts, table catalogue."""
    company = {r["Field"]: {"value": r["Value"], "status": r.get("Data Status")}
               for r in db.records("company_info") if r.get("Field")}
    catalogue = [{"sheet": s["sheet"], "table": s["table"],
                  "columns": s["columns"], "rows": s["n_rows"]}
                 for s in db.manifest()["sheets"] if s["table"]]
    return {
        "company": company,
        "tables": catalogue,
        "citations": [_cite("company_info", "Mixed")],
        "note": "Use table names with sql_select() for ad-hoc questions.",
    }


# ----------------------------------------------------------------------
# Site / project profiles
# ----------------------------------------------------------------------
def _match_site(query: str) -> str | None:
    q = query.strip().lower()
    code = _code(query.upper(), _SITE_CODE)
    for r in db.records("site_portfolio"):
        sid = (r.get("Site ID") or "").strip()
        name = (r.get("Site Name") or "").lower()
        if code and sid.upper() == code:
            return sid
        if q and (q in name or q in sid.lower()):
            return sid
    return None


def get_site(site: str) -> dict:
    """Full profile for one site (portfolio, basin risk, water balance,
    water quality, importance) joined by site code."""
    sid = _match_site(site)
    if not sid:
        return {"error": f"No site matched '{site}'.",
                "available": [r["Site ID"] for r in db.records("site_portfolio")
                              if _code(r.get("Site ID"), _SITE_CODE)]}
    out, cites = {}, []
    for table in ["site_portfolio", "basin_risk", "water_balance",
                  "water_quality", "site_importance"]:
        for r in db.records(table):
            key = r.get("Site ID") or r.get("Site") or ""
            if _code(key, _SITE_CODE) == sid:
                out[table] = r
                cites.append(_cite(table, r.get("Data Status")))
                break
    return {"site_id": sid, "profile": out, "citations": cites}


def get_project(project: str) -> dict:
    """Full profile for one project across projects, targets, performance,
    intervention metadata and financials."""
    code = _code(project.upper(), _PROJ_CODE)
    q = project.strip().lower()
    out, cites, matched = {}, [], None
    for table in ["projects", "pwi_targets", "project_performance",
                  "intervention_metadata", "financial_info"]:
        for r in db.records(table):
            key = r.get("Project ID") or r.get("Project") or ""
            kc = _code(key, _PROJ_CODE)
            if (code and kc == code) or (not code and q and q in str(key).lower()):
                out[table] = r
                cites.append(_cite(table, r.get("Data Status")))
                matched = matched or kc or key
                break
    if not out:
        return {"error": f"No project matched '{project}'."}
    return {"project": matched, "detail": out, "citations": cites}


# ----------------------------------------------------------------------
# Q1: Which sites should I prioritise?
# ----------------------------------------------------------------------
def rank_sites(w_risk: float = 0.5, w_water: float = 0.3,
               w_importance: float = 0.2) -> dict:
    """Rank sites by a transparent weighted blend of basin risk (sheet 03),
    water withdrawal (sheet 04) and strategic importance (sheet 17).
    Weights are normalised to sum to 1; all component values are returned
    so the ranking is fully explainable."""
    tot = (w_risk + w_water + w_importance) or 1.0
    w_risk, w_water, w_importance = w_risk / tot, w_water / tot, w_importance / tot

    risk = {_code(r.get("Site"), _SITE_CODE): db.to_num(r.get("Overall Risk Score (0-100)"))
            for r in db.records("basin_risk")}
    water = {_code(r.get("Site"), _SITE_CODE): db.to_num(r.get("Withdrawal (m3/yr)"))
             for r in db.records("water_balance")}
    imp = {_code(r.get("Site"), _SITE_CODE): db.to_num(r.get("Weight (formula, normalised)"))
           for r in db.records("site_importance")}
    max_water = max([v for v in water.values() if v] or [1])
    max_imp = max([v for v in imp.values() if v] or [1])

    rows = []
    for r in db.records("site_portfolio"):
        sid = _code(r.get("Site ID"), _SITE_CODE)
        if not sid:
            continue
        rk = (risk.get(sid) or 0) / 100
        wt = (water.get(sid) or 0) / max_water
        im = (imp.get(sid) or 0) / max_imp
        score = w_risk * rk + w_water * wt + w_importance * im
        rows.append({
            "site_id": sid, "name": r.get("Site Name"), "country": r.get("Country"),
            "basin": r.get("Basin"),
            "priority_score": round(score * 100, 1),
            "components": {
                "basin_risk_0_100": risk.get(sid),
                "withdrawal_m3_yr": water.get(sid),
                "importance_weight": imp.get(sid),
            },
        })
    rows.sort(key=lambda x: x["priority_score"], reverse=True)
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    return {
        "weights_used": {"risk": round(w_risk, 3), "water_use": round(w_water, 3),
                         "importance": round(w_importance, 3)},
        "ranking": rows,
        "citations": [_cite("basin_risk", "Illustrative"),
                      _cite("water_balance", "Illustrative"),
                      _cite("site_importance", "Illustrative")],
        "note": "Basin risk, per-site withdrawal and importance weights are "
                "Illustrative modelled values (see README). Weights are user-adjustable.",
    }


# ----------------------------------------------------------------------
# Q2: Which projects create the most impact?
# ----------------------------------------------------------------------
def rank_projects_by_impact() -> dict:
    """Rank projects by a defensible impact proxy = achievement ratio
    (min(Delivered/Target,1)) x confidence, while returning the raw delivered
    figures + units (which differ across projects) so magnitude is visible."""
    conf = {_code(r.get("Project"), _PROJ_CODE): db.to_num(r.get("Confidence Score (formula)"))
            for r in db.records("intervention_metadata")}
    comp = {_code(r.get("Project"), _PROJ_CODE): db.to_num(r.get("Completion % (formula)"))
            for r in db.records("project_performance")}

    rows = []
    for r in db.records("pwi_targets"):
        proj = r.get("Project") or ""
        pc = _code(proj, _PROJ_CODE)
        target, delivered = db.to_num(r.get("Target")), db.to_num(r.get("Delivered"))
        achievement = min(delivered / target, 1.0) if target and delivered else None
        c = conf.get(pc)
        impact = round(achievement * c, 3) if achievement is not None and c else achievement
        rows.append({
            "project": proj,
            "delivered": delivered, "target": target, "unit": r.get("Unit"),
            "achievement_ratio": round(achievement, 3) if achievement is not None else None,
            "confidence": c,
            "completion_pct": comp.get(pc),
            "impact_proxy": impact,
            "data_status": r.get("Data Status (Target / Delivered)"),
        })
    rows.sort(key=lambda x: (x["impact_proxy"] is not None, x["impact_proxy"] or 0),
              reverse=True)
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    return {
        "ranking": rows,
        "citations": [_cite("pwi_targets"), _cite("intervention_metadata"),
                      _cite("project_performance")],
        "note": "Units differ across projects (litres / people / m3 / sites); the "
                "impact_proxy normalises via achievement x confidence. Cite raw "
                "delivered + unit alongside any ranking.",
    }


# ----------------------------------------------------------------------
# Q3: Which sites/projects are off-track and why?
# ----------------------------------------------------------------------
def off_track_projects() -> dict:
    """Projects where Actual Progress % < Planned Progress % (sheet 08),
    with delay days and the intervention description for the 'why'."""
    desc = {}
    for r in db.records("projects"):
        pc = _code(r.get("Project ID"), _PROJ_CODE)
        if pc:
            desc[pc] = {"site": r.get("Site / Scope"), "intervention": r.get("Intervention"),
                        "status": r.get("Status Date / Status")}

    off, on = [], []
    for r in db.records("project_performance"):
        proj = r.get("Project") or ""
        pc = _code(proj, _PROJ_CODE)
        planned = db.to_num(r.get("Planned Progress %"))
        actual = db.to_num(r.get("Actual Progress %"))
        if planned is None or actual is None:
            continue
        rec = {
            "project": proj,
            "planned_pct": round(planned * 100, 1),
            "actual_pct": round(actual * 100, 1),
            "gap_pts": round((actual - planned) * 100, 1),
            "delay_days": db.to_num(r.get("Delay (days, formula)")),
            "data_status": r.get("Data Status"),
            "why": desc.get(pc, {}),
        }
        (off if actual < planned else on).append(rec)
    off.sort(key=lambda x: x["gap_pts"])
    return {
        "off_track": off,
        "on_track_count": len(on),
        "citations": [_cite("project_performance"), _cite("projects")],
        "note": "Off-track = Actual Progress < Planned Progress (sheet 08).",
    }


# ----------------------------------------------------------------------
# Semantic + ad-hoc
# ----------------------------------------------------------------------
def search_standard(query: str, k: int = TOP_K) -> dict:
    """Semantic search over the AWS Standard v3.0 PDFs and workbook narrative
    (README sources, supporting docs, confidence methodology)."""
    hits = _vecstore().search(query, k=k)
    return {
        "query": query,
        "results": [{"text": h["text"], "source": h["source"],
                     "locator": h["locator"], "score": h["score"]} for h in hits],
        "citations": [{"source": h["source"], "locator": h["locator"]} for h in hits],
    }


def sql_select(query: str) -> dict:
    """Run a read-only SELECT against the portfolio DB for ad-hoc questions.
    Table + column names come from describe_portfolio()."""
    try:
        rows = db.run_select(query)
    except Exception as e:
        return {"error": str(e), "hint": "Only single read-only SELECT statements are allowed."}
    return {"rows": rows, "row_count": len(rows),
            "note": "Cite the source sheet(s) of any table you SELECT from."}
