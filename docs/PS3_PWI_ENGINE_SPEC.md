# PS3 — Positive Water Impact (PWI) Quantification Engine
## Methodology spec + complete input checklist (auditable)

> **Status: awaiting mandatory inputs.** Per the brief, no site calculations begin until every
> Mandatory input is collected. This document is the collection instrument + the engine contract.

---

## 0. Provenance — nothing here is assumed

Every formula, weight, threshold and dimension below is taken from the **provided resource pack**,
not invented:

| What | Source in repo |
|---|---|
| 3×3 matrix, pillar/dimension structure, 52-question instrument | `Water Stewardship Module_Hydris_xlsx.xlsx` → sheets *PWI 4-Step Framework*, *5. Self-Assessment* |
| Scoring formulas, weights, targets (20/40/40) | same xlsx → *3. Baseline & Targets*, *5. Self-Assessment* §B–C |
| Confidence rule, XV penalties, certification tiers | same xlsx → *5. Self-Assessment* §C–D, *7. PWI Dashboard* |
| Datasets / APIs (38 layers) | `Open_Water_Data_Catalog.xlsx` |
| Volumetric/quality benefit accounting | VWBA 2.0 / WQBA (WRI/LimnoTech) — catalog row 36; CEO Water Mandate / WRC PWI framework — catalog row 35 |
| Auto-derived GIS, WRI Aqueduct, satellite/climate | already built in this repo (`backend/engine.py`, `backend/drivers.py`, `/site`, `/subbasins`) |

**Hackathon scoping note (PS3 brief, page 1):** *"Use the stewardship benefit outputs provided.
You are NOT asked to build the WQBA computation."* → The per-intervention **water benefit (m³/yr)**
is a **factory input**, not something we recompute. Our engine consumes those benefit numbers and
rolls them into the PWI matrix with sources, formulas, assumptions and confidence bands.

---

## 1. The engine contract (what we compute)

### 1.1 The 3×3 PWI Matrix
- **Pillars (the "P" axis):** `P1 = Site` · `P2 = Sub-Basin` · `P3 = Basin`
- **Dimensions (the "D" axis):** `Availability` · `Quality` · `Access`
- 3 × 3 = **9 cells**. The 52 self-assessment questions map onto these 9 cells.

### 1.2 Scoring formulas (verbatim from the methodology)
| Output | Formula | Units | Source sheet |
|---|---|---|---|
| Dimension score (qualitative path) | `Σ question scores / max score × 100` (each Q scored 0–3) | % | 5. Self-Assessment §B |
| Availability score (quantitative path) | `Actual Replenishment ÷ Target × 100` | % | 3. Baseline & Targets §C |
| Quality score (quantitative path) | `Pollutant Removal % × 100` | % | 3. Baseline & Targets §C |
| Access score (quantitative path) | `WASH Access % × 100` | % | 3. Baseline & Targets §C |
| **Pillar score** | `Availability×0.4 + Quality×0.3 + Access×0.3` | % | 3. Baseline & Targets §C |
| **Site PWI score** | `(P1 + P2 + P3) ÷ 3` | % | 3. Baseline & Targets §C |
| **Portfolio PWI score** | `Σ Site scores ÷ #Sites × 100` | % | 3. Baseline & Targets §C |
| PWI (positive) threshold | `≥ 100% on all dimensions` | — | 3. Baseline & Targets §C |

### 1.3 Confidence band
- Per question, evidence status → raw confidence: **Yes = 100% · Partial = 70% · No = 50%**.
- **10 cross-validation (XV) rules** flag inconsistencies; each firing subtracts a penalty
  (−0.15 to −0.30). `Adjusted Confidence = Raw Confidence − Σ XV penalties`.
- Example XV: `IF Q15 (zero-discharge) ≥ 2 AND Q9 (WWTP operational) < 2 → FLAG (−0.30)`.

### 1.4 Certification decision matrix
| PWI score | Confidence | Result |
|---|---|---|
| ≥ 100% | ≥ 75% | SELF-CERTIFIED — Positive Water Impact achieved (valid 3 yr) |
| 80–99% | ≥ 75% | CONDITIONAL — partial desk audit (valid 1 yr) |
| 60–79% | ≥ 50% | IN PROGRESS — external audit needed |
| < 60% | any | NOT ACHIEVED — revised plan required |
| any | < 50% | LOW CONFIDENCE — fix data quality first |

