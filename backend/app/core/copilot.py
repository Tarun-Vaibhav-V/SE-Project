"""Stewardship Copilot orchestrator.

Wires the tools to Groq function-calling under a strict system prompt that
enforces the citation contract: every factual claim must be grounded in a tool
result, and Sourced vs Illustrative data must be distinguished.
"""
from __future__ import annotations
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.core import tools as T
from app.core import llm_groq

SYSTEM_PROMPT = """You are the Hydris Stewardship Copilot, a water-stewardship analyst for a \
company's water portfolio (data pack: PepsiCo FY2025, aligned to the Alliance for Water \
Stewardship (AWS) Standard and the Positive Water Impact (PWI) framework).

YOUR JOB: answer portfolio questions with ranked, explained, and CITED recommendations.

HARD RULES (citation contract):
1. Ground every fact in a tool result. Never invent numbers, sites, projects, or figures.
   If the data does not support an answer, say so plainly.
2. Prefer the STRUCTURED tools (rank_sites, rank_projects_by_impact, off_track_projects,
   get_site, get_project, sql_select) for anything numeric or analytic — they are exact.
   Use search_standard for AWS methodology / "what does the standard require" / source questions.
3. Every number or claim in your answer must show a citation inline as PLAIN TEXT
   in parentheses, e.g. "(Basin Risk, sheet 03; Illustrative)" or
   "(AWS Standard v3.0 Guidance, p.51)". NEVER wrap a citation in a Markdown link
   and NEVER invent a URL — cite only the sheet/page names returned by the tools.
   Do NOT use bracketed reference tokens like 【..†..】 or [n]; use plain parentheses only.
4. Distinguish data provenance: mark values as Sourced (real, publicly reported) vs
   Illustrative (modelled for this portfolio). Never present an Illustrative figure as a
   real PepsiCo-reported number. Surface confidence scores when available.
5. When ranking, show the criteria/weights used and give a one-line "why" per item.
6. Be concise and decision-useful: lead with the ranked recommendation, then the evidence.

Format answers in Markdown: a short direct answer, a ranked list with per-item reasons +
inline citations, then a brief "Sources" note if helpful."""


# --- Tool JSON schemas (OpenAI/Groq function-calling format) ----------
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "describe_portfolio",
        "description": "Portfolio overview: company facts and the catalogue of data tables/columns.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "rank_sites",
        "description": "Rank sites by a weighted blend of basin risk, water withdrawal and "
                       "strategic importance. Weights are user-adjustable and normalised to 1.",
        "parameters": {"type": "object", "properties": {
            "w_risk": {"type": "number", "description": "weight for basin risk (default 0.5)"},
            "w_water": {"type": "number", "description": "weight for water withdrawal (default 0.3)"},
            "w_importance": {"type": "number", "description": "weight for strategic importance (default 0.2)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "rank_projects_by_impact",
        "description": "Rank projects by impact (achievement ratio x confidence), returning raw "
                       "delivered figures + units. Answers 'which projects create the most impact'.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "off_track_projects",
        "description": "Projects where actual progress < planned progress, with delay days and the "
                       "intervention description. Answers 'which are off-track and why'.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "get_site",
        "description": "Full profile for one site (risk, water balance, quality, importance).",
        "parameters": {"type": "object", "properties": {
            "site": {"type": "string", "description": "site id (e.g. S03) or name (e.g. Vallejo)"},
        }, "required": ["site"]},
    }},
    {"type": "function", "function": {
        "name": "get_project",
        "description": "Full profile for one project (targets, performance, metadata, financials).",
        "parameters": {"type": "object", "properties": {
            "project": {"type": "string", "description": "project id (e.g. P04) or name (e.g. Cape Town)"},
        }, "required": ["project"]},
    }},
    {"type": "function", "function": {
        "name": "search_standard",
        "description": "Semantic search over the AWS Standard v3.0 PDFs and workbook narrative "
                       "(sources, supporting docs, confidence methodology). Use for methodology questions.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "description": "number of passages (default 5)"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "sql_select",
        "description": "Run a read-only SELECT against the portfolio DB for ad-hoc questions. "
                       "Get table/column names from describe_portfolio first.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "a single SELECT statement"},
        }, "required": ["query"]},
    }},
]

DISPATCH = {
    "describe_portfolio": T.describe_portfolio,
    "rank_sites": T.rank_sites,
    "rank_projects_by_impact": T.rank_projects_by_impact,
    "off_track_projects": T.off_track_projects,
    "get_site": T.get_site,
    "get_project": T.get_project,
    "search_standard": T.search_standard,
    "sql_select": T.sql_select,
}


def _collect_citations(trace: list[dict]) -> list[dict]:
    seen, out = set(), []
    for step in trace:
        res = step.get("result") or {}
        for c in (res.get("citations") or []):
            key = (c.get("source"), c.get("sheet") or c.get("locator"))
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


class Copilot:
    def __init__(self, model: str = None):
        self.model = model

    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += history or []
        messages.append({"role": "user", "content": question})
        result = llm_groq.run(messages, TOOL_SPECS, DISPATCH, model=self.model)
        answer = re.sub(r"【[^】]*】", "", result["answer"])   # strip stray gpt-oss ref tokens
        return {
            "answer": answer,
            "citations": _collect_citations(result["trace"]),
            "trace": result["trace"],
        }
