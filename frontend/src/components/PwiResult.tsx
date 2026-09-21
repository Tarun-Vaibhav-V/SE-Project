import { NO_DATA_COLOR } from "../lib/risk";
import PwiInterventions from "./PwiInterventions";

/* Presentational PWI result — renders the output of the engine (demo OR real
 * user-entered). The 3×3 matrix is the hero; confidence and roadmap sit in two
 * calm cards; real public context (green) is shown apart from assumed inputs (amber). */

const DIMS = ["Availability", "Quality", "Access"] as const;
const PILLAR_ORDER = ["P1", "P2", "P3"] as const;
const PILLAR_LABEL: Record<string, string> = { P1: "Site", P2: "Sub-Basin", P3: "Basin" };

export function pwiColor(pct: number | null): string {
  if (pct === null || pct === undefined) return NO_DATA_COLOR;
  if (pct >= 100) return "#1a9850";
  if (pct >= 80) return "#66bd63";
  if (pct >= 60) return "#fee08b";
  if (pct >= 40) return "#fc8d59";
  return "#d73027";
}
const inkOn = (pct: number | null) => (pct !== null && pct >= 60 && pct < 100 ? "#141414" : "#fff");

function certColor(result: string): string {
  if (result.startsWith("SELF-CERTIFIED")) return "#1a9850";
  if (result.startsWith("CONDITIONAL")) return "#66bd63";
  if (result.startsWith("IN PROGRESS")) return "#fed976";
  if (result.startsWith("NOT ACHIEVED")) return "#fc8d59";
  return "#d73027";
}

