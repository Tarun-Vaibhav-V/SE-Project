import { useEffect, useMemo, useState } from "react";
import { fetchPwiInstrument, computePwiSite } from "../lib/data";

/* PS3 factory-input flow: Section A operational data + the 52-question self-assessment.
 * Submitting computes a REAL (non-demo) PWI via POST /pwi/site. Kept practical with a
 * quick-fill bar and an example prefill so it is usable in a live demo. */

type Ans = { score: number; evidence: "Yes" | "Partial" | "No" };
const evForScore = (s: number): Ans["evidence"] => (s >= 2 ? "Yes" : s === 1 ? "Partial" : "No");
const PILLAR_LABEL: Record<string, string> = { P1: "Site", P2: "Sub-Basin", P3: "Basin" };

interface Props {
  initial?: { name?: string; lat?: number; lng?: number; industry?: string } | null;
  onDone: (result: any, meta: { name: string }) => void;
  onCancel: () => void;
}

const OP_FIELDS: { key: string; label: string; unit: string }[] = [
  { key: "annual_withdrawal_m3", label: "Annual withdrawal", unit: "m³/yr" },
  { key: "water_recycled_m3", label: "Water recycled", unit: "m³/yr" },
  { key: "water_reused_m3", label: "Water reused", unit: "m³/yr" },
  { key: "wastewater_generated_m3", label: "Wastewater generated", unit: "m³/yr" },
  { key: "wastewater_treated_m3", label: "Wastewater treated", unit: "m³/yr" },
  { key: "employees", label: "Employees", unit: "people" },
  { key: "toilets", label: "Toilets", unit: "count" },
  { key: "washbasins", label: "Washbasins", unit: "count" },
];

