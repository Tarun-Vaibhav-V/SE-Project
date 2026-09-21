import { useEffect, useState } from "react";
import { fetchNews } from "../lib/data";
import type { Site } from "../lib/data";

const SENT_COLOR: Record<string, string> = {
  negative: "var(--risk-3)", neutral: "var(--muted)", positive: "#27AE60",
};

/** Local signals: news clippings near the site, focused on its HIGHEST-scoring
 * risk, sentiment-tagged, with government-action items flagged. Clippings are
 * verbatim from NewsAPI; tags/summary derive only from those items. */
export default function NewsPanel({ site, onClose }: { site: Site; onClose: () => void }) {
  const [data, setData] = useState<any | null | undefined>(undefined);

  useEffect(() => {
    setData(undefined);
    fetchNews(site.lat, site.lng, site.pfaf_id).then(setData);
  }, [site.id]);

  return (
    <div>
      <div className="popup-header">
        <b>Local signals — {site.name}</b>
        <button onClick={onClose} style={{ padding: "2px 9px" }}>×</button>
      </div>

      {data === undefined && <div style={{ color: "var(--muted)", fontSize: 12 }}>fetching local news…</div>}
      {data === null && <div style={{ color: "var(--faint)", fontSize: 12 }}>News service unreachable (compute API must be running).</div>}
      {data?.error && <div style={{ color: "var(--faint)", fontSize: 12 }}>NewsAPI: {data.error}</div>}

      {data?.items && (
        <>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 8 }}>
            near <b>{data.place}</b> · focus: <b style={{ textTransform: "capitalize" }}>{data.risk}</b> (site's highest risk)
            {data.engine === "groq" && " · AI-tagged"}
          </div>
          {data.summary && (
            <div style={{ padding: 8, background: "rgba(255,255,255,0.04)", borderRadius: 8, fontSize: 12, marginBottom: 10, lineHeight: 1.5 }}>
              {data.summary}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.items.length === 0 && (
              <div style={{ fontSize: 11, color: "var(--faint)" }}>No recent local water-risk coverage found.</div>
            )}
            {data.items.map((it: any, i: number) => (
              // only http(s) links — never let an upstream item smuggle a javascript: URL
              <a key={i} href={/^https?:\/\//i.test(it.url ?? "") ? it.url : undefined}
                target="_blank" rel="noreferrer noopener"
                style={{ textDecoration: "none", color: "var(--text)", padding: 8, borderRadius: 8, border: "1px solid var(--border)", display: "block" }}>
                <div style={{ fontSize: 12, lineHeight: 1.4 }}>{it.title}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 5, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="pill" style={{ fontSize: 9, padding: "1px 8px", border: `1px solid ${SENT_COLOR[it.sentiment] ?? "var(--border)"}`, color: SENT_COLOR[it.sentiment] ?? "var(--muted)" }}>
                    {it.sentiment ?? "?"}
                  </span>
                  {it.gov_action && (
                    <span className="pill" style={{ fontSize: 9, padding: "1px 8px", border: "1px solid var(--chip-computed)", color: "var(--chip-computed)" }}>
                      gov action
                    </span>
                  )}
                  <span style={{ fontSize: 9, color: "var(--faint)" }}>
                    {it.source} · {(it.publishedAt || "").slice(0, 10)}
                  </span>
                </div>
              </a>
            ))}
          </div>
          <div style={{ fontSize: 9, color: "var(--faint)", marginTop: 8 }}>{data.note}</div>
        </>
      )}
    </div>
  );
}
