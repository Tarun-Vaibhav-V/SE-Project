"""Hydris GEE-compute service (Phase 2).

Thin FastAPI worker: Supabase holds all state; this service computes on cache
miss (GEE) and upserts results back. If GEE is down, cached demo sites keep
working — the frontend reads Supabase directly and only calls here on misses.
"""
import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import engine
import intervention
import supa
from auth import optional_user, profile_for, require_user
from drivers import ENGINES
from explain import explain as groq_explain

import sys
try:
    from app.core.copilot import Copilot
    copilot_instance = Copilot()
    _copilot_ok = True
except Exception as e:
    print(f"Copilot init failed: {e}")
    _copilot_ok = False

app = FastAPI(title="Hydris GEE compute", version="0.1")
# Locked to local dev origins by default; set ALLOWED_ORIGINS to a comma-separated
# list (e.g. the Vercel URL) when deploying. Avoid "*" in production — the API
# carries bearer tokens, so a wildcard would let any site drive it on a user's behalf.
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins,
                   allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"])

_gee_ok = False


def _check_coords(lat: float, lng: float):
    """Reject out-of-range / non-finite coordinates before any GEE call."""
    import math
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise HTTPException(422, "lat/lng must be finite numbers")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(422, "lat must be in -90..90 and lng in -180..180")


FUTURE_YEARS = (30, 50, 80)  # the only horizons in WRI Aqueduct's future table


def _cache_read(fn, *args):
    """Cache lookups are an optimization, never a dependency. If Supabase is
    unreachable we fall through to live compute instead of failing the request."""
    try:
        return fn(*args)
    except Exception as e:
        print(f"cache read failed ({fn.__name__}): {e}")
        return None


