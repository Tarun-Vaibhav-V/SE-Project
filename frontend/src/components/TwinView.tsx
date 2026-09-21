import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { riskColor, classify } from "../lib/risk";
import {
  interventionCatalog, simulateInterventions, optimizeInterventions,
  riskBudget, evidenceGraph, confidenceReport,
} from "../lib/data";
import type { Site, SiteParams } from "../lib/data";

/* Hydris Intervention Intelligence Engine — the What-If Lab.
 *
 * The map answers "how risky is this factory, and why?". This view answers the
 * next four questions: what can we change, how much risk does it remove, how
 * much water does it save, and which option wins.
 *
 * Every number on screen comes from backend/intervention.py, which re-runs the
 * REAL drivers.composite() on modified severities — no parallel scoring maths
 * lives here. The UI's only job is to keep the modelled/measured distinction
 * visible: effect coefficients are planning estimates, the baselines they move
 * are satellite-computed, and confidence propagates by weakest link. */

interface Props {
  sites: Site[];
  selectedSite: Site | null;
}

const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? "n/d" : v.toFixed(dp);

const CHIP: Record<string, string> = {
  computed: "var(--chip-computed)",
  proxy: "var(--chip-proxy)",
  regional: "var(--chip-regional)",
  "planning-estimate": "var(--chip-proxy)",
  "no-data": "var(--chip-nodata)",
};

function Chip({ c }: { c?: string }) {
  if (!c) return null;
  return (
    <span style={{
      fontSize: 10, padding: "2px 7px", borderRadius: 99, fontWeight: 600,
      background: CHIP[c] ?? "var(--chip-nodata)", color: "#0b1220",
      letterSpacing: "0.02em", whiteSpace: "nowrap",
    }}>{c}</span>
  );
}

