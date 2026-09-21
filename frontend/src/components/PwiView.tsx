import { useEffect, useState } from "react";
import { fetchPwiDemo } from "../lib/data";
import PwiResult, { pwiColor } from "./PwiResult";
import PwiForm from "./PwiForm";
import PwiInterventions from "./PwiInterventions";

/* PS3 container: overview (portfolio rollup + saved assessments) → form → result.
 * Assessments persist in localStorage (no DB migration needed, nothing ingested). */

const LS_KEY = "hydris_pwi_v1";
type Saved = { id: string; name: string; result: any };

function certColor(result: string): string {
  if (result.startsWith("SELF-CERTIFIED")) return "#1a9850";
  if (result.startsWith("CONDITIONAL")) return "#66bd63";
  if (result.startsWith("IN PROGRESS")) return "#fed976";
  if (result.startsWith("NOT ACHIEVED")) return "#fc8d59";
  return "#d73027";
}

export default function PwiView({ selectedSite }: { selectedSite?: { name: string; lat: number; lng: number } | null }) {
  const [saved, setSaved] = useState<Saved[]>([]);
  const [mode, setMode] = useState<"overview" | "form" | "result">("overview");
  const [current, setCurrent] = useState<any | null>(null);

  useEffect(() => {
    try { setSaved(JSON.parse(localStorage.getItem(LS_KEY) || "[]")); } catch { /* ignore */ }
  }, []);

  const persist = (list: Saved[]) => { setSaved(list); localStorage.setItem(LS_KEY, JSON.stringify(list)); };

  const openDemo = async () => {
    const d = await fetchPwiDemo();
    if (d) { setCurrent(d); setMode("result"); }
  };
  const openResult = (r: any) => { setCurrent(r); setMode("result"); };
  const onFormDone = (result: any, meta: { name: string }) => {
    const entry: Saved = { id: result.site?.id || `PWI-${Date.now()}`, name: meta.name, result };
    persist([entry, ...saved.filter((s) => s.id !== entry.id)]);
    setCurrent(result); setMode("result");
  };
  const remove = (id: string) => persist(saved.filter((s) => s.id !== id));

  const scored = saved.filter((s) => s.result?.site_pwi?.value != null);
  const portfolio = scored.length ? scored.reduce((a, s) => a + s.result.site_pwi.value, 0) / scored.length : null;

  if (mode === "form")
    return <div className="pwi"><PwiForm initial={selectedSite ? { name: selectedSite.name, lat: selectedSite.lat, lng: selectedSite.lng } : null}
      onDone={onFormDone} onCancel={() => setMode("overview")} /></div>;

  if (mode === "result" && current)
    return <div className="pwi"><PwiResult data={current} onBack={() => setMode("overview")} /></div>;

  // overview
  return (
    <div className="pwi">
      <div className="pwi-inner">
        <div className="pwi-head">
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>Positive Water Impact</h1>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>WQBA/WRC methodology · quantify Availability, Quality & Access with confidence bands</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={openDemo} style={{ fontSize: 12 }}>View labeled demo</button>
            <button className="primary" onClick={() => setMode("form")} style={{ fontSize: 12 }}>New assessment</button>
          </div>
        </div>

        {/* portfolio rollup */}
        <div className="pwi-tiles">
          <div className="stat-tile">
            <div className="num" style={{ fontSize: 30, fontWeight: 700, color: portfolio == null ? "var(--faint)" : pwiColor(portfolio) }}>
              {portfolio == null ? "—" : `${portfolio.toFixed(1)}%`}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Portfolio PWI (Σ site ÷ n)</div>
          </div>
          <div className="stat-tile">
            <div className="num" style={{ fontSize: 30, fontWeight: 700 }}>{scored.length}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Assessed sites</div>
          </div>
          <div className="stat-tile">
            <div className="num" style={{ fontSize: 30, fontWeight: 700, color: "#5bd08a" }}>
              {scored.filter((s) => s.result.site_pwi.value >= 100).length}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Positive-impact (≥100%)</div>
          </div>
        </div>

        {/* saved assessments */}
        <div className="pwi-card">
          <div className="pwi-card-title">Your assessments</div>
          {saved.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--faint)", padding: "12px 0" }}>
              No assessments yet. Click <b>＋ New assessment</b> to enter a site's operational data and 52-question
              self-assessment for a live PWI, or <b>View labeled demo</b> to see a worked example first.
            </div>
          )}
          {saved.map((s) => {
            const v = s.result?.site_pwi?.value;
            const cert = s.result?.certification?.result ?? "";
            return (
              <div key={s.id} className="pwi-saved" onClick={() => openResult(s.result)}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{s.name}</div>
                  <div style={{ fontSize: 11, color: certColor(cert) }}>{cert}</div>
                </div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700, color: pwiColor(v), minWidth: 70, textAlign: "right" }}>
                  {v == null ? "n/d" : `${v.toFixed(1)}%`}
                </div>
                <button onClick={(e) => { e.stopPropagation(); remove(s.id); }} style={{ fontSize: 11, padding: "4px 9px" }}>✕</button>
              </div>
            );
          })}
        </div>

        {/* portfolio-wide AI intervention plan */}
        {scored.length > 0 && <PwiInterventions results={scored.map((s) => s.result)} scope="portfolio" />}

        <div style={{ fontSize: 10, color: "var(--faint)" }}>
          Portfolio PWI = Σ Site PWI ÷ #Sites (Baseline & Targets §C). Assessments are stored locally in your browser (not uploaded).
        </div>
      </div>
    </div>
  );
}