def _cache_write(fn, *args, **kwargs):
    """Cache writes are best-effort. A cache outage must never discard a
    computation that already succeeded — the result still goes to the caller.
    Endpoints whose *purpose* is persistence (POST /sites) do not use this."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        print(f"cache write failed ({fn.__name__}): {e}")


@app.on_event("startup")
def startup():
    global _gee_ok
    try:
        engine.init_ee()
        _gee_ok = True
    except Exception as e:  # degrade to Supabase-cache-only mode
        print(f"GEE init failed ({e}) - serving from Supabase cache only")


@app.get("/health")
def health():
    return {"ok": True, "gee": _gee_ok}


@app.get("/site")
def site(lat: float, lng: float, site_id: str | None = None):
    _check_coords(lat, lng)
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable - use cached sites from Supabase")
    prof = engine.get_site_profile(lat, lng)
    if prof is None:
        raise HTTPException(404, "no Aqueduct basin at this location")
    pwi = engine.derive_pwi_scores(prof)
    out = {"profile": prof, "pwi": pwi,
           "level": engine.classify_risk_level(prof["overall_gee"])}
    _cache_write(supa.upsert_risk_cache, prof["_meta"]["pfaf_id"], profile=prof, pwi=pwi)
    return out


class ReweightBody(BaseModel):
    lat: float
    lng: float
    ind_weights: dict | None = None
    group_weights: dict | None = None


@app.post("/reweight")
def reweight(body: ReweightBody):
    _check_coords(body.lat, body.lng)
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable")
    prof = engine.get_site_profile(body.lat, body.lng)
    if prof is None:
        raise HTTPException(404, "no basin")
    return engine.reweight(prof, body.ind_weights, body.group_weights)


@app.get("/future")
def future(pfaf_id: int, year: int = 50,
           scenario: Literal["optimistic", "bau", "pessimistic"] = "bau"):
    # Literal[int] would reject the query string "50" (pydantic v2 does not coerce
    # str -> int literals), so the horizon is validated explicitly instead.
    if year not in FUTURE_YEARS:
        raise HTTPException(422, f"year must be one of {list(FUTURE_YEARS)} "
                                 "(the horizons WRI Aqueduct projects)")
    cached = _cache_read(supa.get_risk_cache, pfaf_id)
    key = f"{scenario}{year}"
    if cached and cached.get("future") and key in cached["future"]:
        return cached["future"][key]
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable and no cached projection")
    f = engine.get_future(pfaf_id, year, scenario)
    if f is None:
        raise HTTPException(404, "basin not in future table")
    _cache_write(supa.upsert_risk_cache, pfaf_id, future={key: f})
    return f


class PortfolioBody(BaseModel):
    sites: list[dict]


@app.post("/portfolio")
def portfolio(body: PortfolioBody):
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable")
    return engine.analyze_portfolio(body.sites)


@app.get("/search")
def search(q: str):
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable")
    r = engine.search_location(q)
    if r is None:
        raise HTTPException(404, "location not found")
    return r


@app.get("/drivers")
def drivers(risk: Literal["drought", "groundwater", "flood"],
            lat: float = Query(...), lng: float = Query(...), site_id: str | None = None):
    _check_coords(lat, lng)  # a missing lat/lng used to default to (0,0) — open ocean
    if site_id:
        cached = _cache_read(supa.get_driver_cache, site_id, risk)
        if cached:
            return cached
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable and no cached drivers for this site")
    res = ENGINES[risk](lat, lng)
    if res is None:
        raise HTTPException(404, "no basin")
    if site_id:
        _cache_write(supa.upsert_driver_cache, site_id, risk, res)
    return res


# ---------- PS-X: Intervention Intelligence Engine (HIIE) ----------

def _baseline(site_id: str | None, lat: float, lng: float) -> dict:
    """Assemble {risk: driver-engine JSON} for a site. Cache first, then live GEE.

    A risk that resolves from neither is simply absent — the engine excludes it
    and renormalises, exactly as the driver composite does for a missing driver.
    We never substitute a zero.
    """
    out = {}
    for risk in intervention.RISKS:
        blk = _cache_read(supa.get_driver_cache, site_id, risk) if site_id else None
        if not blk and _gee_ok:
            try:
                blk = ENGINES[risk](lat, lng)
                if blk and site_id:
                    # _cache_write, not a bare call: a cache outage raised here
                    # would hit the except below and null out the drivers GEE
                    # just computed, failing the whole request with a 503.
                    _cache_write(supa.upsert_driver_cache, site_id, risk, blk)
            except Exception as e:
                print(f"/intervention baseline {risk} failed: {e}")
                blk = None
        if blk and blk.get("drivers"):
            out[risk] = blk
    if not out:
        raise HTTPException(503, "no driver data for this site (cache empty and GEE unavailable)")
    return out


class InterventionBody(BaseModel):
    lat: float
    lng: float
    site_id: str | None = None
    portfolio: dict[str, float] | None = None
    site_params: dict | None = None
    goal: str = "max_risk_reduction"
    intensity: float = 1.0
    budget_lakh_inr: float | None = None
    target_hazard_0_5: float | None = None
    max_acceptable_0_5: float = 3.0


@app.get("/intervention/catalog")
def intervention_catalog():
    """The modelled intervention catalogue — effects, costs, durations, formulas."""
    return intervention.catalog()


@app.post("/intervention/simulate")
def intervention_simulate(body: InterventionBody):
    """Digital twin: apply a portfolio at chosen intensities, return the
    counterfactual risk state recomputed by drivers.composite()."""
    _check_coords(body.lat, body.lng)
    base = _baseline(body.site_id, body.lat, body.lng)
    sim = intervention.simulate(base, body.portfolio or {})
    site = body.site_params or {}
    sim["water_benefit"] = {
        iid: intervention.water_benefit(iid, inten, site)
        for iid, inten in (body.portfolio or {}).items() if inten
    }
    total = [w["m3_per_year"] for w in sim["water_benefit"].values() if w.get("m3_per_year")]
    sim["water_total_m3_per_year"] = round(sum(total), 1) if total else None
    return sim


@app.post("/intervention/optimize")
def intervention_optimize(body: InterventionBody):
    """Goal-based portfolio search: max_risk_reduction | best_roi | risk_budget | max_water."""
    _check_coords(body.lat, body.lng)
    base = _baseline(body.site_id, body.lat, body.lng)
    return intervention.optimize(base, site=body.site_params or {}, goal=body.goal,
                                 intensity=body.intensity,
                                 budget_lakh_inr=body.budget_lakh_inr,
                                 target_hazard_0_5=body.target_hazard_0_5)


@app.post("/intervention/budget")
def intervention_budget(body: InterventionBody):
    """Risk budget: how far over the acceptable threshold, and the cheapest way back under."""
    _check_coords(body.lat, body.lng)
    base = _baseline(body.site_id, body.lat, body.lng)
    return intervention.risk_budget(base, body.max_acceptable_0_5,
                                    site=body.site_params or {}, intensity=body.intensity)


@app.get("/intervention/evidence")
def intervention_evidence(lat: float = Query(...), lng: float = Query(...),
                          intervention_id: str = Query(...), intensity: float = 1.0,
                          site_id: str | None = None):
    """Evidence graph: recommendation -> driver -> dataset, every edge traceable."""
    _check_coords(lat, lng)
    base = _baseline(site_id, lat, lng)
    g = intervention.evidence_graph(base, intervention_id, intensity)
    if g.get("error"):
        raise HTTPException(404, g["error"])
    return g


@app.get("/intervention/confidence")
def intervention_confidence(lat: float = Query(...), lng: float = Query(...),
                            site_id: str | None = None):
    """Weight-weighted evidence quality per risk, from the engines' own confidence tags."""
    _check_coords(lat, lng)
    return intervention.confidence_report(_baseline(site_id, lat, lng))


