import { useMemo, useRef, useState } from "react";
import { riskColor, classify } from "../lib/risk";
import { addSite } from "../lib/data";
import type { Site } from "../lib/data";

/* Portfolio dashboard — the enterprise workflow surface. A ranked, filterable,
 * sortable register of every site (overall + per-risk + 2050 projection), with
 * CSV bulk import / export. The map becomes the drill-down, not the front door. */

interface Props {
  sites: Site[];
  basinByPfaf: Record<string, Record<string, any>>;
  futures: Record<number, any>;
  onDrill: (s: Site) => void;   // row click -> open on the map
  onReload: () => void;         // after CSV import, reload sites+basins
}

interface Row {
  site: Site;
  overall: number | null;
  level: string | null;
  bws: number | null;
  flood: number | null;
  drr: number | null;
  gtd: number | null;
  f2050: number | null;
  delta: number | null;
}

type SortKey = "name" | "overall" | "bws" | "flood" | "drr" | "gtd" | "f2050" | "delta";

const num = (v: number | null, dp = 1) => (v === null || v === undefined ? "n/d" : v.toFixed(dp));

/** One colored score cell — color always paired with the number (never color alone). */
function Score({ v, dp = 1 }: { v: number | null; dp?: number }) {
  if (v === null || v === undefined)
    return <span style={{ color: "var(--faint)", fontSize: 11 }}>n/d</span>;
  const dark = v >= 2 && v < 4;
  return (
    <span className="num" style={{
      display: "inline-block", minWidth: 34, textAlign: "center", padding: "2px 6px",
      borderRadius: 6, fontSize: 12, fontWeight: 600,
      background: riskColor(v), color: dark ? "#141414" : "#fff",
      border: v >= 4 ? "1px solid rgba(255,255,255,0.6)" : "none",
    }}>{v.toFixed(dp)}</span>
  );
}

