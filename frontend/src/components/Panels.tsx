import { useEffect, useRef, useState } from "react";
import { LAYERS, RISK_COLORS, NO_DATA_COLOR, classify } from "../lib/risk";
import { geocode, getFuture, reweight } from "../lib/data";
import type { Site } from "../lib/data";

/* ---------- Top nav (56px, full-width header with embedded search) ---------- */
export function TopNav({ view, onView, onGo, onSignOut }: {
  view: "map" | "portfolio" | "pwi" | "copilot" | "evidence" | "twin";
  onView: (v: "map" | "portfolio" | "pwi" | "copilot" | "evidence" | "twin") => void;
  onGo?: (p: { lat: number; lng: number; label: string }) => void;
  onSignOut?: () => void;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const go = async () => {
    if (!q.trim() || !onGo) return;
    setBusy(true); setNotFound(false);
    const hit = await geocode(q);
    setBusy(false);
    if (hit) onGo(hit);
    else { setNotFound(true); setTimeout(() => setNotFound(false), 2500); }
  };

  return (
    <div className="topnav glass">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
        <b>Hydris Basin</b>
        <span style={{ color: "var(--faint)", fontSize: 11 }}>Water Risk Command Center</span>
      </div>
      <div className="view-toggle">
        <button className={view === "map" ? "on" : ""} onClick={() => onView("map")}>Map</button>
        <button className={view === "portfolio" ? "on" : ""} onClick={() => onView("portfolio")}>Basin Scores</button>
        <button className={view === "pwi" ? "on" : ""} onClick={() => onView("pwi")}>PWI</button>
        <button className={view === "evidence" ? "on" : ""} onClick={() => onView("evidence")}>Evidence</button>
        <button className={view === "twin" ? "on" : ""} onClick={() => onView("twin")}>What-If Lab</button>
        <button className={view === "copilot" ? "on" : ""} onClick={() => onView("copilot")}>Copilot</button>
      </div>
      {view === "map" && onGo && (
        <div className="header-search">
          <input type="text" placeholder={notFound ? "Location not found — try again" : "Search location…"}
            value={q} aria-label="Search location"
            style={notFound ? { borderColor: "var(--risk-3)" } : undefined}
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} />
          <button className="primary" onClick={go} disabled={busy}>
            {busy ? "…" : "Go"}
          </button>
        </div>
      )}
      <span className="nav-attn" style={{ fontSize: 10, color: "var(--faint)" }}>
        Data: WRI Aqueduct 4.0 · CC-BY 4.0
      </span>
      {onSignOut && (
        <button onClick={onSignOut} title="Sign out and return to the landing page"
          style={{ fontSize: 11, padding: "4px 12px", flexShrink: 0 }}>
          Sign out
        </button>
      )}
    </div>
  );
}

/* ---------- Layer selector (left sidebar, radio layers) ---------- */
export function LayerSelector({ layerId, onChange }: { layerId: string; onChange: (id: string) => void }) {
  return (
    <div className="layers">
      <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
        Risk layer
      </div>
      {LAYERS.map((l) => (
        <label key={l.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0", cursor: "pointer", fontSize: 12 }}>
          <input type="radio" name="layer" checked={layerId === l.id} onChange={() => onChange(l.id)} />
          {l.label}
        </label>
      ))}
    </div>
  );
}

/* ---------- Legend (left sidebar, 5-stop, labels always on) ---------- */
export function Legend({ layerLabel }: { layerLabel: string }) {
  const stops = ["Low 0–1", "Low-Med 1–2", "Med-High 2–3", "High 3–4", "Ext. High 4–5"];
  return (
    <div className="legend">
      <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 6 }}>{layerLabel} — score /5</div>
      {stops.map((s, i) => (
        <div key={s} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, padding: "1px 0" }}>
          <span style={{ width: 22, height: 10, borderRadius: 2, background: RISK_COLORS[i], border: i === 4 ? "1px solid rgba(255,255,255,0.6)" : "none" }} />
          {s}
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, padding: "1px 0" }}>
        <span style={{ width: 22, height: 10, borderRadius: 2, background: NO_DATA_COLOR }} />
        no data
      </div>
    </div>
  );
}

/* ---------- Basemap toggle (left sidebar) ---------- */
export function BasemapToggle({ value, onChange }: { value: string; onChange: (v: "dark" | "light" | "sat") => void }) {
  return (
    <div className="basemap">
      {(["dark", "light", "sat"] as const).map((b) => (
        <button key={b} onClick={() => onChange(b)}
          style={{ padding: "4px 10px", fontSize: 11, background: value === b ? "var(--accent)" : "transparent", border: "none", color: value === b ? "#fff" : "var(--muted)" }}>
          {b === "sat" ? "Satellite" : b[0].toUpperCase() + b.slice(1)}
        </button>
      ))}
    </div>
  );
}