# ---------- PS3: Positive Water Impact (PWI) Quantification Engine ----------

@app.get("/pwi/instrument")
def pwi_instrument():
    """The 52-question self-assessment instrument + 3x3 matrix definition + method source."""
    import pwi
    return pwi.instrument()


@app.get("/pwi/context")
def pwi_context(lat: float | None = None, lng: float | None = None, country: str | None = None):
    """LIVE real public water/WASH context (World Bank Open Data). Fetched on demand,
    NOT ingested/stored. Resolve by ISO3 `country` or by lat/lng reverse-geocode."""
    import pwi_context as ctx
    if country:
        return ctx.water_context(country.upper(), None)
    if lat is not None and lng is not None:
        _check_coords(lat, lng)
        name, iso3 = ctx.resolve_country(lat, lng)
        if not iso3:
            raise HTTPException(404, "could not resolve a supported country for this location")
        return ctx.water_context(iso3, name)
    raise HTTPException(422, "provide country=ISO3 or lat&lng")


@app.get("/pwi/demo")
def pwi_demo(context: bool = True):
    """Run the engine on the labeled ASSUMED Chennai example (no real factory data).
    Every output is stamped data_grade=ASSUMED-DEMO. When context=true, also attaches
    LIVE real World Bank water/WASH figures for the site's country (fetched, not stored)."""
    import pwi
    from pwi_demo import chennai_demo
    site = chennai_demo()
    out = pwi.site_pwi(site)
    if context:
        try:
            import pwi_context as ctx
            out["basin_context"] = ctx.water_context("IND", "India")
        except Exception as e:
            out["basin_context"] = {"error": str(e)[:120]}
    return out


class PwiSiteBody(BaseModel):
    site: dict  # {id,name,...,self_assessment:{q:{score,evidence}}, operational:{...}}


@app.post("/pwi/site")
def pwi_site(body: PwiSiteBody):
    """Compute the full PWI profile for one site from supplied inputs. Also attaches
    LIVE real World Bank context for the site's country (fetched on demand, not stored)."""
    import pwi
    if not body.site.get("self_assessment"):
        raise HTTPException(422, "self_assessment (52 question scores) required to compute PWI")
    out = pwi.site_pwi(body.site)
    lat, lng = body.site.get("lat"), body.site.get("lng")
    if lat is not None and lng is not None:
        try:
            import pwi_context as ctx
            name, iso3 = ctx.resolve_country(lat, lng)
            if iso3:
                out["basin_context"] = ctx.water_context(iso3, name)
        except Exception:
            pass
    return out


