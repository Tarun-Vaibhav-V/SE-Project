import { riskColor } from "../lib/risk";

/** One of the 13 indicator bars: thin track, 0–5 fill, value in mono text.
 * Identity is never color-alone: label + numeric value always visible. */
export default function MiniBar({ label, score }: { label: string; score: number | null }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "128px 1fr 44px", gap: 8, alignItems: "center" }}
      title={`${label}: ${score === null ? "no data" : score.toFixed(2)} / 5`}>
      <span style={{ fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {label}
      </span>
      <div style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
        {score !== null && (
          <div style={{ width: `${(Math.min(5, score) / 5) * 100}%`, height: "100%", background: riskColor(score), borderRadius: 3 }} />
        )}
      </div>
      <span className="num" style={{ fontSize: 11, textAlign: "right", color: score === null ? "var(--faint)" : "var(--text)" }}>
        {score === null ? "n/d" : score.toFixed(1)}
      </span>
    </div>
  );
}