### 1.5 Targets & gap analysis
- Auto-targets use the **20/40/40 split**: 20% of replenishment at Site, 40% Sub-Basin, 40% Basin.
- Gap = `Target − Current` per cell; the engine recommends interventions to close each gap and
  projects the post-intervention PWI (current benefit + Σ intervention benefits ÷ target).

**Traceability contract:** every number the engine emits carries `{value, unit, formula, source,
assumptions[], confidence_pct, confidence_basis}`.

---

## 2. COMPLETE INPUT CHECKLIST (A–H)

Legend — **M** = Mandatory, **O** = Optional, **AUTO** = system-derived (no factory input),
**BUILT** = already implemented in this repo.

### A. Mandatory Factory Inputs — *must be collected before any calculation*
| Field | Description | Type | Unit | M/O | Example | Why needed | Used by |
|---|---|---|---|---|---|---|---|
| Factory ID | Unique site key | string | — | M | `NKE-IN-014` | Join key across tables | all |
| Factory Name | Human name | string | — | M | `Chennai Apparel Unit` | Reporting | report |
| Company Name | Parent/brand | string | — | M | `Acme Apparel` | Portfolio rollup | portfolio |
| Latitude | WGS84 lat | float | ° | M | `13.0827` | Geolocate → GIS/basin | C, D, E, F |
| Longitude | WGS84 lng | float | ° | M | `80.2707` | Geolocate → GIS/basin | C, D, E, F |
| Factory Address | Postal address | string | — | M | `Ambattur, Chennai` | Verification | report |
| Industry Type | Sector | enum | — | M | `Textile` | Sector water-intensity benchmark | Availability |
| Annual Water Withdrawal | Total intake, all sources | float | m³/yr | M | `520000` | Denominator for replenishment ratio | Availability, water balance |
| Water Source Mix | % groundwater/surface/municipal/rain/recycled | object(%) | % | M | `{gw:40,surf:30,muni:20,rain:5,recy:5}` | Risk-weighted intake, diversification | Availability |
| Water Consumed | Consumed (not returned) | float | m³/yr | M | `180000` | Water balance closure | water balance |
| Water Recycled | Internally recycled | float | m³/yr | M | `60000` | Stewardship benefit | Availability |
| Water Reused | Reused volume | float | m³/yr | M | `25000` | Stewardship benefit | Availability |
| Wastewater Generated | Effluent produced | float | m³/yr | M | `300000` | Quality load basis | Quality |
| Wastewater Treated | Volume treated | float | m³/yr | M | `285000` | Treatment/removal ratio | Quality |
| Treatment Facility Details | WWTP type, capacity, removal % | object | mixed | M | `{type:'MBR', cap_m3d:1200, TSS_rem:0.94}` | Pollutant removal, compliance | Quality |
| Existing Stewardship Interventions | List of implemented projects | array | — | M | `[recycling, RWH, wetland]` | Core PWI benefit rollup | matrix |
| Annual Water Benefit / Intervention | Verified benefit per project | float[] | m³/yr | M | `[60000, 18000, 45000]` | **Replenishment numerator (WQBA-provided)** | Availability P1/P2/P3 |
| Baseline Year | Reference year | int | yr | M | `2022` | % improvement denominator | gap analysis |
| Current Reporting Year | Reporting period | int | yr | M | `2025` | Comparison | gap analysis |
| Data Source | Provenance of each number | string | — | M | `SCADA meters` | Auditability | confidence |
| Measurement Method | metered / estimated / modelled | enum | — | M | `metered` | Confidence band | confidence |
| Last Updated | Freshness | date | ISO | M | `2025-12-31` | Traceability | confidence |

> **Note on `Basin Name`:** the PS3 factory sheet lists it Mandatory *"(or auto-detected)"*. We
> **auto-detect** it from lat/lng (§C), so the owner does not supply it — they only confirm it.

### A′. Mandatory Self-Assessment Inputs (the score driver)
The PWI score is primarily driven by the **52-question self-assessment** (each scored **0–3** with an
evidence flag). Without these, only the quantitative Availability/Quality/Access proxies can be
computed. Collected as a 52-row set: `{q_id, score 0–3, evidence: Yes|Partial|No, evidence_link}`.
Mapping: Q1–22 → P1(Site), Q23–38 → P2(Sub-Basin), Q39–52 → P3(Basin), split Availability/Quality/Access.