class PwiPortfolioBody(BaseModel):
    sites: list[dict]


@app.post("/pwi/portfolio")
def pwi_portfolio(body: PwiPortfolioBody):
    """Portfolio PWI rollup across multiple sites (equal-weighted mean of site %)."""
    import pwi
    if not body.sites:
        raise HTTPException(422, "at least one site required")
    return pwi.portfolio_pwi(body.sites)


class PwiRecommendBody(BaseModel):
    results: list[dict]  # list of computed site_pwi() outputs (1 = site plan, N = portfolio plan)


@app.post("/pwi/recommend")
def pwi_recommend(body: PwiRecommendBody):
    """LLM intervention planner (brief steps 14–17): reads the computed PWI outcome
    (gaps, matrix, live basin context) and returns prioritized interventions with
    duration / benefit / cost / phase + a roadmap. Deterministic fallback if no LLM."""
    import pwi_recommend as rec
    if not body.results:
        raise HTTPException(422, "at least one computed site result required")
    return rec.recommend(body.results)


class ExplainBody(BaseModel):
    risk: str
    drivers: dict  # the driver-engine JSON for this site+risk


@app.post("/explain")
def explain(body: ExplainBody):
    return groq_explain(body.risk, body.drivers)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatBody(BaseModel):
    message: str
    history: list[ChatMessage] | None = None


@app.post("/chat")
def chat(body: ChatBody):
    if not _copilot_ok:
        raise HTTPException(503, "Copilot unavailable")
    
    history_dicts = []
    if body.history:
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in body.history]
        
    try:
        res = copilot_instance.ask(body.message, history=history_dicts)
        return res
    except Exception as e:
        print(f"/chat failed: {e}")  # keep internals out of the client response
        raise HTTPException(500, "Copilot request failed - see server logs")


class PwiChatBody(BaseModel):
    message: str
    history: list[ChatMessage] | None = None
    results: list[dict]


@app.post("/pwi/chat")
def pwi_chat(body: PwiChatBody):
    import pwi_recommend as rec
    history_dicts = []
    if body.history:
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in body.history]
    
    ans = rec.pwi_chat(body.message, history_dicts, body.results)
    return {"answer": ans}


# ---------- PS5: Evidence & Disclosure Agent ----------

@app.get("/evidence/demo")
def evidence_demo():
    """Run the full pipeline on labeled SYNTHETIC sample documents
    (Ingest→Classify→Extract→Map→Gap-detect→citation-backed CDP draft)."""
    import evidence
    return evidence.demo()


class EvidenceDoc(BaseModel):
    name: str
    text: str


class EvidenceBody(BaseModel):
    documents: list[EvidenceDoc]
    site: dict | None = None          # {id,name,lat,lng,pfaf_id} — enables verify + persist
    persist: bool = False


@app.post("/evidence/analyze")
def evidence_analyze(body: EvidenceBody):
    """Analyze supplied document text: classify → map → gap → verify claims → grade → draft.
    If `site` (with lat/lng) is given, GEE recompute runs; if `persist`, results are saved to Supabase."""
    import evidence
    if not body.documents:
        raise HTTPException(422, "at least one document (name + text) required")
    site = body.site or {}
    return evidence.run_pipeline(
        [{"name": d.name, "text": d.text} for d in body.documents],
        lat=site.get("lat"), lng=site.get("lng"),
        site=body.site if body.persist else None, persist=body.persist)


def _extract_text(name: str, raw: bytes) -> str:
    """Turn an uploaded PDF / xlsx / text file into plain text for the pipeline."""
    low = name.lower()
    try:
        if low.endswith(".pdf"):
            import io
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        if low.endswith((".xlsx", ".xlsm")):
            import io
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
            lines = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None and str(c).strip()]
                    if cells:
                        lines.append(" | ".join(cells))
            return "\n".join(lines)
    except Exception as e:
        return f"[could not extract text from {name}: {str(e)[:120]}]"
    return raw.decode("utf-8", errors="replace")   # txt / csv / md