/* ---------- Future toggle (Phase 5): scarcity is projected; others stay baseline ---------- */
export function FuturePanel({ site, baselineScarcity, onClose }: { site: Site; baselineScarcity: number | null; onClose: () => void }) {
  const [year, setYear] = useState<30 | 50>(50);
  const [scenario, setScenario] = useState<"optimistic" | "bau" | "pessimistic">("bau");
  const [proj, setProj] = useState<any | null | undefined>(undefined);

  useEffect(() => {
    if (site.pfaf_id === null) { setProj(null); return; }
    setProj(undefined);
    getFuture(site.pfaf_id, year, scenario).then(setProj);
  }, [site.pfaf_id, year, scenario]);

  return (
    <>
      <div className="popup-header">
        <b>Future scenario — {site.name}</b>
        <button onClick={onClose} style={{ padding: "2px 9px" }}>×</button>
      </div>
      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        {[30, 50].map((y) => (
          <button key={y} onClick={() => setYear(y as 30 | 50)}
            className={year === y ? "primary" : ""} style={{ fontSize: 11, padding: "4px 10px" }}>20{y}</button>
        ))}
        {(["optimistic", "bau", "pessimistic"] as const).map((s) => (
          <button key={s} onClick={() => setScenario(s)}
            className={scenario === s ? "primary" : ""} style={{ fontSize: 11, padding: "4px 10px" }}>{s}</button>
        ))}
      </div>
      {proj === undefined && <div style={{ fontSize: 12, color: "var(--muted)" }}>loading projection…</div>}
      {proj === null && <div style={{ fontSize: 12, color: "var(--faint)" }}>No cached projection and API unreachable.</div>}
      {proj && (
        <div style={{ fontSize: 12, lineHeight: 1.7 }}>
          <div>Water stress (scarcity): <b className="num">{baselineScarcity ?? "n/d"}</b> now →{" "}
            <b className="num">{proj.scarcity ?? "n/d"}</b> in 20{year} ({classify(proj.scarcity) ?? "no data"})</div>
          <div>Depletion → <b className="num">{proj.depletion ?? "n/d"}</b> · Interannual var → <b className="num">{proj.interannual_var ?? "n/d"}</b></div>
          <div className="pill" style={{ border: "1px solid var(--chip-proxy)", color: "var(--chip-proxy)", marginTop: 6, fontSize: 10 }}>
            flood / drought / groundwater stay at baseline — not projected by WRI
          </div>
        </div>
      )}
    </>
  );
}

/* ---------- Weights sliders (Phase 5): live reweight via API.
 * Sends only overrides — the backend keeps every unlisted indicator at its
 * default 1x. The recomputed overall is lifted to App via onResult so the
 * selected site's pin + basin recolor live. ---------- */
const W_STEPS = [0, 0.25, 0.5, 1, 2, 4]; // WRI base-2 scale
export function WeightsPanel({ site, onClose, onResult }: {
  site: Site; onClose: () => void; onResult: (overall: number | null) => void;
}) {
  const [w, setW] = useState<Record<string, number>>({ bws: 3, bwd: 3, drr: 3, rfr: 3, gtd: 3 }); // slider idx (1 = default)
  const [result, setResult] = useState<any | null | undefined>(null);
  const seqRef = useRef(0); // drop out-of-order responses while sliders move

  const run = async (next: Record<string, number>) => {
    const seq = ++seqRef.current;
    setResult(undefined);
    const ind: Record<string, number> = {};
    Object.entries(next).forEach(([k, idx]) => (ind[k] = W_STEPS[idx]));
    const res = await reweight(site.lat, site.lng, ind);
    if (seq !== seqRef.current) return; // a newer slider position superseded this call
    setResult(res);
    onResult(res?.overall ?? null);
  };

  return (
    <>
      <div className="popup-header">
        <b>Custom weights — {site.name}</b>
        <button onClick={onClose} style={{ padding: "2px 9px" }}>×</button>
      </div>
      {Object.keys(w).map((k) => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "40px 1fr 34px", gap: 8, alignItems: "center", padding: "3px 0" }}>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>{k}</span>
          <input type="range" min={0} max={5} step={1} value={w[k]}
            onChange={(e) => { const next = { ...w, [k]: +e.target.value }; setW(next); run(next); }} />
          <span className="num" style={{ fontSize: 11 }}>{W_STEPS[w[k]]}×</span>
        </div>
      ))}
      <div style={{ fontSize: 12, marginTop: 8 }}>
        {result === undefined && <span style={{ color: "var(--muted)" }}>recomputing…</span>}
        {result === null && <span style={{ color: "var(--faint)" }}>needs the compute API (reweighting runs on live Aqueduct data)</span>}
        {result && (
          <>
            custom overall: <b className="num" style={{ fontSize: 15 }}>{result.overall ?? "n/d"}</b> · {result.overall_cat ?? ""}
            <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 4 }}>
              equal-weight base + your overrides — differs from the card's WRI default
              (Delphi-weighted) overall by design. Map recolors with this value.
            </div>
          </>
        )}
      </div>
    </>
  );
}
