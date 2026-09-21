# Hydris AI — Basin Intelligence & Water Risk 

**build.** Enter factory locations → automatically resolve each site's watershed →
return a multi-risk profile (scarcity / flood / drought / groundwater), **today and under
2030/2050 scenarios**, with **explainable drivers behind every score** — computed from satellite
data, never invented.


Smoke test: map loads dark with 6 colored basin polygons → click the Chennai pin → risk card
with three PWI rings → "Why drought?" → attribution bars + AI narrative → "📰 Local news" →
tagged clippings. Add a factory via the **＋** button (any point on Earth).

The Colab notebooks (§7) are **not needed to run the app** — they are the reference
implementation and gate tests; their outputs are already seeded into Supabase.

---

## 2. What this is (context for a new contributor or AI)

- **Problem statement**: "Basin Intelligence and Water Risk" (see
  ). Deliverables: interactive site map, basin
  boundaries, current & future risk scores, explanation of what drives each score.
  
- **PWI framework**: Positive Water Impact = **Availability / Quality / Accessibility**. We map
  WRI's 13 risk indicators onto these three dimensions (the ring gauges) — the vocabulary the
  judges score on.
- **Design references** (all in repo root): three driver-formula toolkits (drought PDF,
  groundwater PDF, flood DOCX), the Water Stewardship Module UI spec (xlsx — S-01/S-02 screens,
  design tokens), and the Open Water Data Catalog (xlsx — dataset licenses).

### The one principle everything follows: the honesty layer

1. Aqueduct's `-9999` no-data → `null` everywhere. Missing values are **excluded and weights
   renormalized** — never coerced to 0.
2. Every driver carries `source` (dataset ID) + `confidence` (`computed` / `proxy` /
   `regional` / `no-data`). Proxies are labeled, not hidden.
3. Attribution % is always "estimated contribution to the modelled score", never physical cause.
4. GRACE is ~300 km resolution → always tagged `regional`, never sold as site-scale.
5. LLM narratives are **mechanically validated**: every number in the text must exist in the
   computed JSON; on failure → retry → deterministic template built from the JSON itself.
6. Dataset IDs are **probed live in GEE before use** — nothing is assumed from memory.
7. WRI projects only stress/depletion/variability to 2030/50/80 — the UI badges flood/drought/
   groundwater as "baseline (not projected by WRI)" instead of faking projections.

---

## 3. Architecture

```
┌── FRONTEND  React 18 + Vite + MapLibre GL (frontend/) ── localhost:5173 ──────────┐
│  S-01 full-bleed dark map: search · 7-layer selector · legend · basemap toggle    │
│  S-02 risk card: overall 48px · 13 mini-bars · PWI ring gauges · derived chips    │
│  Panels: driver attribution+narrative · local news · 2030/2050 · custom weights   │
│  Add-site FAB (name/id/lat-lng or map-pick) · level-9 sub-basin overlay           │
└──────┬──────────────────────────────────────────┬─────────────────────────────────┘
       │ supabase-js (anon key, read-only via RLS) │ REST (compute on cache miss)
       ▼                                          ▼
┌── SUPABASE (cloud Postgres) ─────┐   ┌── FASTAPI GEE-compute (backend/) :8000 ────┐
│ sites        factory registry    │◄──┤ /sites  add factory end-to-end (writes)    │
│ risk_cache   profile+future+PWI  │   │ /site /future /reweight /portfolio /search │
│ driver_cache 3 risks × site      │   │ /drivers (3 engines) /explain (Groq)       │
│ basins       polygons + scores   │   │ /news (NewsAPI+Groq) /subbasins (hybas_9)  │
│ RLS: public read, service write  │   └───┬──────────────┬──────────────┬──────────┘
└──────────────────────────────────┘       ▼              ▼              ▼
                                    Google Earth      Groq API       NewsAPI
                                    Engine (service   llama-3.3-70b  (localhost-
                                    account auth)     (validated)    only free tier)
```

