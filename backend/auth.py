"""Server-side authentication for the write/admin endpoints.

The compute worker holds the Supabase *service-role* key, which bypasses Row
Level Security. Any endpoint that uses it MUST authenticate the caller here
first, otherwise the whole database is world-writable. We verify the caller's
Supabase access token (JWT) against GoTrue via the same client — no extra
secret or dependency required.
"""
from functools import lru_cache

from fastapi import Header, HTTPException

import supa


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _verify(token: str) -> dict:
    """Validate a Supabase access token; return {id, email} or raise 401."""
    try:
        resp = supa.client().auth.get_user(token)
    except Exception:
        raise HTTPException(401, "invalid or expired session")
    user = getattr(resp, "user", None)
    if not user or not getattr(user, "id", None):
        raise HTTPException(401, "invalid or expired session")
    return {"id": str(user.id), "email": getattr(user, "email", None)}


def require_user(authorization: str | None = Header(None)) -> dict:
    """FastAPI dependency: reject the request unless a valid token is present."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(401, "authentication required (send Authorization: Bearer <token>)")
    return _verify(token)


def optional_user(authorization: str | None = Header(None)) -> dict | None:
    """FastAPI dependency: return the caller if a valid token is present, else None.
    Used for reads that expose public rows to everyone but private rows only to
    their owning org (e.g. the portfolio list, which the guest demo also reads)."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        return _verify(token)
    except HTTPException:
        return None


def profile_for(user_id: str) -> dict | None:
    """The user_profiles row (org_id, role) for a verified user id, or None."""
    res = supa.client().table("user_profiles").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None
