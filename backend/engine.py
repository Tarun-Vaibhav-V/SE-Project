"""Hydris engine — Aqueduct headline functions, ported 1:1 from hydris_aqueduct_engine.ipynb.

Every function here mirrors a notebook cell that passed its gate in Colab.
All Aqueduct -9999 no-data markers become None and stay None (excluded +
weights renormalized), never 0.
"""
import os
import ee

GROUPS = {
    "qan": ["bws", "bwd", "iav", "sev", "gtd", "drr", "rfr", "cfr"],
    "qal": ["ucw", "cep"],
    "rrr": ["udw", "usa", "rri"],
}
ALL_IND = [c for g in GROUPS.values() for c in g]
OVERALL = "w_awr_def_tot_score"
OVERALL_CAT = "w_awr_def_tot_cat"

_AQ = None
_AQ_FUT = None


def init_ee():
    """Service-account init (production) with user-credential fallback (local dev)."""
    global _AQ, _AQ_FUT
    project = os.environ["GEE_PROJECT"]
    key_file = os.environ.get("GEE_SA_KEY_FILE")
    if key_file:
        import json
        sa_email = json.load(open(key_file))["client_email"]
        creds = ee.ServiceAccountCredentials(sa_email, key_file)
        ee.Initialize(creds, project=project)
    else:
        ee.Initialize(project=project)
    _AQ = ee.FeatureCollection("WRI/Aqueduct_Water_Risk/V4/baseline_annual")
    _AQ_FUT = ee.FeatureCollection("WRI/Aqueduct_Water_Risk/V4/future_annual")


def AQ():
    if _AQ is None:
        init_ee()
    return _AQ


def AQ_FUT():
    if _AQ_FUT is None:
        init_ee()
    return _AQ_FUT


def clean(v):
    """-9999 = Aqueduct no-data -> None. (+9999 arid mask is a real score, untouched.)"""
    return None if v in (-9999, -9999.0, "-9999") else v


def get_site_profile(lat, lng):
    pt = ee.Geometry.Point([lng, lat])
    hit = AQ().filterBounds(pt)
    if hit.size().getInfo() == 0:
        return None
    d = hit.first().toDictionary().getInfo()
    # cat/label carry the same -9999 no-data marker as raw/score — clean ALL of
    # them so the honesty layer never leaks a -9999 into the profile (a cached
    # gtd.cat=-9999 was slipping through and would fail test_site_chennai live).
    prof = {i: {"raw": clean(d.get(f"{i}_raw")), "score": clean(d.get(f"{i}_score")),
                "cat": clean(d.get(f"{i}_cat")), "label": clean(d.get(f"{i}_label"))}
            for i in ALL_IND}
    prof["_meta"] = {"pfaf_id": d.get("pfaf_id"), "country": d.get("name_0"),
                     "province": d.get("name_1")}
    prof["overall_gee"] = clean(d.get(OVERALL))
    prof["overall_cat"] = clean(d.get(OVERALL_CAT))
    return prof


CATEGORIES = [(0, 1, "Low"), (1, 2, "Low-Medium"), (2, 3, "Medium-High"),
              (3, 4, "High"), (4, 5, "Extremely High")]


def classify(score):
    if score is None:
        return None
    for lo, hi, name in CATEGORIES:
        if lo <= score < hi:
            return name
    return "Extremely High"


def classify_risk_level(overall):
    return classify(overall)


def wmean(scores, weights):
    pairs = [(s, weights.get(k, 0)) for k, s in scores.items()
             if s is not None and weights.get(k, 0) > 0]
    if not pairs:
        return None
    return round(sum(s * w for s, w in pairs) / sum(w for _, w in pairs), 3)


def reweight(profile, ind_weights=None, group_weights=None):
    # Partial dicts are overrides: a missing indicator keeps its default weight 1,
    # it is NOT excluded (weight 0 must be explicit).
    ind_weights = {**{i: 1 for i in ALL_IND}, **(ind_weights or {})}
    group_weights = {**{"qan": 1, "qal": 1, "rrr": 1}, **(group_weights or {})}
    scores = {i: profile[i]["score"] for i in ALL_IND}
    groups = {g: wmean({m: scores[m] for m in members}, ind_weights)
              for g, members in GROUPS.items()}
    overall = wmean(groups, group_weights)
    return {"groups": groups, "overall": overall, "overall_cat": classify(overall)}