**Resilience chain** (why the demo can't die on stage): frontend reads Supabase first →
bundled demo JSON (`frontend/src/demo/`) if Supabase is unreachable → FastAPI only for
uncached compute. Kill GEE and every seeded site still works fully.

### Data flow for one click
1. User clicks a pin → `risk_cache` row fetched by `pfaf_id` (profile + PWI + futures, ~100 ms).
2. Sub-basins fetched (`/subbasins`, cached in-process after first call).
3. "Why drought?" → `driver_cache` hit (instant) or live engine run (~1–2 min for new sites).
4. Narrative → `/explain` → Groq (temp 0, no-arithmetic prompt) → numeral validation → text.
5. "Local news" → `/news` → reverse-geocode locality → NewsAPI (title/description match only)
   → one Groq JSON call tags sentiment + gov-action per clipping.

---

## 4. Repo map

```
hydrisai/
├── README.md                     ← you are here
├── RUN_GATES.md                  ← gate runbook (what to run, what "pass" looks like)
├── hydris_ps1_pilot.ipynb        ← Colab: proved basin-resolve + risk-join + 2050 (Phase S1/S2)
├── hydris_aqueduct_engine.ipynb  ← Colab: 7 engine functions + PWI scoring + Gate 0
├── notebooks/
│   └── hydris_drivers.ipynb      ← Colab: 3 driver engines + Gates 1a/1b/1c + export
├── backend/
│   ├── main.py                   ← FastAPI app, all 11 routes
│   ├── engine.py                 ← Aqueduct headline engine (ported 1:1 from notebook)
│   ├── drivers.py                ← drought/groundwater/flood driver engines (ported 1:1)
│   ├── explain.py                ← Groq narrative + numeral validator + template fallback
│   ├── news.py                   ← NewsAPI fetch + Groq sentiment/gov tagging + keyword fallback
│   ├── supa.py                   ← Supabase service-role read/upsert helpers
│   ├── seed.py                   ← seeds sites/basins/profiles/drivers + geometry normalizer
│   ├── tests/test_contract.py    ← offline no-hallucination tests + live contract tests
│   ├── requirements.txt  .env    ← .env holds real keys (see warning at top)
├── frontend/
│   ├── src/App.tsx               ← state + layout wiring
│   ├── src/lib/risk.ts           ← palette, classify, 13 indicators, 7 layers
│   ├── src/lib/data.ts           ← Supabase-first loaders, demo fallback, API calls,
│   │                                geometry normalizer (GeometryCollection→Polygon)
│   ├── src/components/           ← MapView, RiskCard, PWIRing, MiniBar, DriverPanel,
│   │                                NewsPanel, AddSiteModal, Panels (nav/search/layers/
│   │                                legend/basemap/future/weights)
│   ├── src/styles/               ← tokens.css (design tokens) + app.css (S-01 layout)
│   ├── src/demo/                 ← offline fallback data (basins + drivers)
│   └── .env                      ← Supabase URL + ANON key + API URL
├── supabase/schema.sql           ← 4 tables + RLS (already applied to the cloud project)
├── data/
│   ├── pilot_basins.geojson      ← 5 pilot basins (exported by pilot notebook)
│   ├── drivers_demo.json         ← precomputed drivers 5 sites × 3 risks (drivers notebook)
│   └── gen-lang-client-*.json    ← GEE service-account key (see warning)
└── *.pdf / *.docx / *.xlssx      ← problem statement, driver toolkits, UI spec, data catalog
```

---

## 5. Data model 

| Table | Key | Contents |
|---|---|---|
| `sites` | `id` (S1..S5 pilots, S6+ user-added, U* auto-id) | name, lat, lng, `pfaf_id` |
| `risk_cache` | `pfaf_id` | `profile` (13 indicators × raw/score/cat/label + meta + overall), `future` ({bau30,bau50,...}), `pwi` (dimension mapping) |
| `driver_cache` | (`site_id`,`risk`) | full driver-engine JSON: severities, weights, sources, confidence, attribution %, hazard |
| `basins` | `pfaf_id` | simplified polygon (`geom_geojson`) + cleaned Aqueduct props |

RLS: anonymous key = read-only (what the frontend uses); writes go through the
service-role key (backend only). **Geometry gotcha (already fixed, keep in mind):** GEE's
`simplify()` can degrade Polygons into GeometryCollections of LineStrings, which map fill
layers silently skip — `seed.normalize_geometry()` (Python) and `normalizeGeometry()`
(TypeScript) rebuild them; keep both if you touch geometry code.

---

## 6. API reference (FastAPI, `backend/main.py`)

| Route | What it does |
|---|---|
| `GET /health` | `{ok, gee}` — gee:false means cache-only mode |
| `GET /site?lat&lng` | full 13-indicator profile + PWI dims + badge; upserts `risk_cache` |
| `POST /sites {name,id?,lat,lng}` | **factory input end-to-end**: basin resolve → profile+PWI+futures cached → polygon stored → site persisted |
| `POST /reweight {lat,lng,ind_weights}` | custom weighting. Partial dicts are *overrides* (missing = default 1×, exclusion needs explicit 0). Base-2 scale: 0,.25,.5,1,2,4 |
| `GET /future?pfaf_id&year&scenario` | 30/50/80 × optimistic/bau/pessimistic. Only stress/depletion/variability are projected (WRI) |
| `POST /portfolio {sites:[...]}` | batch risk table |
| `GET /search?q` | Nominatim geocode → basin + overall |
| `GET /drivers?risk&lat&lng&site_id?` | driver engine (drought/groundwater/flood); Supabase cache first |
| `POST /explain {risk, drivers}` | Groq narrative, numeral-validated; `engine` field says `groq` or `template` |
| `GET /news?lat&lng&pfaf_id?` | local clippings for the site's **highest-scoring risk**, sentiment + gov-action tagged |
| `GET /subbasins?lat&lng&level=9&radius_km=75` | HydroSHEDS level-9 polygons around the site, scored via centroid-join to Aqueduct basins |

---

## 7. The science layer (engines + notebooks)

### Headline scores — WRI Aqueduct 4.0 via GEE
`WRI/Aqueduct_Water_Risk/V4/baseline_annual` (13 indicators, HydroBASINS level-6 resolution)
and `future_annual` (fields `{opt|bau|pes}{30|50|80}_{ws|wd|iv|sv}_x_s`). Point-in-polygon
lookup in GEE, zero heavy storage. `+9999` = arid-mask (a real score), `-9999` = no-data (null).

### PWI dimension mapping (`derive_pwi_scores`)
- **Availability**: scarcity composite (0.36·bws + 0.36·bwd + 0.18·iav + 0.10·sev),
  flood = MAX(rfr, cfr), drought (drr), groundwater (gtd)
- **Quality**: ucw, cep, rri (spec's `ety` is not in the GEE table → flagged roadmap)
- **Accessibility**: AVG(udw, usa)
- Dimension rollups = equal-weight mean of available components (nulls excluded+renormalized).

### Driver engines (the "why" behind each score) — `backend/drivers.py` = `notebooks/hydris_drivers.ipynb`
All series use a **batched `yearly()` helper**: one `getInfo()` round-trip per driver,
empty-window-safe (lazy `ee.Algorithms.If` guards years before a dataset starts — e.g. MOD16
PET < 2000 — and mission gaps — GRACE 2017-18; unit scaling applied client-side).

| Engine | Formula | Drivers (dataset) |
|---|---|---|
| **Drought** | `D_H = 0.35·M + 0.30·A + 0.35·H`, split evenly inside pillars | SPI gamma-fit, z fallback (CHIRPS 3-mo) · SPEI-lite z of P−PET (MOD16) · soil moisture (GLDAS) · NDVI (MOD13Q1) · runoff (GLDAS Qs_acc) · storage (GRACE, `regional`) |
| **Groundwater** | `GH = 0.35·EP + 0.30·AD + 0.20·RW (+0.15·QD excluded)` | EP `proxy` from Aqueduct gtd+bwd (no global well data — CGWB/USGS NWIS named for production) · AD GRACE linearFit trend · RW = 1 − recharge index (CHIRPS × SoilGrids sand × slope × WorldCover infiltration) · QD excluded, weights renormalize |
| **Flood** | 5 factors: rain .25 · runoff .25 · catchment .20 · soil-sat .15 · urban .15; framed as **Risk = Hazard × Exposure × Vulnerability** (bars = Hazard; urbanization doubles as Exposure proxy) | design storm mean+1σ of annual 1-day maxima (CHIRPS) · **SCS-CN runoff** (HYSOGs250m × WorldCover × NRCS TR-55; `S = 25400/CN − 254`, `Q = (P−0.2S)²/(P+0.8S)`) · flow accumulation + relative elevation (HydroSHEDS) · SMAP saturation · GHSL built-up change |

Every factor is **individually try/except-isolated** — a server-side GEE failure degrades that
factor to `no-data` with the error string recorded, never crashes the engine.
Composite: renormalize weights over available severities → hazard 0–5 → attribution % (sums to 100).

### Notebook gates (all passed)
| Gate | Proves |
|---|---|
| 0 (engine nb) | PWI dims on 5 sites, badges match WRI, zero `-9999` leaks |
| 1a/1b/1c (drivers nb) | attribution ≈100%, gamma-SPI reported, Fresno GRACE decline high, Chennai flood high, **all 5 flood factors computed incl. CN runoff** (HYSOGs found in community catalog) |
| 2 (pytest) | `cd backend && pytest -q` — 7 offline tests (numeral validator, template groundedness, null-handling); +4 live contract tests with .env |

---

## 8. Frontend spec (S-01 / S-02 from the Water Stewardship Module)

- **Theme**: dark command-center. Basemap Carto Dark Matter (chosen to solve the ocean-vs-Low-risk
  blue clash), glass panels, Inter for UI, **JetBrains Mono for every number**.
- **Risk palette** (WRI, ordinal): `#2171B5 → #6BAED6 → #FED976 → #FD8D3C → #BD0026`, no-data
  `#3A4356`. Validated: worst CVD pair ΔE 18.4 (pass); `#BD0026` is 2.85:1 on dark (<3:1) →
  mitigated by always-on text labels + white relief ring on ≥4 fills. Never show color without text.
- **S-01**: top-nav 56px · search 360px top-left · 7-layer radio top-right · legend bottom-left
  240px · basemap toggle · ＋ FAB · WRI attribution footer.
- **S-02 risk card**: name + badge pill · overall 48px mono · 3 PWI rings (signature element) ·
  Flood/Shortage chips · 13 mini-bars (null → "n/d", never 0) · Why-drought/groundwater/flood.
- **Basin display**: coarse Aqueduct basin fill (risk resolution) + on-select **level-9
  sub-basin overlay** (finer polygons, honestly inheriting the containing basin's score).

---

## 9. Secrets inventory (git-ignored — provide your own, never commit)

Each row is created from its `*.example` template and stays local only.

| Where | Template | What |
|---|---|---|
| `backend/.env` | `backend/.env.example` | `GEE_PROJECT`, `GEE_SA_KEY_FILE` (→ your GEE JSON), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`, `GROQ_MODEL`, `NEWS_API_KEY` |
| `frontend/.env` | `frontend/.env.example` | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (public-by-design), `VITE_API_URL` |
| `data/<your>-service-account.json` | — (download from Google Cloud IAM) | Google service-account key for Earth Engine |

---

## 10. Known caveats 

- Risk scores exist at Aqueduct basin resolution; sub-basin polygons refine *shape*, not *score*.
- Groundwater EP is a labeled proxy; QD is excluded (no global groundwater-chemistry raster).
- GRACE is regional (~300 km). SMAP reads top ~5 cm.
- NewsAPI free tier works **only from localhost** — deployed news needs the paid tier or precached
  demo clippings.
- First driver computation for a *new* site takes ~1–2 min (live 30-yr satellite series); pilots
  are precached.
- `/reweight` custom overall uses an equal-weight base (like Aqueduct's own custom tool), so it
  differs from WRI's Delphi-weighted default on the card — by design, captioned in the UI.
- `ety` (country regulatory) isn't in the GEE table → rri used alone, ety flagged roadmap.

---

## Attribution

WRI Aqueduct 4.0 (CC-BY 4.0) · Google Earth Engine · CHIRPS (UCSB CHC) · NASA GLDAS/GRACE/SMAP/
MODIS · WWF HydroSHEDS/HydroBASINS · ESA WorldCover · JRC GHSL · ISRIC SoilGrids · ORNL DAAC
HYSOGs250m · OpenStreetMap Nominatim · NewsAPI.org · Groq (Llama 3.3 70B).