@app.post("/evidence/upload")
async def evidence_upload(files: list[UploadFile] = File(...),
                          site_id: str | None = Form(None), name: str | None = Form(None),
                          lat: float | None = Form(None), lng: float | None = Form(None),
                          pfaf_id: int | None = Form(None), persist: bool = Form(False)):
    """Multi-file upload (PDF / xlsx / txt). Extracts text server-side, runs the full
    verification+disclosure pipeline, and (if persist) saves to Supabase."""
    import evidence
    if not files:
        raise HTTPException(422, "upload at least one file")
    docs = []
    for f in files:
        raw = await f.read()
        docs.append({"name": f.filename, "text": _extract_text(f.filename, raw)})
    site = None
    if site_id:
        site = {"id": site_id, "name": name or site_id, "lat": lat, "lng": lng, "pfaf_id": pfaf_id}
    return evidence.run_pipeline(docs, lat=lat, lng=lng,
                                 site=site if persist else None, persist=persist)


# ---------- factory input: add a site end-to-end ----------

class SiteBody(BaseModel):
    name: str
    id: str | None = None
    lat: float
    lng: float


@app.post("/sites")
def add_site(body: SiteBody, user: dict | None = Depends(optional_user)):
    """Factory input (name, id, lat/lng) -> basin resolve -> profile+PWI+futures
    cached -> basin polygon stored -> site persisted. The pin is fully live on return.
    Driver explainability computes lazily on first 'Why <risk>?' click (minutes).

    A logged-in caller's site is stamped with their org_id (private to the org);
    an anonymous caller (guest demo) creates a public, org-less site."""
    import re
    import uuid

    org_id = None
    if user:
        prof = profile_for(user["id"])
        org_id = prof.get("org_id") if prof else None

    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "name required, max 120 characters")
    if body.id is not None and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", body.id):
        raise HTTPException(422, "id may only contain letters, digits, _ . - (max 40 chars)")
    body.name = name

    import ee

    from seed import normalize_geometry

    _check_coords(body.lat, body.lng)
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable - cannot assess new sites right now")
    prof = engine.get_site_profile(body.lat, body.lng)
    if prof is None:
        raise HTTPException(404, "no Aqueduct basin at this location (ocean?)")
    pfaf = prof["_meta"]["pfaf_id"]
    # collision-safe id (the old time()%100000 could collide within a bulk upload)
    site_id = body.id or f"U{uuid.uuid4().hex[:8]}"

    pwi = engine.derive_pwi_scores(prof)
    fut = {f"bau{y}": engine.get_future(pfaf, y, "bau") for y in (30, 50)}
    supa.upsert_risk_cache(pfaf, profile=prof, future=fut, pwi=pwi)

    geom = (engine.AQ().filterBounds(ee.Geometry.Point([body.lng, body.lat]))
            .first().geometry().simplify(maxError=1000).getInfo())
    props = {f"{c}_score": prof[c]["score"] for c in engine.ALL_IND}
    props.update({"pfaf_id": pfaf, "w_awr_def_tot_score": prof["overall_gee"],
                  "w_awr_def_tot_cat": prof.get("overall_cat"),
                  "site_id": site_id, "name": body.name, "lat": body.lat, "lng": body.lng})
    supa.upsert_basin(pfaf, normalize_geometry(geom), props)

    site = {"id": site_id, "name": body.name, "lat": body.lat, "lng": body.lng, "pfaf_id": pfaf}
    if org_id:
        site["org_id"] = org_id
    supa.upsert_site(site)
    return {"site": site, "overall": prof["overall_gee"],
            "level": engine.classify_risk_level(prof["overall_gee"]), "pwi": pwi["dims"]}


# ---------- local news signals ----------

RISK_TO_NEWS = {"bws": "scarcity", "drr": "drought", "gtd": "groundwater",
                "rfr": "flood", "cfr": "flood", "ucw": "quality"}


