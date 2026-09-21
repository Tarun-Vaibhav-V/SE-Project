/* Data layer: Supabase-first (public anon reads), bundled demo data as offline
 * fallback, FastAPI GEE service only for uncached computation.
 * Numbers are never invented: missing values stay null and render as "no data". */
import { createClient, SupabaseClient } from "@supabase/supabase-js";
import demoBasins from "../demo/pilot_basins.json";
import demoDrivers from "../demo/drivers_demo.json";

const SUPA_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const SUPA_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
export const API_URL = (import.meta.env.VITE_API_URL as string) || "http://127.0.0.1:8000";

export const supa: SupabaseClient | null =
  SUPA_URL && SUPA_KEY ? createClient(SUPA_URL, SUPA_KEY) : null;

/** Authorization header for the FastAPI service when a user is signed in.
 * Returns {} for guests, so public endpoints keep working unauthenticated. */
export async function authHeader(): Promise<Record<string, string>> {
  if (!supa) return {};
  const { data } = await supa.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface Site {
  id: string;
  name: string;
  lat: number;
  lng: number;
  pfaf_id: number | null;
}

export interface BasinFeature {
  type: "Feature";
  geometry: any;
  properties: Record<string, any>; // normalized: bws,bwd,gtd,drr,rfr,cfr,ucw,wash,flood,overall,pfaf_id
}

const clean = (v: any) => (v === -9999 || v === "-9999" || v === undefined ? null : v);

/** GEE simplify() can degrade basin Polygons into GeometryCollections of
 * LineStrings, which fill layers silently ignore — rebuild Polygon/MultiPolygon. */
function normalizeGeometry(geom: any): any {
  const t = geom?.type;
  if (t === "Polygon" || t === "MultiPolygon") return geom;
  const ringOf = (line: any[]): any[] | null => {
    if (!line || line.length < 4) return null;
    const c = [...line];
    const [f, l] = [c[0], c[c.length - 1]];
    if (f[0] !== l[0] || f[1] !== l[1]) c.push(f);
    return c.length >= 4 ? c : null;
  };
  if (t === "LineString") {
    const r = ringOf(geom.coordinates);
    return r ? { type: "Polygon", coordinates: [r] } : geom;
  }
  if (t === "GeometryCollection") {
    const parts: any[] = [];
    for (const g of geom.geometries ?? []) {
      if (g.type === "Polygon") parts.push(g.coordinates);
      else if (g.type === "MultiPolygon") parts.push(...g.coordinates);
      else if (g.type === "LineString") {
        const r = ringOf(g.coordinates);
        if (r) parts.push([r]);
      }
    }
    if (parts.length === 1) return { type: "Polygon", coordinates: parts[0] };
    if (parts.length) return { type: "MultiPolygon", coordinates: parts };
  }
  return geom;
}

/** Normalize raw Aqueduct-ish props into the layer-selector vocabulary. */
function normalizeProps(p: Record<string, any>): Record<string, any> {
  const g = (k: string) => clean(p[`${k}_score`] ?? p[k]);
  const rfr = g("rfr");
  const cfr = g("cfr");
  const udw = g("udw");
  const usa = g("usa");
  return {
    pfaf_id: p.pfaf_id ?? null,
    bws: g("bws"),
    bwd: g("bwd"),
    gtd: g("gtd"),
    drr: g("drr"),
    rfr,
    cfr,
    ucw: g("ucw"),
    flood: rfr === null && cfr === null ? null : Math.max(rfr ?? -1, cfr ?? -1),
    wash: udw === null && usa === null ? null : ((udw ?? usa ?? 0) + (usa ?? udw ?? 0)) / 2,
    overall: clean(p.w_awr_def_tot_score ?? p.overall),
    overall_cat: p.w_awr_def_tot_cat ?? p.overall_cat ?? null,
    site_id: p.site_id ?? null,
    name: p.name ?? null,
  };
}

const IND_CODES = ["bws","bwd","iav","sev","gtd","rfr","cfr","drr","ucw","cep","udw","usa","rri"];

export async function loadBasins(): Promise<BasinFeature[]> {
  if (supa) {
    const [{ data }, { data: rc }] = await Promise.all([
      supa.from("basins").select("pfaf_id, geom_geojson, props"),
      supa.from("risk_cache").select("pfaf_id, profile"),
    ]);
    if (data && data.length) {
      // basins.props hold only the pilot KEEP subset; risk_cache.profile has all
      // 13 indicators — merge so every layer (incl. Quality ucw / WASH udw+usa)
      // colors from real scores instead of showing no-data.
      const prof = new Map((rc ?? []).map((r: any) => [r.pfaf_id, r.profile]));
      return data.map((r: any) => {
        const merged: Record<string, any> = { ...(r.props || {}) };
        const p = prof.get(r.pfaf_id);
        if (p) {
          for (const c of IND_CODES) {
            const s = p[c]?.score;
            if (s !== undefined && s !== null) merged[`${c}_score`] = s;
          }
          if (p.overall_gee != null) merged.w_awr_def_tot_score = p.overall_gee;
        }
        return {
          type: "Feature" as const,
          geometry: normalizeGeometry(r.geom_geojson),
          properties: { ...normalizeProps(merged), pfaf_id: r.pfaf_id },
        };
      });
    }
  }
  return (demoBasins as any).features.map((f: any) => ({
    type: "Feature",
    geometry: normalizeGeometry(f.geometry),
    properties: normalizeProps(f.properties || {}),
  }));
}

export async function loadSites(): Promise<Site[]> {
  if (supa) {
    const { data } = await supa.from("sites").select("*");
    if (data && data.length) return data as Site[];
  }
  // schema_v2's org-isolation RLS can blank the anon read (sites.org_id is not
  // backfilled yet) — fall back to the compute API's service-role listing.
  try {
    const r = await fetch(`${API_URL}/sites`, { headers: { ...(await authHeader()) } });
    if (r.ok) {
      const rows = await r.json();
      if (Array.isArray(rows) && rows.length) return rows as Site[];
    }
  } catch { /* API down — bundled demo data below */ }
  return (demoBasins as any).features
    .filter((f: any) => f.properties?.site_id)
    .map((f: any) => ({
      id: f.properties.site_id,
      name: f.properties.name,
      lat: f.properties.lat,
      lng: f.properties.lng,
      pfaf_id: f.properties.pfaf_id ?? null,
    }));
}

/** Full cached profile+PWI for a basin; null means "not cached — partial mode". */
export async function getRiskCache(pfaf_id: number | null): Promise<any | null> {
  if (!supa || pfaf_id === null) return null;
  const { data } = await supa.from("risk_cache").select("*").eq("pfaf_id", pfaf_id);
  return data?.[0] ?? null;
}

/** All cached futures keyed by basin (pfaf_id -> {bau30, bau50, ...}). Used by the
 * portfolio table's 2050 column. Empty map if Supabase is unreachable. */
export async function loadFutures(): Promise<Record<number, any>> {
  if (supa) {
    const { data } = await supa.from("risk_cache").select("pfaf_id, future");
    if (data) return Object.fromEntries(data.filter((r: any) => r.future).map((r: any) => [r.pfaf_id, r.future]));
  }
  return {};
}

export async function getDrivers(siteId: string, risk: string, lat: number, lng: number): Promise<any | null> {
  if (supa) {
    const { data } = await supa
      .from("driver_cache")
      .select("drivers")
      .eq("site_id", siteId)
      .eq("risk", risk);
    if (data?.[0]?.drivers) return data[0].drivers;
  }
  const demo = (demoDrivers as any)[siteId]?.[risk];
  if (demo) return demo;
  try {
    const r = await fetch(`${API_URL}/drivers?risk=${risk}&lat=${lat}&lng=${lng}&site_id=${siteId}`);
    if (r.ok) return await r.json();
  } catch { /* API down — honest null */ }
  return null;
}

export async function getFuture(pfaf_id: number, year: number, scenario: string): Promise<any | null> {
  const cached = await getRiskCache(pfaf_id);
  const key = `${scenario}${year}`;
  if (cached?.future?.[key]) return cached.future[key];
  try {
    const r = await fetch(`${API_URL}/future?pfaf_id=${pfaf_id}&year=${year}&scenario=${scenario}`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** Grounded narrative. Server enforces numeral validation; local fallback is a
 * deterministic template over the same JSON (no invented numbers). */
export async function explain(risk: string, drivers: any): Promise<{ narrative: string; engine: string }> {
  try {
    const r = await fetch(`${API_URL}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ risk, drivers }),
    });
    if (r.ok) return await r.json();
  } catch { /* fall through to local template */ }
  const att: Record<string, number> = drivers?.attribution_pct ?? {};
  const top = Object.entries(att).sort((a, b) => b[1] - a[1]).slice(0, 3);
  if (!top.length) return { narrative: `No ${risk} drivers computed for this site.`, engine: "template" };
  const parts = top.map(([k, v]) => `${k.replace(/_/g, " ")} (${v}%)`).join(", ");
  return {
    narrative: `The modelled ${risk} hazard is ${drivers.hazard_0_5} out of 5. Largest estimated contributions to the modelled score: ${parts}.`,
    engine: "template",
  };
}

export async function reweight(lat: number, lng: number, ind_weights: Record<string, number>): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/reweight`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lng, ind_weights }),
    });
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** Factory input end-to-end: POST /sites resolves basin, caches profile+PWI+futures,
 * stores the basin polygon and persists the site. */
export async function addSite(s: { name: string; id?: string; lat: number; lng: number }): Promise<any> {
  const r = await fetch(`${API_URL}/sites`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeader()) },
    body: JSON.stringify(s),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}

/** Local news clippings for the site's highest risk, sentiment+gov tagged server-side. */
export async function fetchNews(lat: number, lng: number, pfaf_id: number | null): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/news?lat=${lat}&lng=${lng}${pfaf_id != null ? `&pfaf_id=${pfaf_id}` : ""}`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** HydroSHEDS level-9 sub-basins around a site, scored from their Aqueduct basin. */
export async function fetchSubbasins(lat: number, lng: number): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/subbasins?lat=${lat}&lng=${lng}`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** PS3 PWI engine — the labeled ASSUMED-DEMO result (Chennai). Real sites need a
 * 52-question self-assessment posted to /pwi/site. Null if the API is unreachable. */
export async function fetchPwiDemo(): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/pwi/demo`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** PS5 Evidence & Disclosure Agent — labeled SYNTHETIC demo run. */
export async function fetchEvidenceDemo(): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/evidence/demo`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** Analyze supplied document text through the evidence pipeline (classify→map→gap→verify→draft). */
export async function analyzeEvidence(documents: { name: string; text: string }[], site?: any, persist = false): Promise<any> {
  const r = await fetch(`${API_URL}/evidence/analyze`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ documents, site, persist }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}

/** Multi-file upload (PDF/xlsx/txt). Server extracts text, runs verify+disclosure, optionally saves to Supabase. */
export async function uploadEvidence(
  files: File[],
  site?: { id?: string; name?: string; lat?: number; lng?: number; pfaf_id?: number },
  persist = false,
): Promise<any> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  if (site?.id) fd.append("site_id", site.id);
  if (site?.name) fd.append("name", site.name);
  if (site?.lat != null) fd.append("lat", String(site.lat));
  if (site?.lng != null) fd.append("lng", String(site.lng));
  if (site?.pfaf_id != null) fd.append("pfaf_id", String(site.pfaf_id));
  fd.append("persist", String(persist));
  const r = await fetch(`${API_URL}/evidence/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}

/** LLM intervention planner — reads computed PWI results (gaps + live basin context)
 * and returns prioritized interventions with duration/benefit/cost/phase + roadmap. */
export async function pwiRecommend(results: any[]): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/pwi/recommend`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results }),
    });
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** PWI Chat Advisor — converse with LLM about site/portfolio gaps, roadmap and scores. */
export async function pwiChat(message: string, history: { role: string; content: string }[], results: any[]): Promise<string> {
  try {
    const r = await fetch(`${API_URL}/pwi/chat`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, results }),
    });
    if (r.ok) {
      const data = await r.json();
      return data.answer;
    }
  } catch { /* API down */ }
  return "Could not connect to the Hydris PWI Advisor. Please check if the FastAPI backend service is running.";
}


