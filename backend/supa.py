"""Supabase cache layer — all state lives in Supabase (user decision).
Frontend reads these tables directly via supabase-js; this module is the
service-role write path used by the FastAPI compute worker.
"""
import os
from functools import lru_cache

from supabase import create_client


@lru_cache(maxsize=1)
def client():
    return create_client(os.environ["SUPABASE_URL"],
                         os.environ["SUPABASE_SERVICE_ROLE_KEY"])


# ---- risk_cache (keyed by basin) ----

def get_risk_cache(pfaf_id):
    res = client().table("risk_cache").select("*").eq("pfaf_id", pfaf_id).execute()
    return res.data[0] if res.data else None


def upsert_risk_cache(pfaf_id, profile=None, future=None, pwi=None):
    row = get_risk_cache(pfaf_id) or {"pfaf_id": pfaf_id}
    if profile is not None:
        row["profile"] = profile
    if future is not None:
        merged = row.get("future") or {}
        merged.update(future)
        row["future"] = merged
    if pwi is not None:
        row["pwi"] = pwi
    row.pop("updated_at", None)
    client().table("risk_cache").upsert(row).execute()
    return row


# ---- driver_cache (keyed by site + risk) ----

def get_driver_cache(site_id, risk):
    res = (client().table("driver_cache").select("drivers")
           .eq("site_id", site_id).eq("risk", risk).execute())
    return res.data[0]["drivers"] if res.data else None


def upsert_driver_cache(site_id, risk, drivers):
    client().table("driver_cache").upsert(
        {"site_id": site_id, "risk": risk, "drivers": drivers}).execute()


# ---- sites / basins ----

def list_sites():
    return client().table("sites").select("*").execute().data


def upsert_site(site):
    client().table("sites").upsert(site).execute()


def upsert_basin(pfaf_id, geom_geojson, props):
    client().table("basins").upsert(
        {"pfaf_id": pfaf_id, "geom_geojson": geom_geojson, "props": props}).execute()


# ---- PS5 evidence & disclosure (evidence_documents / evidence_claims / evidence_reports) ----

def save_evidence(site: dict, result: dict):
    """Persist a full evidence-pipeline run for a site: documents, verified claims,
    and the disclosure rollup. Replaces the site's prior evidence rows (idempotent)."""
    c = client()
    site_id = site.get("id")
    if not site_id:
        raise ValueError("site.id required to persist evidence")

    # ensure the site row exists (FK target)
    c.table("sites").upsert({k: site.get(k) for k in ("id", "name", "lat", "lng", "pfaf_id")
                             if site.get(k) is not None}).execute()

    # clear prior evidence for this site (cascade removes claims)
    c.table("evidence_documents").delete().eq("site_id", site_id).execute()

    doc_id_by_name = {}
    for a in result.get("artefacts", []):
        row = c.table("evidence_documents").insert({
            "site_id": site_id, "name": a.get("name"), "doc_type": a.get("type"),
            "metadata": {k: a.get(k) for k in ("issuing_authority", "doc_date", "validity_end",
                                               "parameters", "volumes_m3_yr", "accredited",
                                               "monitoring_frequency", "citation_quote")},
            "confidence": a.get("type_confidence"),
        }).execute()
        doc_id_by_name[a.get("name")] = row.data[0]["id"] if row.data else None

    claim_rows = []
    for cl in result.get("claims", []):
        claim_rows.append({
            "document_id": doc_id_by_name.get(cl.get("document")),
            "site_id": site_id, "intervention": cl.get("intervention"),
            "formula": cl.get("formula"), "formula_soundness": cl.get("formula_soundness"),
            "claimed_value": cl.get("claimed_value"), "claimed_unit": cl.get("claimed_unit"),
            "recomputed_value": cl.get("recomputed_value"), "deviation_pct": cl.get("deviation_pct"),
            "threshold_pct": cl.get("threshold_pct"), "verified": cl.get("verified"),
            "grade": cl.get("grade"), "confidence_pct": cl.get("confidence_pct"),
            "factors": {"confidence_factors": cl.get("confidence_factors"),
                        "inputs_used": cl.get("inputs_used"), "rainfall_source": cl.get("rainfall_source"),
                        "status": cl.get("status")},
        })
    if claim_rows:
        c.table("evidence_claims").insert(claim_rows).execute()

    g = result.get("grading", {})
    c.table("evidence_reports").upsert({
        "site_id": site_id, "cdp_grade": g.get("cdp_grade"),
        "coverage_pct": result["summary"]["coverage_pct"], "verified_pct": g.get("verified_pct"),
        "gaps": result.get("gaps"), "draft": result.get("draft"),
    }).execute()


def get_evidence_report(site_id):
    res = client().table("evidence_reports").select("*").eq("site_id", site_id).execute()
    return res.data[0] if res.data else None