@app.get("/news")
def news(lat: float, lng: float, pfaf_id: int | None = None):
    """Local clippings for the site's HIGHEST-scoring risk, sentiment+gov-action
    tagged. Place = reverse-geocoded locality (falls back to basin province)."""
    from news import local_news

    _check_coords(lat, lng)

    top_risk, place = "scarcity", None
    cached = _cache_read(supa.get_risk_cache, pfaf_id) if pfaf_id else None
    if cached and cached.get("profile"):
        p = cached["profile"]
        scores = {c: (p.get(c) or {}).get("score") for c in RISK_TO_NEWS}
        scores = {c: s for c, s in scores.items() if s is not None}
        if scores:
            top_risk = RISK_TO_NEWS[max(scores, key=lambda c: scores[c])]
        meta = p.get("_meta") or {}
        place = meta.get("province") or meta.get("country")
    try:
        from geopy.geocoders import Nominatim
        loc = Nominatim(user_agent="hydris-news").reverse((lat, lng), zoom=10, language="en")
        addr = (loc.raw or {}).get("address", {}) if loc else {}
        place = addr.get("city") or addr.get("county") or addr.get("state") or place
    except Exception:
        pass
    if not place:
        raise HTTPException(400, "could not resolve a locality for news search")
    return local_news(place, top_risk)


# ---------- finer sub-basins around a site ----------

_subs_cache: dict = {}


@app.get("/subbasins")
def subbasins(lat: float, lng: float, level: int = 9, radius_km: float = 75):
    """HydroSHEDS level-N sub-basins around the site, each colored by the overall
    score of the Aqueduct basin containing its centroid. Finer POLYGONS, honest
    SCORES: risk is defined at Aqueduct's basin resolution, so neighbouring
    sub-basins inside one Aqueduct basin legitimately share a score."""
    import ee

    _check_coords(lat, lng)
    if not _gee_ok:
        raise HTTPException(503, "GEE unavailable")
    key = (round(lat, 2), round(lng, 2), level, int(radius_km))
    if key in _subs_cache:
        return _subs_cache[key]

    buf = ee.Geometry.Point([lng, lat]).buffer(radius_km * 1000)
    try:
        subs = ee.FeatureCollection(f"WWF/HydroSHEDS/v1/Basins/hybas_{level}").filterBounds(buf)
        aq = engine.AQ().filterBounds(buf)
        withc = subs.map(lambda f: f.set({"c": f.geometry().centroid(100)}))
        joined = ee.Join.saveFirst("aq").apply(
            withc, aq, ee.Filter.intersects(leftField="c", rightField=".geo", maxError=100))

        def shape(f):
            f = ee.Feature(f)
            aqf = ee.Feature(f.get("aq"))
            return ee.Feature(f.geometry().simplify(300), {
                "hybas_id": f.get("HYBAS_ID"),
                "overall": aqf.get("w_awr_def_tot_score"),
                "pfaf_id": aqf.get("pfaf_id"),
            })

        fc = joined.map(shape).getInfo()
    except Exception as e:
        raise HTTPException(502, f"sub-basin fetch failed: {str(e)[:200]}")

    for f in fc.get("features", []):
        v = f["properties"].get("overall")
        if v in (-9999, -9999.0):
            f["properties"]["overall"] = None
    if len(_subs_cache) >= 64:  # bound the per-process cache (each entry is a large FC)
        _subs_cache.pop(next(iter(_subs_cache)))
    _subs_cache[key] = fc
    return fc

@app.get("/sites")
def list_sites(user: dict | None = Depends(optional_user)):
    """Portfolio read. Public (org-less) demo sites are visible to everyone incl.
    the guest demo; sites that belong to an org are returned only to members of
    that org. This replaces the old unconditional service-role dump of every row."""
    org_id = None
    if user:
        prof = profile_for(user["id"])
        org_id = prof.get("org_id") if prof else None
    try:
        q = supa.client().table("sites").select("*")
        if org_id:
            rows = q.or_(f"org_id.is.null,org_id.eq.{org_id}").execute().data
        else:
            rows = q.is_("org_id", "null").execute().data
        return rows
    except Exception as e:
        print(f"/sites list failed: {e}")
        raise HTTPException(503, "sites unavailable")


