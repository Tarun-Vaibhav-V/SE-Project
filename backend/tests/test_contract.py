"""Gate 2 contract tests. Offline parts always run; live parts need .env creds
and are skipped otherwise (pytest -m live to force).

Run:  cd backend && pytest -q
"""
import json
import os
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from explain import validate_narrative, template_fallback, _numbers_in

DRIVER_FIXTURE = {
    "hazard_0_5": 3.4,
    "attribution_pct": {"rainfall_SPI": 42.0, "soil_moisture": 31.5, "vegetation_NDVI": 26.5},
    "drivers": {
        "rainfall_SPI": {"severity": 0.81, "confidence": "computed"},
        "soil_moisture": {"severity": 0.6, "confidence": "computed"},
        "vegetation_NDVI": {"severity": 0.5, "confidence": "regional"},
    },
}


class TestNoHallucination:
    def test_valid_narrative_passes(self):
        txt = ("The modelled drought hazard is 3.4 out of 5. Rainfall SPI contributes an "
               "estimated 42% to the modelled score. Vegetation NDVI (26.5%) is a regional signal.")
        assert validate_narrative(txt, DRIVER_FIXTURE)

    def test_invented_number_fails(self):
        txt = "The hazard is 3.4 driven by a 57% rainfall deficit."
        assert not validate_narrative(txt, DRIVER_FIXTURE)

    def test_template_fallback_is_always_grounded(self):
        txt = template_fallback("drought", DRIVER_FIXTURE)
        assert validate_narrative(txt, DRIVER_FIXTURE)
        assert "estimated contribution" in txt

    def test_template_handles_empty(self):
        txt = template_fallback("flood", {"attribution_pct": {}, "hazard_0_5": None})
        assert "Aqueduct" in txt


class TestEngineOffline:
    def test_classify_boundaries(self):
        from engine import classify
        assert classify(None) is None
        assert classify(0.5) == "Low"
        assert classify(4.0) == "Extremely High"
        assert classify(5.0) == "Extremely High"

    def test_pwi_never_coerces_none_to_zero(self):
        from engine import derive_pwi_scores, ALL_IND
        prof = {i: {"score": None} for i in ALL_IND}
        prof["bws"] = {"score": 4.0}
        pwi = derive_pwi_scores(prof)
        # gtd is None -> groundwater must be None, not 0
        assert pwi["Availability"]["groundwater"] is None
        # scarcity renormalizes over bws alone -> 4.0
        assert pwi["Availability"]["physical_scarcity"] == 4.0
        assert "-9999" not in json.dumps(pwi)

    def test_wavg_renormalizes(self):
        from engine import _wavg
        assert _wavg([(4.0, .36), (None, .36), (None, .18), (None, .10)]) == 4.0
        assert _wavg([(None, 1)]) is None


