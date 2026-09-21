# Security

This document records the security review of the Hydris AI repo, what was fixed,
and the actions **you** still need to take (key rotation cannot be done from code).

## 1. Exposed secrets — REMOVED from tracking, but you MUST rotate

The following files were committed with **live credentials**. They have been
untracked (`git rm --cached`) and added to `.gitignore`, and templated
`*.example` files remain so anyone can set up the project:

| File | Secret that was exposed |
|------|-------------------------|
| `backend/.env` | Supabase **service-role** key, `GROQ_API_KEY`, `NEWS_API_KEY` |
| `frontend/.env` | Supabase anon key (public-by-design, but still committed) |
| `data/gen-lang-client-*.json` | Google Earth Engine **service-account private key** |

> ⚠️ **These keys are already in git history and were pushed to GitHub, so they
> are compromised.** Untracking them does not undo that. You must:
>
> 1. **Rotate every key:**
>    - Groq: revoke `GROQ_API_KEY` and issue a new one.
>    - Supabase: rotate the **service-role** and **anon** keys (Project Settings → API).
>    - NewsAPI: regenerate the API key.
>    - GEE: delete the service-account key in Google Cloud IAM and issue a new JSON.
>      (Google auto-scans public GitHub and disables leaked SA keys within minutes.)
> 2. **Purge the keys from git history** before making the repo public:
>    ```bash
>    pip install git-filter-repo
>    git filter-repo --path backend/.env --path frontend/.env \
>      --path data/gen-lang-client-0226823786-9b6a51eea7a6.json --invert-paths
>    ```
>    Then force-push and have all collaborators re-clone.
> 3. Put the **new** values only in your local (git-ignored) `.env` files.

## 2. Broken access control — FIXED

The FastAPI worker holds the Supabase service-role key, which **bypasses Row
Level Security**. Several endpoints used it with **no authentication**, allowing:

- **Privilege escalation:** anyone could `POST /users` with `role: "admin"` to
  make any account an admin of any organization.
- **Tenant enumeration:** anyone could read every organization, user profile,
  and site via `GET /organizations`, `GET /users/{org_id}`, `GET /sites`.
- **Unauthenticated writes:** anyone could `POST /organizations`.

**Fix** (`backend/auth.py` + `backend/main.py`): every service-role endpoint now
verifies the caller's Supabase access token (JWT) via GoTrue and enforces org
scoping:

- `POST /organizations`, `GET /organizations`, `POST /users`, `GET /users/{org_id}`
  now require a valid bearer token.
- `GET /organizations` returns only the caller's org; `GET /users/{org_id}`
  requires membership.
- `POST /users` lets you create only **your own** profile into a **fresh** org
  (first user becomes admin), or add teammates only if you are that org's admin.
- `GET /sites` returns org-less public/demo sites to everyone (the guest demo
  still works) but private sites only to their org's members. New sites created
  by a signed-in user are stamped with that user's `org_id`.

The frontend (`LoginView.tsx`, `lib/data.ts`) now attaches
`Authorization: Bearer <token>` on these calls.

## 3. CORS — HARDENED

The API previously defaulted to `allow_origins=["*"]` with all methods/headers.
The default is now the local dev origins (`http://localhost:5173`,
`http://127.0.0.1:5173`), methods limited to `GET`/`POST`, and headers to
`Authorization`/`Content-Type`. Set `ALLOWED_ORIGINS` (comma-separated) to your
deployed frontend URL in production. Do **not** set it back to `*`.

## 4. Dependencies

- `vite` resolves to **5.4.21** in `frontend/package-lock.json` — already patched
  for the known dev-server advisories. Keep it up to date with `npm audit`.
- Backend: no known-vulnerable pins found. Run `pip-audit` periodically.

## 5. Residual notes / future work

- `POST /sites` still accepts anonymous (guest) creation of public sites by
  design, so the live "add a factory" demo works without login. If you don't
  need the guest add flow, require auth there too.
- There is no rate limiting on the compute/LLM endpoints — add one (e.g.
  `slowapi`) before any public deployment to limit abuse and API-cost blowups.

## Reporting

Found a vulnerability? Open a private security advisory on the GitHub repo rather
than a public issue.