/** Before → after bar. Colour always paired with the number, never colour alone. */
function DeltaBar({ before, after }: { before: number | null; after: number | null }) {
  if (before === null || after === null)
    return <span style={{ color: "var(--faint)", fontSize: 11 }}>n/d</span>;
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / 5) * 100))}%`;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ flex: 1, minWidth: 90 }}>
        <div style={{ height: 7, background: "rgba(255,255,255,0.07)", borderRadius: 4, marginBottom: 4, position: "relative" }}>
          <div style={{ position: "absolute", inset: 0, width: pct(before), background: riskColor(before), borderRadius: 4, opacity: 0.45 }} />
        </div>
        <div style={{ height: 7, background: "rgba(255,255,255,0.07)", borderRadius: 4, position: "relative" }}>
          <div style={{ position: "absolute", inset: 0, width: pct(after), background: riskColor(after), borderRadius: 4 }} />
        </div>
      </div>
      <span className="num" style={{ fontSize: 12, minWidth: 84, textAlign: "right" }}>
        <span style={{ color: "var(--muted)" }}>{before.toFixed(2)}</span>
        <span style={{ color: "var(--faint)", margin: "0 4px" }}>→</span>
        <strong style={{ color: after < before ? "#4ade80" : "var(--text)" }}>{after.toFixed(2)}</strong>
      </span>
    </div>
  );
}

export default function TwinView({ sites, selectedSite }: Props) {
  const [siteId, setSiteId] = useState<string>(selectedSite?.id ?? sites[0]?.id ?? "");
  const site = useMemo(() => sites.find((s) => s.id === siteId) ?? null, [sites, siteId]);

  const [catalog, setCatalog] = useState<any[]>([]);
  const [portfolio, setPortfolio] = useState<Record<string, number>>({});
  const [params, setParams] = useState<SiteParams>({
    roof_area_m2: 12000, annual_rainfall_mm: 1200,
    withdrawal_m3_yr: 180000, effluent_m3_yr: 90000, catchment_area_m2: 45000,
  });

  const [sim, setSim] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [goal, setGoal] = useState("max_risk_reduction");
  const [intensity, setIntensity] = useState(0.6);
  const [opt, setOpt] = useState<any | null>(null);
  const [optBusy, setOptBusy] = useState(false);

  const [maxAcceptable, setMaxAcceptable] = useState(3.0);
  const [budget, setBudget] = useState<any | null>(null);

  const [conf, setConf] = useState<any | null>(null);
  const [graph, setGraph] = useState<any | null>(null);

  const target = site ? { site_id: site.id, lat: site.lat, lng: site.lng } : null;

  useEffect(() => { interventionCatalog().then((c) => setCatalog(c.interventions)).catch(() => {}); }, []);
  useEffect(() => { if (selectedSite) setSiteId(selectedSite.id); }, [selectedSite]);

  // reset everything that belongs to the previous site
  useEffect(() => {
    setSim(null); setOpt(null); setBudget(null); setGraph(null); setConf(null); setErr(null);
    if (target) confidenceReport(target).then(setConf).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId]);

  // debounce the twin so dragging a slider doesn't spam the engine
  const timer = useRef<number | null>(null);
  const runSim = useCallback(() => {
    if (!target) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      const active = Object.entries(portfolio).filter(([, v]) => v > 0);
      if (!active.length) { setSim(null); return; }
      setBusy(true); setErr(null);
      try {
        setSim(await simulateInterventions(target, Object.fromEntries(active), params));
      } catch (e: any) { setErr(e?.message ?? "simulation failed"); }
      finally { setBusy(false); }
    }, 350);
  }, [portfolio, params, siteId]);

  useEffect(() => { runSim(); return () => { if (timer.current) window.clearTimeout(timer.current); }; }, [runSim]);

  const setLevel = (id: string, v: number) => setPortfolio((p) => ({ ...p, [id]: v }));

  const runOptimize = async () => {
    if (!target) return;
    setOptBusy(true); setErr(null);
    try { setOpt(await optimizeInterventions(target, goal, intensity, params)); }
    catch (e: any) { setErr(e?.message ?? "optimizer failed"); }
    finally { setOptBusy(false); }
  };

  const runBudget = async () => {
    if (!target) return;
    setOptBusy(true); setErr(null);
    try { setBudget(await riskBudget(target, maxAcceptable, intensity, params)); }
    catch (e: any) { setErr(e?.message ?? "risk budget failed"); }
    finally { setOptBusy(false); }
  };

  const applyPortfolio = (ids: string[]) => {
    setPortfolio(Object.fromEntries(ids.map((i) => [i, intensity])));
  };

  const showGraph = async (id: string) => {
    if (!target) return;
    try { setGraph(await evidenceGraph(target, id, portfolio[id] || intensity)); }
    catch { setGraph(null); }
  };

  const overall = sim?.overall;

  return (
    <div className="twin">
      <div className="twin-inner">

        <div className="twin-head">
          <div>
            <h2 style={{ margin: 0, fontSize: 22, letterSpacing: "-0.01em" }}>
              What-If Lab <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: 15 }}>· Intervention Intelligence</span>
            </h2>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13, maxWidth: 720 }}>
              Move the sliders to model an intervention portfolio. Risk is recomputed by the same
              driver composite that produced the baseline — effect sizes are planning estimates,
              the severities they modify are satellite-computed.
            </p>
          </div>
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}
                  style={{ minWidth: 210, height: 34 }}>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>

        {err && <div className="twin-err">{err}</div>}

        {/* ── headline result ── */}
        <div className="twin-tiles">
          <div className="stat-tile">
            <div className="twin-tile-label">Current risk</div>
            <div className="num twin-tile-val">{num(overall?.before_0_5)}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>{classify(overall?.before_0_5 ?? null) ?? "—"}</div>
          </div>
          <div className="stat-tile">
            <div className="twin-tile-label">Projected risk</div>
            <div className="num twin-tile-val" style={{ color: overall?.after_0_5 != null && overall.after_0_5 < overall.before_0_5 ? "#4ade80" : undefined }}>
              {num(overall?.after_0_5)}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>{classify(overall?.after_0_5 ?? null) ?? "—"}</div>
          </div>
          <div className="stat-tile">
            <div className="twin-tile-label">Risk reduction</div>
            <div className="num twin-tile-val">{overall?.reduction_pct != null ? `${overall.reduction_pct}%` : "n/d"}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>−{num(overall?.reduction_0_5)} on 0–5</div>
          </div>
          <div className="stat-tile">
            <div className="twin-tile-label">Water offset</div>
            <div className="num twin-tile-val">
              {sim?.water_total_m3_per_year != null
                ? `${(sim.water_total_m3_per_year / 1000).toFixed(1)}k`
                : "n/d"}
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>m³ / year</div>
          </div>
          <div className="stat-tile">
            <div className="twin-tile-label">Indicative cost</div>
            <div className="num twin-tile-val">{sim ? `₹${num(sim.total_cost_lakh_inr, 1)}L` : "n/d"}</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>planning band</div>
          </div>
        </div>

        <div className="twin-grid">
          {/* ── sliders ── */}
          <section className="twin-card">
            <div className="twin-card-title">
              Factory water digital twin
              {busy && <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400 }}> · simulating…</span>}
            </div>
            {catalog.map((iv) => {
              const v = portfolio[iv.id] ?? 0;
              return (
                <div key={iv.id} className="twin-slider">
                  <div className="twin-slider-head">
                    <span title={iv.basis_note}>{iv.name}</span>
                    <span className="num" style={{ color: v > 0 ? "var(--accent)" : "var(--faint)" }}>
                      {Math.round(v * 100)}%
                    </span>
                  </div>
                  <input type="range" min={0} max={100} value={Math.round(v * 100)}
                         onChange={(e) => setLevel(iv.id, +e.target.value / 100)} />
                  <div className="twin-slider-meta">
                    <span>{iv.duration} · {iv.cost_band} cost · {iv.difficulty} difficulty</span>
                    <button className="linkish" onClick={() => showGraph(iv.id)}>why?</button>
                  </div>
                </div>
              );
            })}
            <button className="ghost" style={{ marginTop: 6 }} onClick={() => setPortfolio({})}>
              Reset all
            </button>
          </section>

          {/* ── right column ── */}
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

            {/* per-risk counterfactual */}
            <section className="twin-card">
              <div className="twin-card-title">Simulated risk state</div>
              {!sim && <p className="twin-empty">Move a slider to run the counterfactual.</p>}
              {sim && Object.entries(sim.per_risk).map(([risk, r]: any) => (
                <div key={risk} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 5 }}>
                    <span style={{ textTransform: "capitalize" }}>{risk}</span>
                    <span style={{ color: "var(--muted)" }}>
                      {r.reduction_pct != null ? `−${r.reduction_pct}%` : "n/d"}
                    </span>
                  </div>
                  <DeltaBar before={r.hazard_before_0_5} after={r.hazard_after_0_5} />
                </div>
              ))}
              {sim && (
                <>
                  <div className="twin-pwi">
                    {Object.entries(sim.pwi_delta).map(([dim, d]: any) => (
                      <div key={dim} className="twin-pwi-cell">
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>{dim}</div>
                        <div className="num" style={{ fontSize: 16, fontWeight: 600 }}>
                          {d.improvement_pct != null ? `↑ ${d.improvement_pct}%` : "n/d"}
                        </div>
                        <div style={{ fontSize: 10, color: "var(--faint)" }}>{d.basis}</div>
                      </div>
                    ))}
                  </div>
                  <div className="twin-caveat">
                    <Chip c={sim.confidence} /> {sim.caveat}
                  </div>
                </>
              )}
            </section>

            {/* optimizer */}
            <section className="twin-card">
              <div className="twin-card-title">Goal-based optimiser</div>
              <div className="twin-controls">
                <select value={goal} onChange={(e) => setGoal(e.target.value)}>
                  <option value="max_risk_reduction">Minimise overall water risk</option>
                  <option value="best_roi">Best ROI (risk drop per ₹ lakh)</option>
                  <option value="max_water">Maximise water saved</option>
                </select>
                <label className="twin-inline">
                  intensity
                  <input type="range" min={10} max={100} value={Math.round(intensity * 100)}
                         onChange={(e) => setIntensity(+e.target.value / 100)} style={{ width: 90 }} />
                  <span className="num">{Math.round(intensity * 100)}%</span>
                </label>
                <button onClick={runOptimize} disabled={optBusy}>
                  {optBusy ? "Searching…" : "Optimise"}
                </button>
              </div>
              {opt?.best && (
                <>
                  <div className="twin-best">
                    <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>
                      Best of {opt.evaluated_count} portfolios evaluated
                    </div>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                      {opt.best.names.join(" + ")}
                    </div>
                    <div style={{ display: "flex", gap: 18, fontSize: 12 }}>
                      <span>risk <strong className="num">{num(opt.best.hazard_before_0_5)} → {num(opt.best.hazard_after_0_5)}</strong></span>
                      <span>cost <strong className="num">₹{num(opt.best.cost_lakh_inr, 1)}L</strong></span>
                      {opt.best.water_m3_per_year && <span>water <strong className="num">{(opt.best.water_m3_per_year / 1000).toFixed(1)}k m³</strong></span>}
                    </div>
                    <button className="ghost" style={{ marginTop: 8 }}
                            onClick={() => applyPortfolio(opt.best.portfolio)}>
                      Load into the twin
                    </button>
                  </div>
                  <table className="twin-table">
                    <thead><tr><th>Portfolio</th><th>Risk ↓</th><th>Water m³/yr</th><th>Cost ₹L</th><th>ROI</th></tr></thead>
                    <tbody>
                      {opt.ranked.slice(0, 6).map((e: any, i: number) => (
                        <tr key={i} onClick={() => applyPortfolio(e.portfolio)}>
                          <td style={{ maxWidth: 230 }}>{e.names.join(" + ")}</td>
                          <td className="num">{num(e.reduction_0_5)}</td>
                          <td className="num">{e.water_m3_per_year ? Math.round(e.water_m3_per_year).toLocaleString() : "n/d"}</td>
                          <td className="num">{num(e.cost_lakh_inr, 1)}</td>
                          <td className="num">{e.roi_reduction_per_lakh?.toFixed(4) ?? "n/d"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {opt && !opt.best && <p className="twin-empty">{opt.reason}</p>}
            </section>

            {/* risk budget */}
            <section className="twin-card">
              <div className="twin-card-title">Water risk budget</div>
              <div className="twin-controls">
                <label className="twin-inline">
                  max acceptable
                  <input type="range" min={10} max={50} value={Math.round(maxAcceptable * 10)}
                         onChange={(e) => setMaxAcceptable(+e.target.value / 10)} style={{ width: 110 }} />
                  <span className="num">{maxAcceptable.toFixed(1)}</span>
                </label>
                <button onClick={runBudget} disabled={optBusy}>Solve</button>
              </div>
              {budget && budget.current_0_5 != null && (
                <>
                  <div className="twin-budget">
                    <div className="twin-budget-row">
                      <span>Maximum acceptable</span>
                      <div className="twin-budget-bar"><div style={{ width: `${(budget.max_acceptable_0_5 / 5) * 100}%`, background: "#3b82f6" }} /></div>
                      <span className="num">{budget.max_acceptable_0_5.toFixed(1)}</span>
                    </div>
                    <div className="twin-budget-row">
                      <span>Current</span>
                      <div className="twin-budget-bar"><div style={{ width: `${(budget.current_0_5 / 5) * 100}%`, background: riskColor(budget.current_0_5) }} /></div>
                      <span className="num">{budget.current_0_5.toFixed(2)}</span>
                    </div>
                    <div style={{ fontSize: 12, color: budget.within_budget ? "#4ade80" : "#f87171", marginTop: 6 }}>
                      {budget.within_budget
                        ? "Within budget — no portfolio required."
                        : `${budget.over_by_0_5.toFixed(2)} over — required reduction ${budget.required_reduction_0_5.toFixed(2)}`}
                    </div>
                  </div>
                  {budget.solution?.best && (
                    <div className="twin-best">
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>Cheapest portfolio that reaches the target</div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{budget.solution.best.names.join(" + ")}</div>
                      <div style={{ fontSize: 12, marginTop: 4 }}>
                        → <span className="num">{num(budget.solution.best.hazard_after_0_5)}</span> at
                        <span className="num"> ₹{num(budget.solution.best.cost_lakh_inr, 1)}L</span>
                      </div>
                      <button className="ghost" style={{ marginTop: 8 }}
                              onClick={() => applyPortfolio(budget.solution.best.portfolio)}>Load into the twin</button>
                    </div>
                  )}
                  {budget.solution && !budget.solution.best && (
                    <p className="twin-empty">{budget.solution.reason}</p>
                  )}
                  {budget.single_measure_contributions && (
                    <table className="twin-table">
                      <thead><tr><th>Single measure</th><th>Risk ↓</th><th>Cost ₹L</th></tr></thead>
                      <tbody>
                        {budget.single_measure_contributions.slice(0, 5).map((s: any) => (
                          <tr key={s.id} onClick={() => applyPortfolio([s.id])}>
                            <td>{s.name}</td>
                            <td className="num">−{num(s.reduction_0_5)}</td>
                            <td className="num">{num(s.cost_lakh_inr, 1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              )}
            </section>

            {/* confidence */}
            {conf && (
              <section className="twin-card">
                <div className="twin-card-title">
                  Evidence quality
                  <span className="num" style={{ float: "right" }}>{conf.overall_evidence_pct}%</span>
                </div>
                {Object.entries(conf.per_risk).map(([risk, v]: any) => (
                  <div key={risk} style={{ marginBottom: 8 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                      <span style={{ textTransform: "capitalize" }}>{risk}</span>
                      <span className="num">{v.evidence_quality_pct ?? "n/d"}%</span>
                    </div>
                    <div style={{ height: 6, background: "rgba(255,255,255,0.07)", borderRadius: 3 }}>
                      <div style={{ height: "100%", width: `${v.evidence_quality_pct ?? 0}%`, background: "#38bdf8", borderRadius: 3 }} />
                    </div>
                    <div style={{ display: "flex", gap: 4, marginTop: 5, flexWrap: "wrap" }}>
                      {Object.entries(v.confidence_mix).map(([c, n]: any) => (
                        <span key={c} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                          <Chip c={c} /><span style={{ fontSize: 10, color: "var(--faint)" }}>×{n}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
                {conf.notes?.map((n: string, i: number) => (
                  <div key={i} className="twin-note">⚠ {n}</div>
                ))}
              </section>
            )}
          </div>
        </div>

        {/* ── site parameters ── */}
        <section className="twin-card" style={{ marginTop: 14 }}>
          <div className="twin-card-title">Site parameters <span style={{ fontWeight: 400, color: "var(--muted)", fontSize: 12 }}>— drive the volumetric benefit formulas</span></div>
          <div className="twin-params">
            {([
              ["roof_area_m2", "Roof area (m²)"],
              ["annual_rainfall_mm", "Annual rainfall (mm)"],
              ["withdrawal_m3_yr", "Withdrawal (m³/yr)"],
              ["effluent_m3_yr", "Effluent (m³/yr)"],
              ["catchment_area_m2", "Catchment area (m²)"],
            ] as [keyof SiteParams, string][]).map(([k, label]) => (
              <label key={k} className="twin-param">
                <span>{label}</span>
                <input type="number" value={(params[k] as number) ?? ""}
                       onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value === "" ? undefined : +e.target.value }))} />
              </label>
            ))}
          </div>
          {sim?.water_benefit && (
            <table className="twin-table" style={{ marginTop: 10 }}>
              <thead><tr><th>Measure</th><th>m³/yr</th><th>Formula</th></tr></thead>
              <tbody>
                {Object.entries(sim.water_benefit).map(([id, w]: any) => (
                  <tr key={id}>
                    <td>{catalog.find((c) => c.id === id)?.name ?? id}</td>
                    <td className="num">{w.m3_per_year != null ? Math.round(w.m3_per_year).toLocaleString() : "n/d"}</td>
                    <td style={{ fontSize: 11, color: "var(--muted)" }}>
                      {w.missing_input ? `needs ${w.missing_input}` : (w.reason ?? w.formula)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* ── evidence graph ── */}
        {graph && (
          <section className="twin-card" style={{ marginTop: 14 }}>
            <div className="twin-card-title">
              Evidence graph — {graph.name}
              <button className="linkish" style={{ float: "right" }} onClick={() => setGraph(null)}>close</button>
            </div>
            <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 12px" }}>
              Every edge is traceable: the modelled effect, the driver it moves with its measured
              weight and attribution, and the Earth-observation dataset behind that driver.
            </p>
            <div className="twin-graph">
              <div className="twin-gnode twin-grec">{graph.name}<Chip c="planning-estimate" /></div>
              {graph.nodes.filter((n: any) => n.kind === "driver").map((n: any) => {
                const ds = graph.edges.find((e: any) => e.from === n.id && e.kind === "computed_from");
                const dsn = graph.nodes.find((x: any) => x.id === ds?.to);
                const ef = graph.edges.find((e: any) => e.to === n.id && e.kind === "modelled_effect");
                return (
                  <div key={n.id} className="twin-gbranch">
                    <div className="twin-gedge">−{ef?.applied_delta?.toFixed(3)} severity</div>
                    <div className="twin-gnode">
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <strong>{n.label}</strong><Chip c={n.confidence} />
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>
                        {n.risk} · severity <span className="num">{n.severity}</span> · weight <span className="num">{n.weight}</span>
                        {n.attribution_pct != null && <> · attribution <span className="num">{n.attribution_pct}%</span></>}
                      </div>
                      {n.caveat && <div className="twin-note" style={{ marginTop: 5 }}>⚠ {n.caveat}</div>}
                    </div>
                    <div className="twin-gedge">computed from</div>
                    <div className="twin-gnode twin-gds">{dsn?.label ?? "unknown"}</div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <p className="twin-foot">
          Effect coefficients are planning estimates from the WSM 4-Step framework and WQBA
          volumetric benefit accounting — not measured outcomes. The baseline severities they
          modify are computed from satellite data, and the projected score is recomputed by the
          same <code>drivers.composite()</code> that produced the baseline. Costs are indicative
          bands, not quotes.
        </p>
      </div>
    </div>
  );
}
