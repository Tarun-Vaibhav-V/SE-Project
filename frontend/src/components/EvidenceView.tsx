import { useRef, useState } from "react";
import { fetchEvidenceDemo, analyzeEvidence, uploadEvidence } from "../lib/data";

/* PS5 — Evidence & Disclosure Agent. Ingest → Classify → Map → Gap-detect →
 * formula-verify claims (GEE recompute) → A–F grade → citation-backed CDP draft. */

const gapColor: Record<string, string> = { MISSING: "#d73027", EXPIRED: "#fc8d59", STALE: "#fed976" };
const gradeColor: Record<string, string> = { A: "#1a9850", B: "#66bd63", C: "#fed976", D: "#fc8d59", F: "#d73027" };
const statusColor: Record<string, string> = {
  verified: "#5bd08a", flagged: "#fc8d59", not_numerically_verifiable: "#fed976",
  insufficient_inputs: "var(--faint)",
};

export default function EvidenceView() {
  const [data, setData] = useState<any | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [docName, setDocName] = useState("");
  const [docText, setDocText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const runDemo = async () => {
    setBusy(true); setErr(null);
    const d = await fetchEvidenceDemo();
    setBusy(false);
    if (d) setData(d); else setErr("Pipeline unavailable — is the backend running?");
  };

  const runUpload = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setBusy(true); setErr(null);
    try {
      // Chennai coords let the GEE rainfall recompute run for the demo site
      const d = await uploadEvidence([...files], { id: "S1", name: "Chennai plant (IN)", lat: 13.0827, lng: 80.2707, pfaf_id: 453750 }, true);
      setData(d);
    } catch (e: any) { setErr(String(e?.message ?? e)); }
    finally { setBusy(false); }
  };

  const runPaste = async () => {
    if (!docText.trim()) return;
    setBusy(true); setErr(null);
    try {
      const d = await analyzeEvidence([{ name: docName.trim() || "pasted-document.txt", text: docText }],
        { id: "S1", name: "Chennai plant (IN)", lat: 13.0827, lng: 80.2707, pfaf_id: 453750 }, false);
      setData(d); setPasteOpen(false);
    } catch (e: any) { setErr(String(e?.message ?? e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="evidence">
      <div className="ev-inner">
        <div className="pwi-head">
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700 }}>Evidence & Disclosure Agent</h1>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              Ingest → Classify → Map → Gap-detect → formula-verify → grade → citation-backed CDP draft
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={() => fileRef.current?.click()} disabled={busy} style={{ fontSize: 12 }}>⬆ Upload documents</button>
            <button onClick={() => setPasteOpen(!pasteOpen)} style={{ fontSize: 12 }}>Paste text</button>
            <button className="primary" onClick={runDemo} disabled={busy} style={{ fontSize: 12 }}>
              {busy ? "Running…" : "Run sample documents"}
            </button>
            <input ref={fileRef} type="file" multiple accept=".pdf,.xlsx,.xlsm,.txt,.csv,.md"
              style={{ display: "none" }} onChange={(e) => { runUpload(e.target.files); e.currentTarget.value = ""; }} />
          </div>
        </div>

        {pasteOpen && (
          <div className="pwi-card">
            <div className="pwi-card-title">Analyze your own document text</div>
            <input type="text" placeholder="Document name (e.g. rainwater_harvesting_claim.pdf)" value={docName}
              onChange={(e) => setDocName(e.target.value)} style={{ marginBottom: 8 }} />
            <textarea className="ev-textarea" placeholder="Paste the document text here…" value={docText}
              onChange={(e) => setDocText(e.target.value)} />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button className="primary" onClick={runPaste} disabled={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
              <button onClick={() => setPasteOpen(false)}>Cancel</button>
            </div>
          </div>
        )}

        {err && <div style={{ color: "var(--risk-3)", fontSize: 12, marginBottom: 12 }}>{err}</div>}

        {data === undefined && !err && (
          <div className="pwi-card" style={{ color: "var(--faint)", fontSize: 13 }}>
            Upload permits, lab reports, WASH audits, water-balance records and intervention reports (PDF / xlsx / txt).
            The agent classifies each artefact, extracts metadata, maps it to CDP Water Security questions, flags gaps,
            <b> independently recomputes every intervention claim against its formula + GEE rainfall</b>, grades each
            claim A–F (capped by the formula's audited soundness), and drafts a citation-backed disclosure.
            Click <b>Run sample documents</b> to see it on labeled synthetic files.
          </div>
        )}

        {data && <Result data={data} />}
      </div>
    </div>
  );
}

function Result({ data }: { data: any }) {
  const s = data.summary;
  const g = data.grading;
  const draftEngine = data.draft?.engine;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        {data.data_grade === "SYNTHETIC-DEMO" && (
          <span className="pill" style={{ border: "1px solid var(--chip-proxy)", color: "var(--chip-proxy)" }}>SYNTHETIC DEMO — sample documents</span>
        )}
        {data.persisted && <span className="pill" style={{ border: "1px solid #1a9850", color: "#5bd08a" }}>✓ saved to Supabase</span>}
      </div>

      {/* degraded-LLM disclosure: quota exhaustion must never read as fraud */}
      {data.llm_status?.degraded && (
        <div style={{ border: "1px solid var(--chip-proxy)", borderRadius: 10, padding: "10px 14px", marginBottom: 12, fontSize: 12, lineHeight: 1.55 }}>
          <b style={{ color: "var(--chip-proxy)" }}>⚠ AI extraction degraded:</b> {data.llm_status.reason}.{" "}
          <span style={{ color: "var(--muted)" }}>{data.llm_status.impact}. Grades below reflect missing
          extraction parameters, not disproven claims — re-run when the AI quota resets.</span>
        </div>
      )}

      {/* grade banner + summary tiles */}
      <div className="ev-grade-row">
        <div className="ev-grade" style={{ borderColor: gradeColor[g?.cdp_grade] ?? "var(--border)" }}>
          <div className="num" style={{ fontSize: 46, fontWeight: 800, color: gradeColor[g?.cdp_grade] ?? "var(--text)" }}>{g?.cdp_grade ?? "—"}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>CDP disclosure grade</div>
        </div>
        <div className="pwi-tiles" style={{ gridTemplateColumns: "repeat(4, 1fr)", flex: 1, margin: 0 }}>
          <Tile v={s.documents} label="Documents" />
          <Tile v={`${s.answered}/${s.cdp_questions}`} label="CDP covered" color="#66bd63" />
          <Tile v={`${g?.verified_pct ?? 0}%`} label="Claims verified" color={(g?.verified_pct ?? 0) >= 50 ? "#66bd63" : "#fed976"} />
          <Tile v={s.gaps} label="Gaps" color={s.gaps ? "#fc8d59" : "#66bd63"} />
        </div>
      </div>

      {/* claim verification (the audit core) */}
      {data.claims?.length > 0 && (
        <div className="pwi-card">
          <div className="pwi-card-title">Claim verification — recompute vs GEE/formula</div>
          <div style={{ overflowX: "auto" }}>
            <table className="ev-table">
              <thead><tr>
                <th>Intervention</th><th>Formula soundness</th><th style={{ textAlign: "right" }}>Claimed</th>
                <th style={{ textAlign: "right" }}>Recomputed</th><th style={{ textAlign: "right" }}>Δ</th>
                <th>Status</th><th style={{ textAlign: "center" }}>Grade</th>
              </tr></thead>
              <tbody>
                {data.claims.map((c: any, i: number) => (
                  <tr key={i}>
                    <td>{c.intervention?.replace(/_/g, " ")}<div style={{ fontSize: 10, color: "var(--faint)" }}>{c.document}</div></td>
                    <td style={{ fontSize: 11 }}>{c.formula_soundness?.replace(/_/g, " ")}</td>
                    <td style={{ textAlign: "right" }} className="num">{fmt(c.claimed_value)}</td>
                    <td style={{ textAlign: "right" }} className="num">{c.recomputed_value == null ? "—" : fmt(c.recomputed_value)}</td>
                    <td style={{ textAlign: "right" }} className="num">{c.deviation_pct == null ? "—" : `${c.deviation_pct}%`}</td>
                    <td style={{ fontSize: 11, color: statusColor[c.status] ?? "var(--muted)" }}>
                      {(c.status || "").replace(/_/g, " ")}{c.direction ? ` (${c.direction})` : ""}
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <span className="ev-gradechip" style={{ background: gradeColor[c.grade] ?? "var(--faint)", color: c.grade === "C" ? "#141414" : "#fff" }}>{c.grade ?? "—"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 8 }}>
            Grade capped by formula soundness (weak formulas max C). Verified benefit feeding PWI:
            <b className="num"> {fmt(g?.verified_benefit_m3_yr)} m³/yr</b>. {g?.note}
          </div>
        </div>
      )}

      {/* classified artefacts */}
      <div className="pwi-card">
        <div className="pwi-card-title">Classified artefacts (extract)</div>
        {data.artefacts.map((a: any) => (
          <div key={a.name} className="ev-artefact">
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{a.type_label}
                <span style={{ fontSize: 10, color: "var(--faint)", fontWeight: 400 }}> · {a.name}</span></div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{metaLine(a)}</div>
            </div>
            <span className="pill" style={{ border: "1px solid var(--border-strong)", fontSize: 10 }}>
              {a.type_confidence}% · {a._engine === "groq" ? "AI" : "keyword"}</span>
          </div>
        ))}
      </div>

      {/* coverage map */}
      <div className="pwi-card">
        <div className="pwi-card-title">Evidence → CDP mapping</div>
        {Object.entries(data.coverage).map(([id, c]: [string, any]) => (
          <div key={id} className="ev-cov">
            <span style={{ color: c.covered ? "#5bd08a" : "var(--risk-3)", fontSize: 13 }}>{c.covered ? "✓" : "✗"}</span>
            <div style={{ flex: 1 }}>
              <b style={{ fontSize: 12 }}>{id}</b> <span style={{ fontSize: 11, color: "var(--muted)" }}>{c.question}</span>
              {c.documents.length > 0 && <div style={{ fontSize: 10, color: "var(--faint)" }}>← {c.documents.join(", ")}</div>}
            </div>
          </div>
        ))}
      </div>

      {/* gaps */}
      <div className="pwi-card">
        <div className="pwi-card-title">Gap detection</div>
        {data.gaps.length === 0 && <div style={{ fontSize: 12, color: "#5bd08a" }}>No gaps.</div>}
        {data.gaps.map((gp: any, i: number) => (
          <div key={i} className="ev-gap">
            <span className="pill" style={{ background: gapColor[gp.kind] ?? "var(--faint)", color: "#fff", fontSize: 10 }}>{gp.kind}</span>
            <span style={{ fontSize: 12 }}>{gp.detail}</span>
          </div>
        ))}
      </div>

      {/* draft */}
      <div className="pwi-card">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <span className="pwi-card-title" style={{ margin: 0 }}>Citation-backed CDP disclosure draft</span>
          <span className="pill" style={draftEngine === "groq"
            ? { border: "1px solid var(--chip-computed)", color: "var(--chip-computed)", fontSize: 10 }
            : { border: "1px solid var(--chip-proxy)", color: "var(--chip-proxy)", fontSize: 10 }}>
            {draftEngine === "groq" ? "AI-drafted (Groq)" : "template"}</span>
        </div>
        {(data.draft?.responses ?? []).map((r: any, i: number) => (
          <div key={i} className="ev-draft">
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)" }}>{r.cdp_id}</div>
            <div style={{ fontSize: 12, lineHeight: 1.6 }}>{r.text}</div>
            {r.citations?.length > 0 && (
              <div style={{ fontSize: 10, color: "var(--faint)", marginTop: 2 }}>
                cites: {r.citations.map((c: string, j: number) => <span key={j} className="ev-cite">{c}</span>)}</div>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10, color: "var(--faint)" }}>{data.disclaimer}</div>
    </>
  );
}

function Tile({ v, label, color }: { v: any; label: string; color?: string }) {
  return (
    <div className="stat-tile">
      <div className="num" style={{ fontSize: 24, fontWeight: 700, color: color ?? "var(--text)" }}>{v}</div>
      <div style={{ fontSize: 11, color: "var(--muted)" }}>{label}</div>
    </div>
  );
}

const fmt = (v: any) => (v == null ? "—" : Number(v).toLocaleString());

function metaLine(a: any): string {
  const bits: string[] = [];
  if (a.issuing_authority) bits.push(a.issuing_authority);
  if (a.doc_date) bits.push(`dated ${a.doc_date}`);
  if (a.validity_end) bits.push(`valid to ${a.validity_end}`);
  const p = a.parameters || {}, v = a.volumes_m3_yr || {};
  for (const [k, val] of Object.entries(p)) if (val != null) bits.push(`${k} ${val}`);
  for (const [k, val] of Object.entries(v)) if (val != null) bits.push(`${k} ${Number(val).toLocaleString()} m³/yr`);
  if (a.accredited) bits.push("accredited");
  return bits.join(" · ") || "no structured fields extracted";
}
