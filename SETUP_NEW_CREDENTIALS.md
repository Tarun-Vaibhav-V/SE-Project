# Setting up a fresh Supabase project + Google Earth Engine service account

Your old keys were exposed and should be treated as burned. This guide walks
through creating **brand-new** credentials from scratch so the demo runs on
clean, private infrastructure. Follow it top to bottom — steps are ordered
because later ones depend on earlier ones.

Total time: ~25-35 minutes (GEE approval can take longer if your account
isn't already Earth Engine-enabled).

---

## Part A — Supabase (database)

### A1. Create the project

1. Go to https://supabase.com/dashboard and sign in (GitHub login is fine).
2. Click **New project**.
3. Pick an **organization** (create one if you don't have one), a **name**
   (e.g. `hydris-ai-demo`), a strong **database password** — save it
   somewhere, you won't need it for the app but you will if you ever need
   direct Postgres access — and a **region** close to you (e.g. Mumbai/
   Singapore for lowest latency from India).
4. Click **Create new project**. Wait ~2 minutes for provisioning.

### A2. Grab your API keys

1. In the project, go to **Project Settings → API** (gear icon, bottom left).
2. You need three values from this page:
   - **Project URL** — looks like `https://xxxxxxxxxxxx.supabase.co`
   - **anon / public** key — long `eyJ...` JWT, safe to expose to the browser
   - **service_role** key — a different long `eyJ...` JWT. **This one is
     secret** — it bypasses all Row Level Security. Never put it in the
     frontend or commit it.

Keep this tab open — you'll paste these into `.env` files in Part C.

### A3. Run the schema files

The repo has three SQL files that create every table the app needs. Run them
**in this order** (later files reference tables from earlier ones via
foreign keys).

1. In the Supabase dashboard, open **SQL Editor** (left sidebar) → **New query**.
2. Open [`supabase/schema.sql`](supabase/schema.sql) in this repo, copy its
   entire contents, paste into the SQL editor, click **Run**.
   - Creates: `sites`, `risk_cache`, `driver_cache`, `basins` — the core
     risk-engine tables, with public-read RLS policies.
3. New query → open [`supabase/schema_v2.sql`](supabase/schema_v2.sql), paste, **Run**.
   - Creates: `organizations`, `user_profiles`; adds `org_id` to `sites`;
     sets up the multi-tenant auth policies.
4. New query → open [`supabase/evidence_schema.sql`](supabase/evidence_schema.sql), paste, **Run**.
   - Creates: `evidence_documents`, `evidence_claims`, `evidence_reports` —
     the PS5 Evidence & Disclosure Agent tables.

After all three, check **Table Editor** (left sidebar) — you should see 7
tables: `sites`, `risk_cache`, `driver_cache`, `basins`, `organizations`,
`user_profiles`, `evidence_documents`, `evidence_claims`, `evidence_reports`
(9 total, some created across the two files).

### A4. Enable email auth (needed for sign-up/login to work)

1. **Authentication → Providers** → confirm **Email** is enabled (it is by
   default).
2. **Authentication → URL Configuration** → set **Site URL** to
   `http://localhost:5173` for local demo purposes.
3. If you don't want email-confirmation friction during a live demo:
   **Authentication → Providers → Email** → turn **Confirm email** OFF.
   (Turn it back on before any real public launch.)

Supabase side is done.

---

## Part B — Google Earth Engine service account

This is what lets the backend compute real satellite-derived risk scores for
**new** sites you add live. (The 5 pilot sites already have precomputed data
bundled in the repo, so the demo works even without this — see the "offline
mode" note in Part D. But a live "add a new factory" demo needs this.)

### B1. Create / choose a Google Cloud project

1. Go to https://console.cloud.google.com/
2. Create a new project (or reuse one): top bar → project dropdown → **New
   Project**. Name it something like `hydris-demo`. Note the **Project ID**
   shown under the name (e.g. `hydris-demo-123456`) — you'll need this exact
   string later.

### B2. Enable the Earth Engine API

1. In the same project, go to **APIs & Services → Library**.
2. Search "**Earth Engine API**" → click it → **Enable**.
3. Go to https://code.earthengine.google.com/register and register the
   project for Earth Engine access (choose **"Unpaid usage" / non-commercial**
   for a hackathon/demo — this is free). It may take a few minutes to a few
   hours for Google to approve a brand-new project; existing GCP projects
   with billing history often get approved instantly.

### B3. Create the service account

1. **IAM & Admin → Service Accounts** → **Create Service Account**.
2. Name it e.g. `hydris-ai` → **Create and Continue**.
3. Grant it the role **Earth Engine Resource Writer** (search "Earth Engine"
   in the role picker; if you don't see it, `Editor` also works for a demo
   but is broader than needed).
4. Click **Continue** → **Done**.

### B4. Generate the JSON key

1. Click on the service account you just created (from the list).
2. Go to the **Keys** tab → **Add Key** → **Create new key** → **JSON** → **Create**.
3. A `.json` file downloads automatically. **This file is a secret** — it
   contains a private key. Treat it exactly like a password.
4. Move it into this repo's `data/` folder, e.g.:
   ```
   data/hydris-demo-service-account.json
   ```
   (Any filename is fine — you'll point to it by path in `.env`. Just don't
   use the old filename `gen-lang-client-0226823786-...json` to avoid any
   confusion with the burned key.)

### B5. Register the service account for Earth Engine

Even after IAM setup, GEE needs the service account's email registered:

1. Note the service account's **email** (shown on its detail page, looks
   like `hydris-ai@hydris-demo-123456.iam.gserviceaccount.com`).
2. Go to https://code.earthengine.google.com/register (or the Earth Engine
   service account page linked from your GCP project's Earth Engine settings)
   and confirm the service account has access — for most GCP projects that
   already completed B2, service accounts under that project inherit access
   automatically once the project itself is EE-enabled. If you get a
   "not registered" error later when running the backend, this is the step
   to revisit.

GEE side is done. You now have:
- A GEE **Project ID** (from B1)
- A service-account **JSON key file** (from B4), placed in `data/`

---

## Part C — Wire it into the repo

### C1. Backend `.env`

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and fill in:

```ini
GEE_PROJECT=hydris-demo-123456              # your GCP Project ID from B1
GEE_SA_KEY_FILE=../data/hydris-demo-service-account.json   # path from B4

SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co       # from A2
SUPABASE_SERVICE_ROLE_KEY=eyJ...service-role...     # from A2 (the SECRET one)

GROQ_API_KEY=gsk_...                        # see note below
GROQ_MODEL=llama-3.3-70b-versatile

NEWS_API_KEY=...                            # see note below
```

**Groq key** (powers the LLM narratives/copilot): sign up free at
https://console.groq.com/keys → **Create API Key**.

**NewsAPI key** (powers the local news panel): sign up free at
https://newsapi.org/register → key is emailed/shown immediately. Note: the
free tier only works from `localhost`, per the README — fine for a local demo.

### C2. Frontend `.env`

```bash
cd ../frontend
cp .env.example .env
```

Open `frontend/.env` and fill in:

```ini
VITE_SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co   # same as backend, from A2
VITE_SUPABASE_ANON_KEY=eyJ...anon...                 # from A2 (the PUBLIC one — not service-role)
VITE_API_URL=http://127.0.0.1:8000
```

---

## Part D — Seed demo data and test

### D1. Install dependencies (if not already done)

```bash
cd backend
pip install -r requirements.txt
```

### D2. Seed the 5 pilot sites

The repo bundles `data/pilot_basins.geojson` and `data/drivers_demo.json`
from the original build, so you can seed your **new** Supabase without
needing GEE to be perfectly working yet:

```bash
cd backend
python seed.py --offline
```

This populates `sites` and `basins` in your new Supabase project from the
bundled files — no live GEE calls. Good first smoke test.

If your GEE service account is set up (Part B) and you want fully live data
instead of the bundled snapshot, run without `--offline`:

```bash
python seed.py
```

### D3. Start the backend

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Check:
```bash
curl http://127.0.0.1:8000/health
```
Expect `{"ok":true,"gee":true}`. If `"gee":false`, GEE init failed — the app
still works in Supabase-cache-only mode (fine for the 5 seeded pilot sites;
adding brand-new sites live needs GEE to be `true`). Check the terminal
output for the actual error.

### D4. Start the frontend

```bash
cd ../frontend
npm install
npm run dev
```

Open http://localhost:5173.

### D5. Smoke test checklist

- [ ] Map loads with colored basin polygons (proves Supabase read + anon key work)
- [ ] Click a pilot site pin → risk card shows scores (proves `risk_cache` seeded correctly)
- [ ] Sign up a new account → org gets created, you land on the dashboard
      (proves `organizations`/`user_profiles` tables + auth flow work)
- [ ] "Add a new factory" at a real-world coordinate → new pin appears live
      (proves GEE service account works end-to-end — skip if GEE isn't set up yet)
- [ ] `/health` returns `"gee":true` if you want the live-add feature working

---

## Quick troubleshooting

| Symptom | Likely cause |
|---|---|
| Map loads but shows no polygons | `schema.sql` not run, or seed.py not run yet |
| `"gee": false` in `/health` | GEE project not yet approved (B2), or `GEE_SA_KEY_FILE` path wrong in `.env` |
| Sign-up fails creating org/user | `schema_v2.sql` not run, or backend not restarted after editing `.env` |
| `SUPABASE_SERVICE_ROLE_KEY` errors on backend start | Wrong key pasted (double-check you used service_role, not anon, in `backend/.env`) |
| News panel empty when deployed (not localhost) | Expected — NewsAPI free tier is localhost-only |

Once you've run through this and confirmed the smoke test checklist, ping me
with any error output and I'll help debug it directly.
