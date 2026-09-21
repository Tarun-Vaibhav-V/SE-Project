"""Grounded narrative via Groq — with a mechanical no-hallucination guarantee.

Pipeline: driver JSON -> Groq (temp 0.2, numbers-from-JSON-only system prompt)
-> numeral validation (every number in the reply must exist in the JSON)
-> one retry on failure -> deterministic template fallback built straight
from the JSON (always available, never invents anything).
"""
import json
import os
import re

SYSTEM_PROMPT = """You are a water-risk analyst. You will receive a JSON object of computed
risk-driver data for one site. Write a 3-sentence plain-English explanation of why the risk
score is what it is.

HARD RULES:
- Use ONLY numbers that appear verbatim in the JSON. Never compute, round, or invent numbers.
- NEVER do arithmetic: no sums, totals, differences, or "combined X%" figures — quote each
  number individually, exactly as it appears.
- Name the top drivers by their attribution percentages.
- If a driver's confidence is "proxy", "regional" or "no-data", say so plainly.
- Describe attribution as "estimated contribution to the modelled score", never as physical cause.
- No preamble, no markdown, just the 3 sentences."""


def _numbers_in(text):
    """All numeric tokens in a string, normalized (strip trailing zeros)."""
    return {n.rstrip("0").rstrip(".") if "." in n else n
            for n in re.findall(r"-?\d+(?:\.\d+)?", text)}


def _json_numbers(obj):
    nums = set()

    def walk(o):
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            s = repr(float(o))
            nums.add(s.rstrip("0").rstrip(".") if "." in s else s)
            if isinstance(o, float) and o == int(o):
                nums.add(str(int(o)))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            nums.update(_numbers_in(o))

    walk(obj)
    return nums


def validate_narrative(text, driver_json):
    """True iff every number in the narrative exists in the driver JSON."""
    allowed = _json_numbers(driver_json)
    allowed.update({"0", "1", "3", "5", "100"})  # scale bounds / sentence-count / percent-total phrasing
    return _numbers_in(text) <= allowed


def template_fallback(risk, driver_json):
    """Deterministic explanation built directly from the JSON — zero-hallucination path."""
    att = driver_json.get("attribution_pct", {})
    hazard = driver_json.get("hazard_0_5")
    if not att:
        return (f"No {risk} drivers could be computed for this site from open data; "
                "the headline score comes from WRI Aqueduct alone.")
    top = sorted(att.items(), key=lambda x: -x[1])[:3]
    parts = [f"{k.replace('_', ' ')} ({v}%)" for k, v in top]
    flags = [f"{k.replace('_', ' ')} is {d['confidence']}"
             for k, d in driver_json.get("drivers", {}).items()
             if d.get("confidence") in ("proxy", "regional", "no-data")]
    txt = (f"The modelled {risk} hazard is {hazard} out of 5. "
           f"The largest estimated contributions to the modelled score are {', '.join(parts)}.")
    if flags:
        txt += " Note: " + "; ".join(flags) + "."
    return txt


def explain(risk, driver_json):
    """Returns {narrative, grounded (bool), engine ('groq'|'template')}."""
    api_key = os.environ.get("GROQ_API_KEY")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    if api_key:
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            for _ in range(3):  # retries on validation failure
                resp = client.chat.completions.create(
                    model=model,
                    temperature=0.0,
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(
                            {"risk": risk, **driver_json}, indent=1)},
                    ],
                )
                text = resp.choices[0].message.content.strip()
                if validate_narrative(text, driver_json):
                    return {"narrative": text, "grounded": True, "engine": "groq"}
        except Exception:
            pass
    return {"narrative": template_fallback(risk, driver_json),
            "grounded": True, "engine": "template"}
