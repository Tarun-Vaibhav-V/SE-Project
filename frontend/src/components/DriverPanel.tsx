import { useEffect, useState } from "react";
import { getDrivers, explain } from "../lib/data";
import type { Site } from "../lib/data";
import { CONFIDENCE_COLORS } from "../lib/risk";

/** Explainability panel: attribution bars + confidence chips + grounded narrative.
 * Every number shown comes from the driver JSON; the narrative is server-validated
 * (Groq + numeral check) with a deterministic template fallback. */
export default function DriverPanel({ site, risk, onClose }: { site: Site; risk: string; onClose: () => void }) {
  const [data, setData] = useState<any | null | undefined>(undefined); // undefined = loading
  const [story, setStory] = useState<{ narrative: string; engine: string } | null>(null);

  useEffect(() => {
    setData(undefined); setStory(null);
    getDrivers(site.id, risk, site.lat, site.lng).then((d) => {
      setData(d);
      if (d) explain(risk, d).then(setStory);
    });
  }, [site.id, risk]);

  const att: [string, number][] = data?.attribution_pct
    ? Object.entries(data.attribution_pct as Record<string, number>).sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div className="driver-panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontWeight: 700, textTransform: "capitalize" }}>{risk} drivers — {site.name}</div>
        <button onClick={onClose} style={{ padding: "2px 9px" }} aria-label="close">×</button>
      </div>

      {data === undefined && <div style={{ color: "var(--muted)", fontSize: 12 }}>computing / fetching cache…</div>}
      {data === null && (
        <div style={{ color: "var(--faint)", fontSize: 12 }}>
          No cached drivers and the compute API is unreachable. Run backend/seed.py or start the FastAPI service.
        </div>
      )}

      {data && (
        <>
          <div style={{ fontSize: 12, marginBottom: 10 }}>
            modelled hazard <b className="num" style={{ fontSize: 16 }}>{data.hazard_0_5 ?? "n/d"}</b> /5
            <span style={{ color: "var(--faint)", marginLeft: 8, fontSize: 10 }}>
              {data.attribution_note ?? "estimated contribution to the modelled score"}
            </span>
          </div>

          {risk === "flood" && (
            <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 10, padding: "6px 8px", border: "1px solid var(--border)", borderRadius: 8, lineHeight: 1.5 }}>
              Framework: <b>Risk = Hazard × Exposure × Vulnerability</b>. These bars decompose the
              modelled <b>Hazard</b> term; the urbanization driver (GHSL built-up fraction) doubles as
              the <b>Exposure</b> proxy. Site-level Vulnerability (drainage capacity, defenses) needs
              site data — disclosed, not invented.
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {att.map(([k, pct]) => {
              const drv = data.drivers?.[k] ?? {};
              return (
                <div key={k} title={`source: ${drv.source ?? "?"}`}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                    <span>{k.replace(/_/g, " ")}</span>
                    <span>
                      <span className="num">{pct}%</span>
                      <span className="pill" style={{
                        marginLeft: 6, padding: "1px 8px", fontSize: 9,
                        border: `1px solid ${CONFIDENCE_COLORS[drv.confidence] ?? "var(--border)"}`,
                        color: CONFIDENCE_COLORS[drv.confidence] ?? "var(--muted)",
                      }}>
                        {drv.confidence ?? "?"}
                      </span>
                    </span>
                  </div>
                  <div style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3 }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 3 }} />
                  </div>
                </div>
              );
            })}
          </div>

          {(data.excluded?.length ?? 0) > 0 && (
            <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 8 }}>
              excluded (no-data): {data.excluded.join(", ")}
            </div>
          )}

          <div style={{ marginTop: 12, padding: 10, background: "rgba(255,255,255,0.04)", borderRadius: 8, fontSize: 12, lineHeight: 1.5 }}>
            {story ? (
              <>
                {story.narrative}
                <div style={{ fontSize: 9, color: "var(--faint)", marginTop: 6 }}>
                  narrative: {story.engine === "groq" ? "Groq LLM (numeral-validated against computed data)" : "deterministic template from computed data"}
                </div>
              </>
            ) : (
              <span style={{ color: "var(--muted)" }}>generating grounded narrative…</span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