class TestPWIEngine:
    """PS3 PWI Quantification Engine — deterministic methodology checks (offline)."""

    def _answers(self, score, evidence):
        import pwi
        return {str(q): {"score": score, "evidence": evidence} for q in pwi.QUESTION_CELL}

    def test_all_max_is_self_certified(self):
        import pwi
        r = pwi.score_self_assessment(self._answers(3, "Yes"))
        # every cell 100%, pillars 100, site 100, no XV, confidence 100
        assert r["site_pwi"]["value"] == 100.0
        for p in pwi.PILLARS:
            assert r["pillars"][p]["value"] == 100.0
        assert r["confidence"]["adjusted_pct"] == 100.0
        assert r["certification"]["result"].startswith("SELF-CERTIFIED")

    def test_all_zero_is_not_achieved(self):
        import pwi
        r = pwi.score_self_assessment(self._answers(0, "No"))
        assert r["site_pwi"]["value"] == 0.0
        assert r["confidence"]["adjusted_pct"] == 50.0  # evidence 'No' = 50, no XV fires at 0
        assert "NOT ACHIEVED" in r["certification"]["result"]

    def test_pillar_weighting_formula(self):
        # Availability×0.4 + Quality×0.3 + Access×0.3 exactly
        import pwi
        a = self._answers(0, "No")
        for q, (p, d) in pwi.QUESTION_CELL.items():
            if p == "P1" and d == "Availability":
                a[str(q)] = {"score": 3, "evidence": "Yes"}   # P1 Avail -> 100%
        r = pwi.score_self_assessment(a)
        assert r["pillars"]["P1"]["value"] == 40.0  # 100*0.4 + 0 + 0

    def test_xv_penalty_lowers_confidence(self):
        import pwi
        a = self._answers(3, "Yes")            # raw confidence 100
        a["25"] = {"score": 2, "evidence": "Yes"}
        a["26"] = {"score": 0, "evidence": "No"}   # XV-06: NBS implemented but unverified
        r = pwi.score_self_assessment(a)
        fired = [x["id"] for x in r["confidence"]["rules"] if x["result"] == "FAIL"]
        assert "XV-06" in fired
        assert r["confidence"]["adjusted_pct"] < r["confidence"]["raw_pct"]

    def test_portfolio_is_mean_of_sites(self):
        import pwi
        s1 = {"id": "A", "self_assessment": self._answers(3, "Yes")}   # 100
        s2 = {"id": "B", "self_assessment": self._answers(0, "No")}    # 0
        r = pwi.portfolio_pwi([s1, s2])
        assert r["portfolio_pwi"]["value"] == 50.0
        assert r["ranked_sites"][0]["id"] == "A"  # ranked desc

    def test_demo_is_labeled_assumed(self):
        import pwi
        from pwi_demo import chennai_demo
        r = pwi.site_pwi(chennai_demo())
        assert r["data_grade"] == "ASSUMED-DEMO"
        assert r["site_pwi"]["value"] is not None


class TestEvidenceAgent:
    """PS5 Evidence & Disclosure Agent — deterministic pipeline checks (offline, no LLM)."""

    def test_keyword_classify_permit(self):
        import evidence
        m = evidence._kw_classify("CONSENT TO OPERATE — Pollution Control Board. Valid until 31-Dec-2024.")
        assert m["type"] == "discharge_permit"
        assert m["validity_end"] == "2024-12-31"  # date normalised

    def test_map_to_cdp(self):
        import evidence
        arts = [{"name": "wb.xlsx", "type": "meter_water_balance"},
                {"name": "lab.pdf", "type": "effluent_lab_report", "accredited": True}]
        cov = evidence.map_to_cdp(arts)
        assert "wb.xlsx" in cov["W1.2"]          # meter -> water accounting
        assert "lab.pdf" in cov["W5.1a"]         # lab -> discharge quality
        assert "lab.pdf" in cov["W9.1"]          # accredited -> verification

    def test_verification_needs_accreditation(self):
        import evidence
        cov = evidence.map_to_cdp([{"name": "lab.pdf", "type": "effluent_lab_report", "accredited": False}])
        assert cov["W9.1"] == []                 # non-accredited lab does NOT satisfy W9.1

    def test_gap_detect_flags_expired_permit(self):
        import evidence
        arts = [{"name": "p.pdf", "type": "discharge_permit", "type_label": "Discharge Permit",
                 "validity_end": "2000-01-01", "accredited": False}]
        gaps = evidence.detect_gaps(arts, evidence.map_to_cdp(arts))
        assert any(g["kind"] == "EXPIRED" for g in gaps)

    def test_template_draft_only_cites_provided_docs(self):
        import evidence
        arts = [{"name": "wb.xlsx", "type": "meter_water_balance", "type_label": "Meter / Water-Balance Record",
                 "parameters": {}, "volumes_m3_yr": {"withdrawal": 520000}}]
        cov = evidence.map_to_cdp(arts)
        draft = evidence._template_draft(cov, arts)
        assert draft["engine"] == "template"
        for r in draft["responses"]:
            for c in r["citations"]:
                assert c == "wb.xlsx"            # never cites a document not supplied


