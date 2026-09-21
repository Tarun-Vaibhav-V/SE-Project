import { INDICATORS, classify, riskColor } from "../lib/risk";
import type { Site } from "../lib/data";
import PWIRing from "./PWIRing";
import MiniBar from "./MiniBar";

interface Props {
  site: Site;
  cache: any | null;               // risk_cache row (profile+pwi) or null
  basinProps: Record<string, any>; // normalized fallback props
  onExplain: (risk: string) => void;
  onClose: () => void;
}

/** S-02 Site Risk Card: overall 48px mono, 13 mini bars, PWI ring gauges. */
export default function RiskCard({ site, cache, basinProps, onExplain, onClose }: Props) {
  const profile = cache?.profile ?? null;
  const pwi = cache?.pwi ?? null;

  const score = (code: string): number | null => {
    if (profile?.[code]) return profile[code].score ?? null;
    return basinProps[code] ?? null; // fallback covers bws/bwd/gtd/drr/rfr/cfr only
  };
  const overall: number | null = profile?.overall_gee ?? basinProps.overall ?? null;
  const level = classify(overall);
  const flood = (() => {
    const r = score("rfr"), c = score("cfr");
    return r === null && c === null ? null : Math.max(r ?? -1, c ?? -1);
  })();
  const shortage = (() => {
    const b = score("bws"), d = score("drr");
    if (b === null && d === null) return null;
    return ((b ?? d ?? 0) + (d ?? b ?? 0)) / 2;
  })();

  return (
    <div className="glass risk-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{site.name}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            basin {site.pfaf_id ?? basinProps.pfaf_id ?? "?"} · {site.lat.toFixed(3)}, {site.lng.toFixed(3)}
          </div>
        </div>
        <button onClick={onClose} style={{ padding: "2px 9px", fontSize: 13 }} aria-label="close">×</button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "12px 0" }}>
        <span className="num" style={{ fontSize: 48, fontWeight: 700, lineHeight: 1, color: riskColor(overall) }}>
          {overall === null ? "–" : overall.toFixed(2)}
        </span>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {level && (
            <span className="pill" style={{ background: riskColor(overall), color: (overall ?? 0) >= 2 && (overall ?? 0) < 4 ? "#1a1a1a" : "#fff" }}>
              {level}
            </span>
          )}
          <span style={{ fontSize: 10, color: "var(--muted)" }}>WRI Aqueduct 4.0 · overall water risk /5</span>
        </div>
      </div>

      {pwi?.dims ? (
        <div style={{ display: "flex", justifyContent: "space-around", padding: "8px 0 12px", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
          <PWIRing label="Availability" score={pwi.dims.Availability ?? null} />
          <PWIRing label="Quality" score={pwi.dims.Quality ?? null} />
          <PWIRing label="Access" score={pwi.dims.Accessibility ?? null} />
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "var(--faint)", padding: "8px 0", borderTop: "1px solid var(--border)" }}>
          PWI dimensions appear once this basin is cached in Supabase (run backend/seed.py).
        </div>
      )}

      <div style={{ display: "flex", gap: 8, margin: "10px 0" }}>
        <span className="pill" style={{ border: "1px solid var(--border-strong)", color: "var(--text)" }}>
          Flood <b className="num">{flood === null ? "n/d" : flood.toFixed(1)}</b>
        </span>
        <span className="pill" style={{ border: "1px solid var(--border-strong)", color: "var(--text)" }}>
          Shortage <b className="num">{shortage === null ? "n/d" : shortage.toFixed(1)}</b>
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 5, maxHeight: 180, overflowY: "auto", paddingRight: 4 }}>
        {INDICATORS.map((ind) => (
          <MiniBar key={ind.code} label={ind.label} score={score(ind.code)} />
        ))}
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
        {["drought", "groundwater", "flood"].map((r) => (
          <button key={r} onClick={() => onExplain(r)} style={{ flex: 1, fontSize: 11, padding: "7px 4px" }}>
            Why {r}?
          </button>
        ))}
      </div>
    </div>
  );
}