export default function PwiResult({ data, onBack }: { data: any; onBack?: () => void }) {
  const m = data.matrix_3x3;
  const pillars = data.pillars;
  const site = data.site_pwi.value as number;
  const conf = data.confidence;
  const cert = data.certification.result as string;
  const proj = data.targets_gap_projection;
  const wb = data.water_balance?.quant_dimensions;
  const firedRules = conf.rules.filter((r: any) => r.result === "FAIL");
  const topGaps = (proj?.gaps ?? []).slice(0, 3);
  const assumed = data.data_grade === "ASSUMED-DEMO";

  return (
    <div className="pwi-inner">
      <div className="pwi-head">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {onBack && <button onClick={onBack} style={{ fontSize: 12, padding: "5px 12px" }}>Back to assessments</button>}
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>Positive Water Impact</h1>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              {data.site.name} · {data.site.industry ?? "—"} {data.site.pfaf_id ? `· basin ${data.site.pfaf_id}` : ""}
            </div>
          </div>
        </div>
        <span className="pill" style={assumed
          ? { border: "1px solid var(--chip-proxy)", color: "var(--chip-proxy)" }
          : { border: "1px solid #1a9850", color: "#5bd08a" }}>
          {assumed ? "ASSUMED DEMO - synthetic inputs" : "YOUR DATA - as entered"}
        </span>
      </div>

      <div className="pwi-tiles">
        <div className="stat-tile">
          <div className="num" style={{ fontSize: 34, fontWeight: 700, color: pwiColor(site) }}>{site.toFixed(1)}%</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>Site PWI score</div>
        </div>
        <div className="stat-tile">
          <div style={{ fontSize: 15, fontWeight: 700, color: certColor(cert), lineHeight: 1.3 }}>{cert}</div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>Certification</div>
        </div>
        <div className="stat-tile">
          <div className="num" style={{ fontSize: 34, fontWeight: 700, color: conf.adjusted_pct >= 75 ? "#66bd63" : conf.adjusted_pct >= 50 ? "#fed976" : "#d73027" }}>
            {conf.adjusted_pct}%
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>Confidence (adjusted)</div>
        </div>
      </div>

      <div className="pwi-card">
        <div className="pwi-card-title">PWI Matrix · 3 Pillars × 3 Dimensions</div>
        <div className="pwi-matrix">
          <div className="pwi-mh" />
          {DIMS.map((d) => <div key={d} className="pwi-mh">{d}</div>)}
          <div className="pwi-mh" style={{ textAlign: "right" }}>Pillar</div>
          {PILLAR_ORDER.map((p) => (
            <PillarRow key={p} p={p} cells={m[p]} pillar={pillars[p].value} />
          ))}
        </div>
        <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 10 }}>
          Cell = Σ(question scores)/max×100. Pillar = Avail×0.4 + Quality×0.3 + Access×0.3.
          Site PWI = mean of the three pillars. Higher is better; ≥100% on all = positive impact.
        </div>
      </div>

      <div className="pwi-two">
        <div className="pwi-card">
          <div className="pwi-card-title">Confidence & cross-validation</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 13, marginBottom: 10 }}>
            <span className="num">{conf.raw_pct}%</span>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>raw</span>
            <span style={{ color: "var(--risk-3)" }}>− {conf.xv_penalty_points}</span>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>penalty</span>
            <span style={{ marginLeft: "auto" }} />
            <span className="num" style={{ fontSize: 18, fontWeight: 700 }}>{conf.adjusted_pct}%</span>
          </div>
          <div className="pwi-bar"><div style={{ width: `${conf.adjusted_pct}%` }} /></div>
          <div style={{ fontSize: 11, color: "var(--muted)", margin: "10px 0 6px" }}>
            {10 - firedRules.length} / 10 checks passed
            {firedRules.length > 0 && <> · <span style={{ color: "var(--risk-3)" }}>{firedRules.length} flagged</span></>}
          </div>
          {firedRules.map((r: any) => (
            <div key={r.id} style={{ fontSize: 11, padding: "4px 0", borderTop: "1px solid var(--border)" }}>
              <b style={{ color: "var(--risk-3)" }}>{r.id}</b> {r.check} <span className="num" style={{ color: "var(--faint)" }}>−{r.penalty_points}</span>
              <div style={{ color: "var(--faint)", fontSize: 10 }}>↳ {r.action}</div>
            </div>
          ))}
          {firedRules.length === 0 && <div style={{ fontSize: 11, color: "#5bd08a" }}>All cross-checks passed.</div>}
        </div>

        <div className="pwi-card">
          <div className="pwi-card-title">Gap & roadmap</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <div>
              <div className="num" style={{ fontSize: 22, fontWeight: 700, color: pwiColor(site) }}>{site.toFixed(1)}%</div>
              <div style={{ fontSize: 10, color: "var(--muted)" }}>today</div>
            </div>
            <span style={{ color: "var(--faint)" }}>→</span>
            <div>
              <div className="num" style={{ fontSize: 22, fontWeight: 700, color: pwiColor(proj.projected_site_pwi.value) }}>
                {proj.projected_site_pwi.value.toFixed(1)}%
              </div>
              <div style={{ fontSize: 10, color: "var(--muted)" }}>after Phase 1 (planned)</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>Largest gaps to close:</div>
          {topGaps.map((g: any, i: number) => (
            <div key={i} style={{ fontSize: 11, padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b>{g.pillar} {g.pillar_name} · {g.dimension}</b>
                <span className="num" style={{ color: "var(--risk-3)" }}>gap {g.gap_pct}%</span>
              </div>
              <div style={{ color: "var(--muted)" }}>↳ {g.recommended_interventions[0]}</div>
            </div>
          ))}
        </div>
      </div>

      {wb && (
        <div className="pwi-card">
          <div className="pwi-card-title">Operational cross-check (water balance)</div>
          <div className="pwi-wb">
            <WB label="Availability" hint="replenishment ÷ withdrawal" v={wb.Availability.value} />
            <WB label="Quality" hint="wastewater treated ÷ generated" v={wb.Quality.value} />
            <WB label="Access" hint="WASH conditions met" v={wb.Access.value} />
            <WB label="Withdrawal" hint="m³/yr" v={data.water_balance.withdrawal_m3} raw />
          </div>
        </div>
      )}

      {/* AI intervention planner for this site */}
      <PwiInterventions results={[data]} scope="site" />

      {data.basin_context?.metrics && (
        <div className="pwi-card">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span className="pwi-card-title" style={{ margin: 0 }}>Basin context · {data.basin_context.country}</span>
            <span className="pill" style={{ border: "1px solid #1a9850", color: "#5bd08a", fontSize: 10 }}>REAL - World Bank, live</span>
          </div>
          <div className="pwi-wb">
            {data.basin_context.metrics.map((mm: any) => (
              <div key={mm.code}>
                <div className="num" style={{ fontSize: 18, fontWeight: 700, color: mm.value === null ? "var(--faint)" : "var(--text)" }}>
                  {mm.value === null ? "n/d" : mm.value.toLocaleString()}
                  <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400 }}> {mm.unit}</span>
                </div>
                <div style={{ fontSize: 11 }}>{mm.indicator}</div>
                <div style={{ fontSize: 10, color: "var(--faint)" }}>{mm.pwi_dimension} · {mm.year ?? "—"}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 10 }}>{data.basin_context.note}</div>
        </div>
      )}

      <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 12 }}>
        Methodology: {data.method_source}. Every value is traceable to its formula, source and confidence.
        <br />Colour key: <b style={{ color: "var(--chip-proxy)" }}>amber = ASSUMED</b> (factory inputs, owner-supplied) ·
        <b style={{ color: "#5bd08a" }}> green = REAL</b> (live public data).
      </div>
    </div>
  );
}

function PillarRow({ p, cells, pillar }: { p: string; cells: any; pillar: number }) {
  return (
    <>
      <div className="pwi-plabel"><b>{p}</b> {PILLAR_LABEL[p]}</div>
      {DIMS.map((d) => {
        const v = cells[d].value as number | null;
        return (
          <div key={d} className="pwi-cell num" style={{ background: pwiColor(v), color: inkOn(v) }}>
            {v === null ? "n/d" : `${v.toFixed(0)}%`}
          </div>
        );
      })}
      <div className="pwi-cell num" style={{ background: "transparent", color: pwiColor(pillar), fontWeight: 700, textAlign: "right" }}>
        {pillar.toFixed(1)}%
      </div>
    </>
  );
}

function WB({ label, hint, v, raw }: { label: string; hint: string; v: number | null; raw?: boolean }) {
  return (
    <div>
      <div className="num" style={{ fontSize: 18, fontWeight: 700, color: raw ? "var(--text)" : pwiColor(v) }}>
        {v === null || v === undefined ? "n/d" : raw ? v.toLocaleString() : `${v.toFixed(0)}%`}
      </div>
      <div style={{ fontSize: 11 }}>{label}</div>
      <div style={{ fontSize: 10, color: "var(--faint)" }}>{hint}</div>
    </div>
  );
}
