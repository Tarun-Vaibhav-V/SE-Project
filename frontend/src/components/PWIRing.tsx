import { riskColor } from "../lib/risk";

/** Ring gauge for one PWI dimension — 0–5 scale, color = risk step, value in mono.
 * No-data renders a dashed grey ring with an en-dash, never 0. */
export default function PWIRing({ label, score }: { label: string; score: number | null }) {
  const R = 26;
  const C = 2 * Math.PI * R;
  const frac = score === null ? 0 : Math.min(1, Math.max(0, score / 5));
  const color = riskColor(score);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <svg width="68" height="68" viewBox="0 0 68 68" role="img" aria-label={`${label}: ${score ?? "no data"}`}>
        <circle cx="34" cy="34" r={R} fill="none" stroke="rgba(255,255,255,0.1)"
          strokeWidth="6" strokeDasharray={score === null ? "3 5" : undefined} />
        {score !== null && (
          <circle cx="34" cy="34" r={R} fill="none" stroke={color} strokeWidth="6"
            strokeLinecap="round" strokeDasharray={`${frac * C} ${C}`}
            transform="rotate(-90 34 34)" />
        )}
        <text x="34" y="39" textAnchor="middle" fill="var(--text)"
          style={{ font: "700 15px var(--font-num)" }}>
          {score === null ? "–" : score.toFixed(1)}
        </text>
      </svg>
      <span style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.04em", textTransform: "uppercase" }}>
        {label}
      </span>
    </div>
  );
}