class TestFormulaVerification:
    """PS5 formula recompute + A–F grading (offline; rainfall supplied, no GEE call)."""

    def test_rwh_recompute_and_grade(self):
        import formulas
        # 5000 m² × 1.0 m × 0.8 = 4000; claim 4000 -> 0% -> verified, grade A (sound)
        c = {"intervention": "rainwater_harvesting", "claimed_value": 4000,
             "params": {"catchment_area_m2": 5000, "runoff_coeff": 0.8}}
        r = formulas.verify_claim(c, rain_m=1.0)
        assert r["recomputed_value"] == 4000.0
        assert r["deviation_pct"] == 0.0
        assert r["verified"] is True and r["grade"] == "A"

    def test_overstated_claim_flagged_F(self):
        import formulas
        # recompute 10000×1.0×0.3=3000; claim 30000 -> 900% -> flagged F
        c = {"intervention": "groundwater_recharge", "claimed_value": 30000,
             "params": {"area_m2": 10000, "recharge_coeff": 0.3}}
        r = formulas.verify_claim(c, rain_m=1.0)
        assert r["verified"] is False and r["grade"] == "F"
        assert r["direction"] == "over-stated"

    def test_weak_formula_capped_at_C(self):
        import formulas
        # exact match (0% deviation) but weak formula -> grade capped at C
        c = {"intervention": "wetland_restoration", "claimed_value": 45000,
             "params": {"wetland_area_ha": 12, "recharge_rate": 3750}}
        r = formulas.verify_claim(c)
        assert r["status"] == "not_numerically_verifiable"
        assert r["grade"] == "C"                      # never better than C

    def test_sound_formula_can_reach_A_but_calibration_cap_B(self):
        import formulas
        # a perfect match on a needs_calibration formula still caps at B
        c = {"intervention": "groundwater_recharge", "claimed_value": 3000,
             "params": {"area_m2": 10000, "recharge_coeff": 0.3}}
        r = formulas.verify_claim(c, rain_m=1.0)
        assert r["deviation_pct"] == 0.0 and r["grade"] == "B"   # capped by soundness

    def test_overall_grade_rollup(self):
        import formulas
        claims = [{"grade": "A", "verified": True, "recomputed_value": 1000},
                  {"grade": "F", "verified": False, "recomputed_value": 500}]
        roll = formulas.overall_grade(claims, coverage_pct=100)
        assert roll["verified_pct"] == 50.0
        assert roll["verified_benefit_m3_yr"] == 1000.0   # only verified benefits count
        assert roll["cdp_grade"] in ("C", "B")


LIVE = os.environ.get("SUPABASE_URL") and os.environ.get("GEE_PROJECT")


@pytest.mark.skipif(not LIVE, reason="needs .env with GEE + Supabase creds")
class TestLiveContract:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app) as c:
            yield c

    def test_health(self, client):
        assert client.get("/health").json()["ok"]

    def test_site_chennai(self, client):
        r = client.get("/site", params={"lat": 13.0827, "lng": 80.2707})
        assert r.status_code == 200
        body = r.json()
        assert body["profile"]["_meta"]["pfaf_id"]
        assert "-9999" not in json.dumps(body)
        assert set(body["pwi"]["dims"]) == {"Availability", "Quality", "Accessibility"}

    def test_future_cached_fast(self, client):
        import time
        pfaf = client.get("/site", params={"lat": 13.0827, "lng": 80.2707}).json()["profile"]["_meta"]["pfaf_id"]
        client.get("/future", params={"pfaf_id": pfaf})          # warm
        t0 = time.time()
        r = client.get("/future", params={"pfaf_id": pfaf})
        assert r.status_code == 200
        assert time.time() - t0 < 0.5, "second call must be served from Supabase cache"

    def test_explain_grounded(self, client):
        r = client.post("/explain", json={"risk": "drought", "drivers": DRIVER_FIXTURE})
        body = r.json()
        assert body["grounded"] is True
        assert not (_numbers_in(body["narrative"]) -
                    _numbers_in(json.dumps(DRIVER_FIXTURE)) - {"0", "1", "3", "5", "100"})