/** The 52-question instrument + 3×3 matrix definition (drives the assessment form). */
export async function fetchPwiInstrument(): Promise<any | null> {
  try {
    const r = await fetch(`${API_URL}/pwi/instrument`);
    if (r.ok) return await r.json();
  } catch { /* API down */ }
  return null;
}

/** Compute a real (non-demo) PWI profile from supplied factory inputs + 52-Q self-assessment. */
export async function computePwiSite(site: any): Promise<any> {
  const r = await fetch(`${API_URL}/pwi/site`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ site }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}

export async function geocode(q: string): Promise<{ lat: number; lng: number; label: string } | null> {
  try {
    const r = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`,
      { headers: { Accept: "application/json" } }
    );
    const j = await r.json();
    if (j?.[0]) return { lat: +j[0].lat, lng: +j[0].lon, label: j[0].display_name };
  } catch { /* offline */ }
  return null;
}

export async function sendChatMessage(message: string, history: Array<{ role: string; content: string }>): Promise<any> {
  const r = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}


/* ── Intervention Intelligence Engine (HIIE) ────────────────────────────── */

export type SiteParams = {
  roof_area_m2?: number;
  annual_rainfall_mm?: number;
  withdrawal_m3_yr?: number;
  effluent_m3_yr?: number;
  catchment_area_m2?: number;
};

async function postHIIE(path: string, body: any): Promise<any> {
  const r = await fetch(`${API_URL}/intervention/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `HTTP ${r.status}`);
  return await r.json();
}