### B. Optional Factory Inputs — *sharpen accuracy & confidence*
| Field | Description | Type | Unit | M/O | Example | Why needed | Used by |
|---|---|---|---|---|---|---|---|
| Factory Area | Footprint | float | m² | O | `45000` | RWH yield, exposure | Availability |
| Number of Employees | Headcount | int | people | O | `1800` | WASH ratios | Access |
| Watershed / Sub-basin | Finer unit | string | — | O | `HydroBASINS L9 id` | Precise P2 context | Availability P2 |
| River / Aquifer Name | Named hydrology | string | — | O | `Cooum / Chennai aquifer` | Hydrological context | D |
| Daily Water Withdrawal | Ops-level intake | float | m³/day | O | `1425` | Operational analysis | Availability |
| Water Discharged | Returned to environment | float | m³/yr | O | `285000` | Water balance closure | water balance |
| Water Losses | Unaccounted | float | m³/yr | O | `15000` | Efficiency, XV checks | water balance |
| Peak Water Demand | Max draw | float | m³/day | O | `1900` | Capacity planning | Availability |
| Water Quality Params | BOD/COD/TSS/pH influent+effluent | object | mg/L | O | `{BOD_in:320,BOD_out:22}` | Advanced quality scoring | Quality |
| Intervention Cost | CAPEX per project | float[] | currency | O | `[120000]` | ROI, cost/m³ | roadmap |
| O&M Cost | Running cost | float[] | currency/yr | O | `[9000]` | ROI | roadmap |
| Government Subsidy | Grants | float | currency | O | `20000` | Economic assessment | roadmap |
| Community Beneficiaries | People served | int | people | O | `3200` | Access P2/P3 | Access |
| Villages/Farmers Benefited | Count | int | count | O | `6` | Access P2/P3 | Access |
| Production Capacity | Output | float | units/yr | O | `9.0e6` | Water intensity | Availability |
| Operating Days/Hours | Uptime | object | d, h | O | `{days:310}` | Efficiency metrics | Availability |
| Regulatory Permits | Consents held | array | — | O | `[CPCB consent]` | Compliance, XV | Quality |
| Confidence Score | Owner-declared certainty | float | % | O | `85` | Advanced uncertainty | confidence |

