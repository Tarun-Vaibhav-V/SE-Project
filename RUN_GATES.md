# Hydris — Gate Runbook (what to run, what "pass" looks like)

Build order is gated: **don't start a phase until the previous gate passes.**
Phases 0–1 run in **Colab** (they need your Google/GEE login). Phase 2 runs locally/cloud.

---

## Gate 0 — Engine brain (`hydris_aqueduct_engine.ipynb`)

1. Upload the updated notebook to Colab, set `EE_PROJECT`, run all cells top→bottom.
2. The new cells are at the end: **Function 8** (`derive_pwi_scores` + `classify_risk_level`) and the **GATE 0** cell.

**PASS =** for all 5 sites: 3 PWI dims print; badge matches WRI's category direction;
`Chennai groundwater` and `Riyadh drought` print **"no data"** (never 0); final line says `GATE 0: ✅ PASS`.

---

## Gate 1 — Driver engines (`notebooks/hydris_drivers.ipynb`)

Run all cells top→bottom (expect the driver cells to take **minutes per site** — they pull
20–30 yr satellite series; this is why Supabase caching exists).

**Cell 2 (dataset probe) first:** report which rows print `MISSING`.
- `hysogs MISSING` is expected until you either find it in the community catalog probe or
  download HYSOGs250m from ORNL DAAC (DOI 10.3334/ORNLDAAC/1566) and upload it as a GEE asset
  named `projects/YOUR_PROJECT/assets/HYSOGs250m`. Per Gate 1c, the flood engine still ships
  with runoff marked "pending asset" — that's a pass, not a fail.

**Gate 1a (drought) PASS =** attribution sums ~100%; method shows `gamma-SPI` (fallback noted if not);
Chennai/Fresno hazard direction agrees with their Aqueduct `drr_score`; runtimes printed.

**Gate 1b (groundwater) PASS =** Fresno `aquifer_decline` elevated (>0.6 if GRACE loaded);
`extraction_pressure` labeled `proxy`; `quality_QD` in `excluded`; attribution ~100%.

**Gate 1c (flood) PASS =** Chennai hazard high; if CN computed, Chennai CN ≈ 85–92 (urban);
all assertions pass even with runoff pending.

**Then run the export cell** → download `drivers_demo.json` → put it in `data/`.
Also keep `pilot_basins.geojson` (from the pilot notebook) in `data/`.

---

## Gate 2 — Supabase + API (`backend/`, `supabase/`)

1. Create a Supabase project → SQL editor → run `supabase/schema.sql`.
2. `cd backend && copy .env.example .env` → fill `GEE_PROJECT`, `GEE_SA_KEY_FILE`
   (service-account JSON from Google Cloud IAM), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `GROQ_API_KEY`.
3. `pip install -r requirements.txt`
4. `python seed.py` — seeds sites/basins/profiles/PWI/futures (+ drivers if `drivers_demo.json` present).
5. `uvicorn main:app --reload` → open http://127.0.0.1:8000/docs
6. `pytest -q` — offline tests always run; live contract tests activate once `.env` is filled.

**PASS =** all pytest green; `/site?lat=13.0827&lng=80.2707` returns Chennai with PWI dims;
second `/future` call <0.5 s (Supabase-cached); rows visible in Supabase tables;
with GEE creds removed, cached demo sites still serve.

**Already verified on this machine:** the 7 offline tests pass, including the
no-hallucination validator (invented numbers rejected; template fallback always grounded).

---

## What's next after Gate 2

Phase 3 (MapLibre dark map S-01) → Phase 4 (risk card + PWI rings S-02) → Phase 5 (weights +
future toggle) → Phase 6 (driver panel + Groq narrative) → Phase 7 (CSV, deploy, demo).
Full detail: `C:\Users\tarun\.claude\plans\let-me-ground-this-hazy-possum.md`.