export default function PwiForm({ initial, onDone, onCancel }: Props) {
  const [instrument, setInstrument] = useState<any | null>(null);
  const [name, setName] = useState(initial?.name ?? "");
  const [industry, setIndustry] = useState(initial?.industry ?? "Textile");
  const [lat, setLat] = useState(initial?.lat != null ? String(initial.lat) : "");
  const [lng, setLng] = useState(initial?.lng != null ? String(initial.lng) : "");
  const [op, setOp] = useState<Record<string, string>>({});
  const [benefits, setBenefits] = useState("");   // comma list of m³/yr
  const [safeDW, setSafeDW] = useState(true);
  const [ans, setAns] = useState<Record<number, Ans>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { fetchPwiInstrument().then(setInstrument); }, []);

  // group the 52 questions by pillar -> dimension
  const groups = useMemo(() => {
    const g: Record<string, Record<string, any[]>> = {};
    (instrument?.questions ?? []).forEach((q: any) => {
      (g[q.pillar] ??= {})[q.dimension] ??= [];
      g[q.pillar][q.dimension].push(q);
    });
    return g;
  }, [instrument]);

  const setScore = (id: number, score: number) =>
    setAns((a) => ({ ...a, [id]: { score, evidence: a[id]?.score === score ? a[id].evidence : evForScore(score) } }));
  const setEvidence = (id: number, evidence: Ans["evidence"]) =>
    setAns((a) => ({ ...a, [id]: { score: a[id]?.score ?? 0, evidence } }));
  const quickFill = (score: number) => {
    const next: Record<number, Ans> = {};
    (instrument?.questions ?? []).forEach((q: any) => (next[q.id] = { score, evidence: evForScore(score) }));
    setAns(next);
  };

  const prefillExample = () => {
    setName((n) => n || "Chennai plant (IN)"); setIndustry("Textile");
    setLat((v) => v || "13.0827"); setLng((v) => v || "80.2707");
    setOp({ annual_withdrawal_m3: "520000", water_recycled_m3: "60000", water_reused_m3: "25000",
      wastewater_generated_m3: "300000", wastewater_treated_m3: "285000",
      employees: "1800", toilets: "90", washbasins: "320" });
    setBenefits("60000, 18000, 45000");
    // site mature, sub-basin partial, basin early
    const pat: Record<string, number> = { P1: 2, P2: 1, P3: 1 };
    const next: Record<number, Ans> = {};
    (instrument?.questions ?? []).forEach((q: any) => {
      const s = pat[q.pillar]; next[q.id] = { score: s, evidence: evForScore(s) };
    });
    setAns(next);
  };

  const answered = Object.keys(ans).length;

  const submit = async () => {
    setErr(null);
    if (!name.trim()) return setErr("Site name is required");
    const la = parseFloat(lat), ln = parseFloat(lng);
    if (Number.isNaN(la) || Number.isNaN(ln)) return setErr("Valid lat/lng required (for live basin context)");
    if (answered === 0) return setErr("Answer the self-assessment (or use Quick-fill / Prefill example)");
    const num = (k: string) => (op[k] === undefined || op[k] === "" ? undefined : Number(op[k]));
    const site = {
      id: `PWI-${Date.now().toString(36)}`,
      name: name.trim(), company: "—", industry, lat: la, lng: ln,
      data_grade: "user-entered",
      self_assessment: Object.fromEntries((instrument?.questions ?? []).map((q: any) =>
        [String(q.id), ans[q.id] ?? { score: 0, evidence: "No" }])),
      operational: {
        annual_withdrawal_m3: num("annual_withdrawal_m3"),
        water_recycled_m3: num("water_recycled_m3"),
        water_reused_m3: num("water_reused_m3"),
        wastewater_generated_m3: num("wastewater_generated_m3"),
        wastewater_treated_m3: num("wastewater_treated_m3"),
        employees: num("employees"), toilets: num("toilets"), washbasins: num("washbasins"),
        safe_drinking_water: safeDW,
        intervention_benefits_m3: benefits.split(",").map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n) && n > 0),
      },
    };
    setBusy(true);
    try {
      const result = await computePwiSite(site);
      onDone(result, { name: site.name });
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally { setBusy(false); }
  };

  if (!instrument) return <div className="pwi-inner" style={{ color: "var(--muted)" }}>Loading assessment instrument…</div>;

  return (
    <div className="pwi-inner">
      <div className="pwi-head">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={onCancel} style={{ fontSize: 12, padding: "5px 12px" }}>← Cancel</button>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>New PWI assessment</h1>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>Section A operational data + 52-question self-assessment → live PWI</div>
          </div>
        </div>
        <button onClick={prefillExample} style={{ fontSize: 11 }}>⚡ Prefill example</button>
      </div>

      {/* identity + operational */}
      <div className="pwi-card">
        <div className="pwi-card-title">Site & operational data (Section A)</div>
        <div className="pwi-form-grid">
          <label>Site name<input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Chennai plant" /></label>
          <label>Industry<input type="text" value={industry} onChange={(e) => setIndustry(e.target.value)} /></label>
          <label>Latitude<input type="text" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="13.0827" /></label>
          <label>Longitude<input type="text" value={lng} onChange={(e) => setLng(e.target.value)} placeholder="80.2707" /></label>
          {OP_FIELDS.map((f) => (
            <label key={f.key}>{f.label} <span style={{ color: "var(--faint)" }}>({f.unit})</span>
              <input type="text" inputMode="numeric" value={op[f.key] ?? ""} onChange={(e) => setOp({ ...op, [f.key]: e.target.value })} />
            </label>
          ))}
          <label>Intervention benefits <span style={{ color: "var(--faint)" }}>(m³/yr, comma-sep)</span>
            <input type="text" value={benefits} onChange={(e) => setBenefits(e.target.value)} placeholder="60000, 18000, 45000" />
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={safeDW} onChange={(e) => setSafeDW(e.target.checked)} style={{ width: "auto" }} />
            Safe drinking water provided
          </label>
        </div>
        <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 8 }}>
          Operational numbers are owner-supplied (no public source). Lat/lng also fetches live World Bank basin context.
        </div>
      </div>

      {/* 52 questions */}
      <div className="pwi-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
          <span className="pwi-card-title" style={{ margin: 0 }}>Self-assessment · {answered}/52 answered</span>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <span style={{ color: "var(--muted)" }}>Quick-fill all:</span>
            {[0, 1, 2, 3].map((s) => <button key={s} onClick={() => quickFill(s)} style={{ padding: "4px 9px", fontSize: 11 }}>{s}</button>)}
          </div>
        </div>
        {["P1", "P2", "P3"].map((p) => (
          <div key={p} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--accent)", margin: "6px 0" }}>{p} · {PILLAR_LABEL[p]}</div>
            {["Availability", "Quality", "Access"].map((d) => (
              <div key={d} style={{ marginBottom: 6 }}>
                <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", margin: "4px 0" }}>{d}</div>
                {(groups[p]?.[d] ?? []).map((q: any) => (
                  <div key={q.id} className="pwi-q">
                    <span className="pwi-q-title">{q.id}. {q.title}</span>
                    <div className="pwi-q-scores">
                      {[0, 1, 2, 3].map((s) => (
                        <button key={s} onClick={() => setScore(q.id, s)}
                          className={ans[q.id]?.score === s ? "on" : ""}>{s}</button>
                      ))}
                    </div>
                    <select value={ans[q.id]?.evidence ?? "No"} onChange={(e) => setEvidence(q.id, e.target.value as any)}>
                      <option>Yes</option><option>Partial</option><option>No</option>
                    </select>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ))}
        <div style={{ fontSize: 10, color: "var(--faint)" }}>Score: 0=not done · 1=partial/planned · 2=implemented · 3=fully implemented & verified. Evidence sets per-question confidence (Yes 100 / Partial 70 / No 50).</div>
      </div>

      {err && <div style={{ color: "var(--risk-3)", fontSize: 12, marginBottom: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="primary" onClick={submit} disabled={busy}>{busy ? "Computing PWI…" : "Compute PWI"}</button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