SCN = {"optimistic": "opt", "bau": "bau", "pessimistic": "pes"}
FUT = {"scarcity": "ws", "depletion": "wd", "interannual_var": "iv", "seasonal_var": "sv"}


def get_future(pfaf_id, year=50, scenario="bau"):
    fc = AQ_FUT().filter(ee.Filter.eq("pfaf_id", pfaf_id))
    keys = [f"{SCN[scenario]}{year}_{c}_x_s" for c in FUT.values()]
    # .first() hands back a server-side Element even when the collection is
    # empty, so a Python `is None` check never fires — the null only surfaces as
    # an EEException inside getInfo(). Guard server-side instead, in the same
    # round-trip, so a basin WRI does not project returns None (-> 404) rather
    # than a 500.
    d = ee.Dictionary(ee.Algorithms.If(fc.size().gt(0),
                                       fc.first().toDictionary(keys),
                                       ee.Dictionary({}))).getInfo()
    if not d:
        return None
    out = {name: clean(d.get(f"{SCN[scenario]}{year}_{c}_x_s")) for name, c in FUT.items()}
    out["_note"] = ("WRI projects only stress/depletion/variability; "
                    "flood, drought and groundwater remain at baseline by design")
    return out


def _wavg(pairs):
    avail = [(s, w) for s, w in pairs if s is not None]
    if not avail:
        return None
    return round(sum(s * w for s, w in avail) / sum(w for _, w in avail), 2)


def _mx(*vals):
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def derive_pwi_scores(p):
    """WRI 13 -> PWI dimensions (Availability/Quality/Accessibility) per the WSM spec.
    No-data excluded with weight renormalization, never coerced to 0."""
    def s(k):
        return p[k]["score"]

    scarcity = _wavg([(s("bws"), .36), (s("bwd"), .36), (s("iav"), .18), (s("sev"), .10)])
    availability = {"physical_scarcity": scarcity, "flood": _mx(s("rfr"), s("cfr")),
                    "drought": s("drr"), "groundwater": s("gtd")}
    quality = {"untreated_wastewater": s("ucw"), "coastal_eutrophication": s("cep"),
               "reg_reputational": s("rri")}
    accessibility = {"wash_gap": _wavg([(s("udw"), .5), (s("usa"), .5)])}
    return {
        "Availability": availability, "Quality": quality, "Accessibility": accessibility,
        "dims": {
            "Availability": _wavg([(v, 1) for v in availability.values()]),
            "Quality": _wavg([(v, 1) for v in quality.values()]),
            "Accessibility": _wavg([(v, 1) for v in accessibility.values()]),
        },
        "derived": {"flood": _mx(s("rfr"), s("cfr")),
                    "shortage": _wavg([(s("bws"), .5), (s("drr"), .5)])},
        "_notes": [
            "ety (country regulatory) not in GEE Aqueduct table - rri used alone; ety = roadmap",
            "no-data indicators excluded with weight renormalization, never treated as 0",
        ],
    }


def analyze_portfolio(sites):
    rows = []
    for s in sites:
        p = get_site_profile(s["lat"], s["lng"])
        r = {"site": s.get("name"), "id": s.get("id"),
             "basin": p["_meta"]["pfaf_id"] if p else None}
        if p:
            r.update({"scarcity": p["bws"]["score"], "flood": p["rfr"]["score"],
                      "drought": p["drr"]["score"], "groundwater": p["gtd"]["score"],
                      "overall": p["overall_gee"], "level": classify(p["overall_gee"])})
        rows.append(r)
    return rows


def search_location(query):
    from geopy.geocoders import Nominatim
    loc = Nominatim(user_agent="hydris-backend").geocode(query)
    if not loc:
        return None
    prof = get_site_profile(loc.latitude, loc.longitude)
    return {"query": query, "lat": loc.latitude, "lng": loc.longitude,
            "address": loc.address,
            "basin": prof["_meta"] if prof else None,
            "overall": prof["overall_gee"] if prof else None}