export async function interventionCatalog(): Promise<any> {
  const r = await fetch(`${API_URL}/intervention/catalog`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

export async function simulateInterventions(
  site: { site_id?: string; lat: number; lng: number },
  portfolio: Record<string, number>,
  site_params: SiteParams
): Promise<any> {
  return postHIIE("simulate", { ...site, portfolio, site_params });
}

export async function optimizeInterventions(
  site: { site_id?: string; lat: number; lng: number },
  goal: string,
  intensity: number,
  site_params: SiteParams,
  budget_lakh_inr?: number | null
): Promise<any> {
  return postHIIE("optimize", { ...site, goal, intensity, site_params, budget_lakh_inr });
}

export async function riskBudget(
  site: { site_id?: string; lat: number; lng: number },
  max_acceptable_0_5: number,
  intensity: number,
  site_params: SiteParams
): Promise<any> {
  return postHIIE("budget", { ...site, max_acceptable_0_5, intensity, site_params });
}

export async function evidenceGraph(
  site: { site_id?: string; lat: number; lng: number },
  intervention_id: string,
  intensity: number
): Promise<any> {
  const q = new URLSearchParams({
    lat: String(site.lat), lng: String(site.lng),
    intervention_id, intensity: String(intensity),
  });
  if (site.site_id) q.set("site_id", site.site_id);
  const r = await fetch(`${API_URL}/intervention/evidence?${q}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

export async function confidenceReport(
  site: { site_id?: string; lat: number; lng: number }
): Promise<any> {
  const q = new URLSearchParams({ lat: String(site.lat), lng: String(site.lng) });
  if (site.site_id) q.set("site_id", site.site_id);
  const r = await fetch(`${API_URL}/intervention/confidence?${q}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}