/** Minimal quote-aware CSV line splitter (handles "a,b" quoted fields). */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; }
    else if (c === "," && !q) { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

export default function PortfolioView({ sites, basinByPfaf, futures, onDrill, onReload }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "high" | "extreme" | "nodata" | "worst">("all");
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [importing, setImporting] = useState<{ done: number; total: number; label: string } | null>(null);
  const [importLog, setImportLog] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const rows: Row[] = useMemo(() => sites.map((s) => {
    const p = s.pfaf_id != null ? basinByPfaf[String(s.pfaf_id)] ?? {} : {};
    const fut = s.pfaf_id != null ? futures[s.pfaf_id] : undefined;
    const f2050 = fut?.bau50?.scarcity ?? null;
    const overall = p.overall ?? null;
    const bws = p.bws ?? null;
    return {
      site: s, overall, level: classify(overall),
      bws, flood: p.flood ?? null, drr: p.drr ?? null, gtd: p.gtd ?? null,
      f2050, delta: f2050 != null && bws != null ? +(f2050 - bws).toFixed(2) : null,
    };
  }), [sites, basinByPfaf, futures]);

  const stats = useMemo(() => {
    const scored = rows.filter((r) => r.overall !== null);
    const extreme = scored.filter((r) => (r.overall ?? 0) >= 4).length;
    const high = scored.filter((r) => (r.overall ?? 0) >= 3 && (r.overall ?? 0) < 4).length;
    const avg = scored.length ? scored.reduce((a, r) => a + (r.overall ?? 0), 0) / scored.length : null;
    return { total: rows.length, extreme, high, avg, nodata: rows.length - scored.length };
  }, [rows]);

  const view = useMemo(() => {
    let r = rows.filter((x) => x.site.name.toLowerCase().includes(query.toLowerCase()));
    if (filter === "high") r = r.filter((x) => (x.overall ?? -1) >= 3);
    else if (filter === "extreme") r = r.filter((x) => (x.overall ?? -1) >= 4);
    else if (filter === "nodata") r = r.filter((x) => x.overall === null);
    const dir = sortDir === "asc" ? 1 : -1;
    r = [...r].sort((a, b) => {
      if (sortKey === "name") return a.site.name.localeCompare(b.site.name) * dir;
      const av = (a as any)[sortKey], bv = (b as any)[sortKey];
      if (av === null || av === undefined) return 1;       // nulls always last
      if (bv === null || bv === undefined) return -1;
      return (av - bv) * dir;
    });
    if (filter === "worst") r = r.slice(0, 10);
    return r;
  }, [rows, query, filter, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir(k === "name" ? "asc" : "desc"); }
  };

  // Excel/Sheets execute cells starting with = + - @ as formulas — neutralize
  // user-supplied text so a site named "=HYPERLINK(...)" can't inject on export.
  const csvSafe = (s: string) => (/^[=+\-@\t]/.test(s) ? `'${s}` : s);

  const exportCsv = () => {
    const header = ["Site", "ID", "Basin", "Lat", "Lng", "Overall", "Level",
      "WaterStress", "Flood", "Drought", "Groundwater", "Scarcity2050"];
    const lines = [header.join(",")];
    for (const r of view) {
      lines.push([
        `"${csvSafe(r.site.name).replace(/"/g, '""')}"`, csvSafe(String(r.site.id)), r.site.pfaf_id ?? "",
        r.site.lat, r.site.lng, num(r.overall, 2), r.level ?? "no-data",
        num(r.bws), num(r.flood), num(r.drr), num(r.gtd), num(r.f2050),
      ].join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `hydris-portfolio-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const importCsv = async (file: File) => {
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    if (!lines.length) return;
    const head = splitCsvLine(lines[0]).map((h) => h.toLowerCase());
    const iName = head.findIndex((h) => h.includes("name") || h.includes("site"));
    const iLat = head.findIndex((h) => h.startsWith("lat"));
    const iLng = head.findIndex((h) => h.startsWith("lng") || h.startsWith("lon"));
    const iId = head.findIndex((h) => h === "id" || h.includes("site id") || h === "siteid");
    if (iName < 0 || iLat < 0 || iLng < 0) {
      setImportLog(["✗ CSV needs columns: name, lat, lng (id optional)"]);
      return;
    }
    const parsed = lines.slice(1).map(splitCsvLine).map((c) => ({
      name: c[iName], lat: parseFloat(c[iLat]), lng: parseFloat(c[iLng]),
      id: iId >= 0 ? c[iId] || undefined : undefined,
    })).filter((r) => r.name && Number.isFinite(r.lat) && Number.isFinite(r.lng));

    const log: string[] = [];
    for (let i = 0; i < parsed.length; i++) {
      const row = parsed[i];
      setImporting({ done: i, total: parsed.length, label: row.name });
      try {
        const res = await addSite(row);
        log.push(`✓ ${row.name} — overall ${res.overall?.toFixed(2) ?? "n/d"} (${res.level ?? "no-data"})`);
      } catch (e: any) {
        log.push(`✗ ${row.name} — ${String(e?.message ?? e).slice(0, 80)}`);
      }
      setImportLog([...log]);
    }
    setImporting(null);
    onReload();
  };

  const Th = ({ k, label, right }: { k: SortKey; label: string; right?: boolean }) => (
    <th onClick={() => toggleSort(k)}
      style={{ cursor: "pointer", textAlign: right ? "right" : "left", whiteSpace: "nowrap", userSelect: "none" }}>
      {label}{sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );

  const tiles = [
    { label: "Sites", value: stats.total, color: "var(--text)" },
    { label: "Extremely High", value: stats.extreme, color: "var(--risk-4)" },
    { label: "High", value: stats.high, color: "var(--risk-3)" },
    { label: "Avg overall", value: stats.avg === null ? "–" : stats.avg.toFixed(2), color: "var(--accent)" },
    { label: "No data", value: stats.nodata, color: "var(--faint)" },
  ];

  return (
    <div className="portfolio">
      <div className="pf-inner">
        <div className="pf-head">
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>Portfolio risk register</h1>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              Every facility ranked by modelled water risk · click a row to open it on the map
            </div>
          </div>
        </div>

        <div className="pf-tiles">
          {tiles.map((t) => (
            <div key={t.label} className="stat-tile">
              <div className="num" style={{ fontSize: 26, fontWeight: 700, color: t.color }}>{t.value}</div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{t.label}</div>
            </div>
          ))}
        </div>

        <div className="pf-toolbar">
          <input type="text" placeholder="Filter by name…" value={query}
            onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 260 }} />
          <div className="pf-chips">
            {([["all", "All"], ["worst", "Worst 10"], ["high", "High +"], ["extreme", "Extremely High"], ["nodata", "No data"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setFilter(k)}
                className={filter === k ? "primary" : ""} style={{ fontSize: 11, padding: "5px 11px" }}>{l}</button>
            ))}
          </div>
          <div style={{ flex: 1 }} />
          <button onClick={() => fileRef.current?.click()} style={{ fontSize: 12 }}>⬆ Import CSV</button>
          <button onClick={exportCsv} style={{ fontSize: 12 }}>⬇ Export CSV</button>
          <input ref={fileRef} type="file" accept=".csv" style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv(f); e.currentTarget.value = ""; }} />
        </div>

        {(importing || importLog.length > 0) && (
          <div className="pf-import glass">
            {importing && (
              <>
                <div style={{ fontSize: 12, marginBottom: 6 }}>
                  Importing {importing.done + 1}/{importing.total}: <b>{importing.label}</b>
                  <span style={{ color: "var(--faint)" }}> — new basins take ~1–2 min each (live satellite series)</span>
                </div>
                <div className="pf-progress">
                  <div style={{ width: `${(importing.done / importing.total) * 100}%` }} />
                </div>
              </>
            )}
            {importLog.length > 0 && (
              <div style={{ maxHeight: 120, overflowY: "auto", fontSize: 11, marginTop: 8, lineHeight: 1.6 }}>
                {importLog.map((l, i) => (
                  <div key={i} style={{ color: l.startsWith("✓") ? "var(--text)" : "var(--risk-3)" }}>{l}</div>
                ))}
                {!importing && <button onClick={() => setImportLog([])} style={{ marginTop: 6, fontSize: 11 }}>Dismiss</button>}
              </div>
            )}
          </div>
        )}

        <div className="pf-tablewrap">
          <table className="pf-table">
            <thead>
              <tr>
                <Th k="name" label="Site" />
                <th style={{ textAlign: "left" }}>Basin</th>
                <Th k="overall" label="Overall" right />
                <th style={{ textAlign: "left" }}>Level</th>
                <Th k="bws" label="Water stress" right />
                <Th k="flood" label="Flood" right />
                <Th k="drr" label="Drought" right />
                <Th k="gtd" label="Groundwater" right />
                <Th k="f2050" label="Scarcity 2050" right />
                <Th k="delta" label="Δ" right />
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.site.id} onClick={() => onDrill(r.site)}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.site.name}</div>
                    <div style={{ fontSize: 10, color: "var(--faint)" }}>{r.site.id} · {r.site.lat.toFixed(2)}, {r.site.lng.toFixed(2)}</div>
                  </td>
                  <td style={{ color: "var(--muted)", fontSize: 11 }} className="num">{r.site.pfaf_id ?? "—"}</td>
                  <td style={{ textAlign: "right" }}><Score v={r.overall} dp={2} /></td>
                  <td style={{ fontSize: 11, color: "var(--muted)" }}>{r.level ?? "no data"}</td>
                  <td style={{ textAlign: "right" }}><Score v={r.bws} /></td>
                  <td style={{ textAlign: "right" }}><Score v={r.flood} /></td>
                  <td style={{ textAlign: "right" }}><Score v={r.drr} /></td>
                  <td style={{ textAlign: "right" }}><Score v={r.gtd} /></td>
                  <td style={{ textAlign: "right" }}><Score v={r.f2050} /></td>
                  <td style={{ textAlign: "right" }} className="num">
                    {r.delta === null ? <span style={{ color: "var(--faint)" }}>—</span> :
                      <span style={{ color: r.delta > 0 ? "var(--risk-3)" : r.delta < 0 ? "var(--risk-0)" : "var(--muted)", fontSize: 12 }}>
                        {r.delta > 0 ? "▲" : r.delta < 0 ? "▼" : ""}{Math.abs(r.delta).toFixed(2)}
                      </span>}
                  </td>
                </tr>
              ))}
              {view.length === 0 && (
                <tr><td colSpan={10} style={{ textAlign: "center", padding: 40, color: "var(--faint)" }}>
                  No sites match. {rows.length === 0 ? "Import a CSV or add a site on the map to begin." : "Clear the filter to see all sites."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 10 }}>
          Scores at WRI Aqueduct basin resolution. Δ = 2050 BAU water-stress projection minus today (WRI projects
          scarcity only; flood/drought/groundwater stay at baseline). Groundwater "n/d" is genuine no-data, never 0.
        </div>
      </div>
    </div>
  );
}