### C. GIS Data — AUTO-derived from lat/lng
| Field | Description | Source | Status | Used by |
|---|---|---|---|---|
| Basin (pfaf_id) | HydroBASINS/Aqueduct basin | GEE Aqueduct join | **BUILT** (`/site`) | D, matrix P3 |
| Sub-basin (L9/L12) | HydroSHEDS finer unit | GEE `hybas_9` | **BUILT** (`/subbasins`) | matrix P2 |
| Watershed polygon | Basin boundary geometry | HydroBASINS | **BUILT** | map, context |
| River (nearest reach) | HydroRIVERS routing | HydroRIVERS (catalog #6) | TO WIRE | D, context |
| Aquifer | Aquifer unit/name | WHYMAP / CGWB (IN) | TO WIRE | D, groundwater |
| Admin boundaries | Country / province / district | Aqueduct `name_0/1`, GADM | **BUILT** (partial) | report, JMP join |
| Elevation / slope | Terrain | Copernicus DEM (catalog #29) | **BUILT** (drivers) | flood/recharge |
| Land cover | LULC around site | ESA WorldCover (catalog #28) | **BUILT** (drivers) | recharge, RWH |

### D. Basin Data Required
| Field | Description | Source | Status | Used by |
|---|---|---|---|---|
| WRI Aqueduct 13 indicators | bws, bwd, iav, sev, gtd, rfr, cfr, drr, ucw, cep, udw, usa, rri | Aqueduct 4.0 (catalog #1) | **BUILT** | risk context, XV, targets |
| Future projections | 2030/2050/2080 stress etc. | Aqueduct future | **BUILT** (`/future`) | gap, trend |
| Renewable water / availability | Basin water resources | FAO AQUASTAT (catalog #22) | TO WIRE | Availability denominators |
| Environmental flow requirement | E-flow threshold | HydroATLAS / literature | TO CONFIRM | replenishment target |
| Basin population | People in basin | WorldPop / GHSL (catalog #32/33) | **BUILT** (GHSL partial) | Access P3 |
| WRC priority status | In WRC Top 100? | CEO Water Mandate / WRC (catalog #35) | **NEEDS LIST** | prioritization, significance |

### E. Satellite Data Required — mostly BUILT in `drivers.py`
| Field | Source | Status |
|---|---|---|
| Rainfall (design storm, SPI) | CHIRPS (catalog #17) | **BUILT** |
| NDVI (vegetation stress) | MODIS MOD13Q1 | **BUILT** |
| Soil moisture | GLDAS / SMAP (catalog #14) | **BUILT** |
| Evapotranspiration / PET | MOD16 / TerraClimate (#19) | **BUILT** |
| Groundwater storage anomaly | GRACE (catalog #12) | **BUILT** |
| Built-up change (exposure) | GHSL (catalog #33) | **BUILT** |
| Surface water extent | JRC GSW (catalog #10) | TO WIRE (optional) |

### F. Climate Data Required
| Field | Source | Status | Used by |
|---|---|---|---|
| Precipitation (annual, seasonality) | CHIRPS / ERA5 (#17/#18) | **BUILT/partial** | RWH yield, recharge |
| Temperature / PET / aridity | TerraClimate / ERA5 (#19/#18) | **BUILT/partial** | water balance |
| Future climate (SSP scenarios) | NEX-GDDP-CMIP6 (#20) | TO WIRE | forward gap |
| Drought indices (SPI/SPEI) | Copernicus GDO (#15) | **BUILT (own SPI)** | Availability risk |

### G. WRC / WQBA Data Required
| Field | Description | Source | Status |
|---|---|---|---|
| PWI methodology (formulas/weights) | pillar/dimension math, thresholds | **provided** (WSM xlsx) | **HAVE** |
| 52-Q self-assessment instrument | question bank + evidence + XV rules | **provided** (WSM xlsx) | **HAVE** |
| Certification tiers & confidence | decision matrix | **provided** (WSM xlsx) | **HAVE** |
| Per-intervention benefit (m³/yr) | volumetric/quality benefit | **factory input** (A) + VWBA 2.0 method (#36) | **HAVE (as input)** |
| WRC Top 100 Priority Basins list | basin → priority flag | CEO Water Mandate / WRC (#35) | **NEEDS SOURCE FILE** |
| Context-based / basin targets | replenishment target basis | 20/40/40 (WSM) + basin availability | **HAVE (method)**, data TO WIRE |

### H. External APIs / Datasets Required
| Service | Purpose | Status |
|---|---|---|
| Google Earth Engine | GIS, Aqueduct, satellite, climate | **BUILT** (service-account live) |
| Nominatim / OSM | geocode / reverse-geocode | **BUILT** |
| WHO/UNICEF JMP | WASH access baselines (Access pillar) | TO WIRE (#27) |
| FAO AQUASTAT | national/basin withdrawals & availability | TO WIRE (#22) |
| WorldPop | population served counts | TO WIRE (#32) |
| HydroRIVERS / WHYMAP / CGWB | river & aquifer naming | TO WIRE |
| WRC / CEO Water Mandate | Top 100 basin list + framework | **NEEDS LIST** |
| Groq LLM | narrative + recommendations (grounded) | **BUILT** |

---

## 3. Already handled by the existing Hydris build (do NOT re-ask)
Categories **C, D, E, F** are largely solved by PS1/PS2: `/site` returns the basin + 13 Aqueduct
indicators + PWI-style dimensions; `/subbasins` gives the sub-basin (P2) geometry; `drivers.py`
computes CHIRPS/GLDAS/GRACE/SMAP/MODIS/GHSL series; `/future` gives 2030/2050 projections. So the
**only things a factory owner must actually provide are Section A + A′.**

## 4. Genuine gaps to confirm before/at build time
1. **WRC Top 100 Priority Basins list** — need the authoritative file (CEO Water Mandate). Until
   provided, the "is this a priority basin?" flag stays `unknown`, never guessed.
2. **JMP / WorldPop / AQUASTAT wiring** — needed for true Access (WASH) and basin-availability
   denominators; until wired, Access uses site WASH ratios only (labeled `site-only`).
3. **River/aquifer naming** (HydroRIVERS / WHYMAP / CGWB) — optional context.
4. **Quantitative vs. questionnaire path** — confirm whether score comes from the 52-Q instrument,
   the operational water-balance proxies, or both (blended).

## 5. Blocking ask
Provide **Section A + A′ for at least one site** (or authorize a clearly-labeled worked example on an
existing pilot such as Chennai S1). No site PWI number will be produced until the mandatory set is in.
