"""Labeled worked-example inputs for the PWI engine (PS3).

⚠️ EVERY NUMBER HERE IS ASSUMED / SYNTHETIC — it is NOT real factory data.
It exists only to exercise the engine end-to-end on a known site (Chennai S1)
until the factory owner supplies real Section A + 52-question inputs. The
`data_grade: "ASSUMED-DEMO"` tag propagates into every output so no result can
be mistaken for a verified measurement.
"""

# 52 self-assessment scores (0-3). Pattern: site (P1) fairly mature, sub-basin
# (P2) partial, basin (P3) early — the realistic shape for a single factory.
_SCORES = {
    # P1 Availability Q1-8
    1: 3, 2: 3, 3: 2, 4: 2, 5: 1, 6: 2, 7: 2, 8: 1,
    # P1 Quality Q9-16
    9: 3, 10: 2, 11: 2, 12: 2, 13: 2, 14: 2, 15: 1, 16: 1,
    # P1 Access Q17-22
    17: 3, 18: 2, 19: 2, 20: 2, 21: 2, 22: 2,
    # P2 Availability Q23-28  (Q25 implemented but Q26 unverified -> triggers XV-06)
    23: 2, 24: 2, 25: 2, 26: 0, 27: 1, 28: 1,
    # P2 Quality Q29-33
    29: 1, 30: 1, 31: 1, 32: 0, 33: 0,
    # P2 Access Q34-38
    34: 1, 35: 2, 36: 1, 37: 1, 38: 1,
    # P3 Availability Q39-43
    39: 1, 40: 1, 41: 0, 42: 0, 43: 0,
    # P3 Quality Q44-48
    44: 0, 45: 1, 46: 0, 47: 0, 48: 0,
    # P3 Access Q49-52
    49: 1, 50: 1, 51: 0, 52: 0,
}

# evidence rule for the demo: score>=2 -> Yes, ==1 -> Partial, 0 -> No
def _evidence(score):
    return "Yes" if score >= 2 else "Partial" if score == 1 else "No"


def chennai_demo() -> dict:
    return {
        "id": "S1",
        "name": "Chennai plant (IN)",
        "company": "Demo Apparel Co. (ASSUMED)",
        "lat": 13.0827, "lng": 80.2707, "pfaf_id": 453750,
        "industry": "Textile",
        "basin_name": "Chennai basin (pfaf 453750)",
        "data_grade": "ASSUMED-DEMO",   # <-- propagates into outputs
        "self_assessment": {str(q): {"score": s, "evidence": _evidence(s)} for q, s in _SCORES.items()},
        "operational": {
            "annual_withdrawal_m3": 520000,
            "water_recycled_m3": 60000,
            "water_reused_m3": 25000,
            # per-intervention benefit (m³/yr) — WQBA-provided per the brief (here ASSUMED)
            "intervention_benefits_m3": [60000, 18000, 45000],
            "wastewater_generated_m3": 300000,
            "wastewater_treated_m3": 285000,
            "employees": 1800,
            "toilets": 90,        # 1800/90 = 20 ≤ 22 ✓
            "washbasins": 320,    # 1800/320 = 5.6 ≤ 6 ✓
            "safe_drinking_water": True,
        },
    }