# ---------- Organization & User CRUD ----------

import re as _re

_UUID_RE = _re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                       r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class OrgBody(BaseModel):
    name: str


@app.post("/organizations")
def create_organization(body: OrgBody, user: dict = Depends(require_user)):
    name = body.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "organization name required, max 120 characters")
    try:
        res = supa.client().table("organizations").insert({"name": name}).execute()
    except Exception as e:
        print(f"/organizations insert failed: {e}")
        raise HTTPException(500, "failed to create organization")
    if not res.data:
        raise HTTPException(500, "failed to create organization")
    return res.data[0]


@app.get("/organizations")
def list_organizations(user: dict = Depends(require_user)):
    """Only the caller's own organization — never the full tenant list."""
    prof = profile_for(user["id"])
    if not prof or not prof.get("org_id"):
        return []
    try:
        return (supa.client().table("organizations").select("*")
                .eq("id", prof["org_id"]).execute().data)
    except Exception as e:
        print(f"/organizations list failed: {e}")
        raise HTTPException(503, "organizations unavailable")


class UserBody(BaseModel):
    id: str  # auth.users id
    org_id: str
    role: str = "viewer"


@app.post("/users")
def create_user_profile(body: UserBody, user: dict = Depends(require_user)):
    """Create a user_profiles row. Access rules (this endpoint uses the
    RLS-bypassing service role, so it must enforce them itself):
      * You may create a profile for SOMEONE ELSE only if you are already an
        admin of that org (inviting a teammate).
      * You may create your OWN profile only into an org that has no members
        yet — the onboarding case, where the org's first user becomes its admin.
        Self-joining an org that already has members requires an admin to add you.
    This blocks the previous privilege escalation (anyone POSTing role=admin
    into any existing org)."""
    if not _UUID_RE.fullmatch(body.id):
        raise HTTPException(422, "id must be a UUID (Supabase auth user id)")
    if not _UUID_RE.fullmatch(body.org_id):
        raise HTTPException(422, "org_id must be a UUID")
    if body.role not in ("admin", "viewer"):
        raise HTTPException(422, "role must be 'admin' or 'viewer'")

    caller_id = user["id"]
    caller_profile = profile_for(caller_id)
    try:
        members = (supa.client().table("user_profiles").select("id")
                   .eq("org_id", body.org_id).execute().data)
    except Exception as e:
        print(f"/users membership check failed: {e}")
        raise HTTPException(503, "user profiles unavailable")

    if body.id != caller_id:
        # inviting another user -> caller must be an admin of the target org
        if not (caller_profile and caller_profile.get("org_id") == body.org_id
                and caller_profile.get("role") == "admin"):
            raise HTTPException(403, "only an org admin can add other users")
    else:
        # creating your own profile
        if caller_profile:
            raise HTTPException(409, "profile already exists")
        if members:
            raise HTTPException(403, "organization already has members; ask an admin to add you")
        body.role = "admin"  # first user of a fresh org is its admin

    try:
        res = supa.client().table("user_profiles").upsert(body.model_dump()).execute()
    except Exception as e:
        print(f"/users upsert failed: {e}")  # e.g. FK violation: id not in auth.users
        raise HTTPException(400, "could not create profile - is the id a real auth user?")
    if not res.data:
        raise HTTPException(500, "failed to create user profile")
    return res.data[0]


@app.get("/users/{org_id}")
def list_org_users(org_id: str, user: dict = Depends(require_user)):
    if not _UUID_RE.fullmatch(org_id):
        raise HTTPException(422, "org_id must be a UUID")
    prof = profile_for(user["id"])
    if not prof or prof.get("org_id") != org_id:
        raise HTTPException(403, "not a member of this organization")
    try:
        return supa.client().table("user_profiles").select("*").eq("org_id", org_id).execute().data
    except Exception as e:
        print(f"/users list failed: {e}")
        raise HTTPException(503, "user profiles unavailable")

