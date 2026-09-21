-- Hydris PS1 — Supabase schema (Phase 2)
-- Run in the Supabase SQL editor. RLS: public read, service-role write.

create table if not exists sites (
  id        text primary key,            -- e.g. 'S1'
  name      text not null,
  lat       double precision not null,
  lng       double precision not null,
  pfaf_id   bigint,
  created_at timestamptz default now()
);

create table if not exists risk_cache (
  pfaf_id    bigint primary key,
  profile    jsonb,                      -- get_site_profile output (13 indicators + meta)
  future     jsonb,                      -- {year_scenario: {...}} projections
  pwi        jsonb,                      -- derive_pwi_scores output
  updated_at timestamptz default now()
);

create table if not exists driver_cache (
  site_id    text not null,
  risk       text not null check (risk in ('drought','groundwater','flood')),
  drivers    jsonb not null,             -- full driver-engine output incl. attribution + confidence
  updated_at timestamptz default now(),
  primary key (site_id, risk)
);

create table if not exists basins (
  pfaf_id      bigint primary key,
  geom_geojson jsonb not null,           -- simplified basin polygon (from pilot_basins.geojson)
  props        jsonb                     -- cleaned Aqueduct attributes
);

alter table sites        enable row level security;
alter table risk_cache   enable row level security;
alter table driver_cache enable row level security;
alter table basins       enable row level security;

-- public (anon) read — the map reads these directly via supabase-js
create policy "public read sites"        on sites        for select using (true);
create policy "public read risk_cache"   on risk_cache   for select using (true);
create policy "public read driver_cache" on driver_cache for select using (true);
create policy "public read basins"       on basins       for select using (true);
-- writes only via service-role key (bypasses RLS) — no insert/update policies for anon
