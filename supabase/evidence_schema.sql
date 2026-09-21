-- Hydris PS5 — Evidence & Disclosure Agent + Formula-Validation/GEE-Audit schema
-- Run in the Supabase SQL editor (project ouddfkokwpzyymttbljf).
-- RLS mirrors the existing tables: public (anon) read, service-role write only.
-- gen_random_uuid() uses pgcrypto, enabled by default on Supabase.

-- 1) Uploaded evidence documents — metadata + extracted text (raw binary optional in Storage)
create table if not exists evidence_documents (
  id             uuid primary key default gen_random_uuid(),
  site_id        text references sites(id) on delete cascade,
  name           text not null,
  doc_type       text,                       -- discharge_permit, effluent_lab_report, meter_water_balance, ...
  storage_path   text,                       -- optional: path in the 'evidence' Storage bucket
  metadata       jsonb,                      -- extracted metadata (authority, dates, params, volumes)
  extracted_text text,                       -- text used by classify/verify (nullable)
  confidence     numeric,                    -- extraction confidence 0-100
  uploaded_at    timestamptz default now()
);
create index if not exists idx_evidence_docs_site on evidence_documents(site_id);

-- 2) Verified intervention claims — claimed vs GEE/formula-recomputed value + grade
--    formula_soundness ∈ {sound, needs_calibration, oversimplified, weak} (from the audit PDF)
--    grade ∈ {A,B,C,D,F}; verified = deviation_pct <= threshold_pct
create table if not exists evidence_claims (
  id                uuid primary key default gen_random_uuid(),
  document_id       uuid references evidence_documents(id) on delete cascade,
  site_id           text references sites(id) on delete cascade,
  intervention      text not null,           -- rainwater_harvesting, groundwater_recharge, check_dam, ...
  formula           text,                    -- the formula string applied
  formula_soundness text,
  claimed_value     numeric,
  claimed_unit      text default 'm3/yr',
  recomputed_value  numeric,                 -- formula + GEE recompute
  deviation_pct     numeric,                 -- |claimed - recomputed| / recomputed * 100
  threshold_pct     numeric,                 -- soundness-based tolerance (20 / 35 / null-for-weak)
  verified          boolean,
  grade             text,                    -- capped by formula soundness
  confidence_pct    numeric,                 -- composite 0.35/0.25/0.20/0.10/0.10 -> 0-100
  factors           jsonb,                   -- 5 confidence sub-scores + GEE inputs used
  created_at        timestamptz default now()
);
create index if not exists idx_evidence_claims_site on evidence_claims(site_id);
create index if not exists idx_evidence_claims_doc  on evidence_claims(document_id);

-- 3) Per-site disclosure rollup — overall CDP grade + citation-backed draft (one row per site)
create table if not exists evidence_reports (
  site_id       text primary key references sites(id) on delete cascade,
  cdp_grade     text,                        -- overall disclosure grade A..F
  coverage_pct  numeric,                     -- CDP questions evidenced
  verified_pct  numeric,                     -- share of claims within threshold
  gaps          jsonb,
  draft         jsonb,                       -- citation-backed CDP responses
  generated_at  timestamptz default now()
);

-- RLS: public read, service-role write (service key bypasses RLS; no anon insert/update policies)
alter table evidence_documents enable row level security;
alter table evidence_claims    enable row level security;
alter table evidence_reports   enable row level security;
create policy "public read evidence_documents" on evidence_documents for select using (true);
create policy "public read evidence_claims"    on evidence_claims    for select using (true);
create policy "public read evidence_reports"   on evidence_reports   for select using (true);
