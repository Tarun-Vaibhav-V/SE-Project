-- Hydris PS1 — Organization and Authentication Schema Updates
-- Run this in the Supabase SQL editor to enable multi-tenant organizations.

-- 1. Create Organizations Table
create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz default now()
);

-- 2. Create User Profiles Table (extends Supabase auth.users)
create table if not exists user_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  org_id uuid references organizations(id) on delete cascade,
  role text check (role in ('admin', 'viewer')) default 'viewer',
  created_at timestamptz default now()
);

-- 3. Add org_id to existing sites table
alter table sites add column if not exists org_id uuid references organizations(id);

-- 4. Enable Row Level Security (RLS) on new tables
alter table organizations enable row level security;
alter table user_profiles enable row level security;

-- 5. Define Security Policies

-- Users can only see their own organization
create policy "Users can view their organization" on organizations
  for select using (id in (select org_id from user_profiles where user_profiles.id = auth.uid()));

-- Users can only view their own profile
create policy "Users can view their own profile" on user_profiles
  for select using (id = auth.uid());

-- Sites: org isolation policy (takes effect for rows that HAVE an org_id).
drop policy if exists "Users can read sites in their org" on sites;
create policy "Users can read sites in their org" on sites
  for select using (org_id in (select org_id from user_profiles where user_profiles.id = auth.uid()));

-- IMPORTANT: keep public read until org onboarding backfills sites.org_id.
-- Every existing site has org_id NULL, which matches NO organization — so the
-- org policy alone hides the whole portfolio from everyone, including
-- logged-in users (this exact outage happened when v1 of this file dropped
-- the policy below). Remove it only after: (1) real signup assigns org_id to
-- every site, and (2) the frontend attaches the user's session to reads.
drop policy if exists "public read sites" on sites;
create policy "public read sites" on sites for select using (true);

-- The FastAPI Service-Role bypasses RLS for CRUD operations
