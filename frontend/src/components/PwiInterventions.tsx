import { Fragment, useState, useEffect, useRef } from "react";
import { pwiRecommend, pwiChat } from "../lib/data";

/* AI intervention planner (brief steps 14–17). Lazy: fetches only when the user
 * clicks Generate. Renders a premium split roadmap + prioritized intervention grid
 * alongside an interactive conversational Advisor panel tailored for Apple/Nvidia-grade review. */

const priColor: Record<string, string> = { High: "#E74C3C", Medium: "#E67E22", Low: "#2ECC71" };
const priBg: Record<string, string> = {
  High: "rgba(231, 76, 60, 0.1)",
  Medium: "rgba(230, 126, 34, 0.1)",
  Low: "rgba(46, 204, 113, 0.1)",
};

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function PwiInterventions({ results, scope }: { results: any[]; scope: "site" | "portfolio" }) {
  const [data, setData] = useState<any | null | undefined>(undefined); // undefined=not run, null=failed
  const [busy, setBusy] = useState(false);

  // UI Navigation states
  const [activePhase, setActivePhase] = useState<number | "all">("all");
  const [showGuide, setShowGuide] = useState(false); // ⓘ priority & cost reference
  const [expanded, setExpanded] = useState<number | null>(null); // clicked row cascades its rationale below
  
  // Chat state
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const run = async () => {
    setBusy(true);
    const result = await pwiRecommend(results);
    setData(result);
    setBusy(false);

    if (result) {
      const siteName = results[0]?.site?.name || "the site";
      const startMsg = `Hello! I am your **Hydris PWI Strategic Advisor**.

I have compiled the Positive Water Impact strategy for **${siteName}**. Phase 1 targets Site-level (P1) quick wins, followed by Sub-basin (P2) and Basin-level (P3) action.

Ask me anything about the recommended timeline, cost allocations, or how to resolve any flagged cross-validation checks.`;
      setChatHistory([{ role: "assistant", content: startMsg }]);
    }
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, chatBusy]);

  const handleSend = async (messageText?: string) => {
    const text = messageText || chatInput;
    if (!text.trim() || chatBusy) return;

    if (!messageText) setChatInput("");
    const newHistory = [...chatHistory, { role: "user" as const, content: text }];
    setChatHistory(newHistory);
    setChatBusy(true);

    try {
      const answer = await pwiChat(text, newHistory, results);
      setChatHistory((prev) => [...prev, { role: "assistant" as const, content: answer }]);
    } catch {
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant" as const, content: "Sorry, I lost connection to the backend. Please verify your FastAPI service is running." }
      ]);
    } finally {
      setChatBusy(false);
    }
  };

  /** Icon per intervention family — visual anchor only; keyed on the catalog's
   * own wording, nothing generated. */
  const interventionIcon = (name: string): string => {
    const n = (name || "").toLowerCase();
    if (n.includes("replenish") || n.includes("recharge") || n.includes("nbs") || n.includes("reservoir")) return "🌊";
    if (n.includes("wwtp") || n.includes("treatment") || n.includes("effluent") || n.includes("recycl")) return "🏭";
    if (n.includes("efficien") || n.includes("meter") || n.includes("leak")) return "💧";
    if (n.includes("wash") || n.includes("sanitation") || n.includes("drinking")) return "🚰";
    if (n.includes("rain") || n.includes("harvest")) return "🌧️";
    if (n.includes("policy") || n.includes("coalition") || n.includes("advocacy") || n.includes("governance") || n.includes("stakeholder")) return "🤝";
    if (n.includes("monitor") || n.includes("sensor") || n.includes("data") || n.includes("audit")) return "📊";
    return "🛠️";
  };

  const sampleQuestions = [
    "Why is WWTP upgrade High priority?",
    "How does the water-efficiency program help?",
    "How do we fix the XV-05 feasibility penalty?",
    "What is the certification roadmap for this site?"
  ];

  if (data === undefined)
    return (
      <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "rgba(20, 20, 25, 0.6)", backdropFilter: "blur(12px)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, flexWrap: "wrap", padding: "12px 6px" }}>
          <div>
            <div className="pwi-card-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, letterSpacing: "-0.02em" }}>AI Intervention & Stewardship Strategy</div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4, lineHeight: 1.4 }}>
              Optimize positive water impact with customized engineering solutions mapped to your local river basin data.
            </div>
          </div>
          <button className="primary" onClick={run} disabled={busy} style={{ padding: "10px 20px", fontSize: 12, fontWeight: 600 }}>
            {busy ? "Analyzing Basin..." : "Generate Strategic Plan"}
          </button>
        </div>
      </div>
    );

  if (data === null)
    return (
      <div className="pwi-card" style={{ border: "1px solid rgba(231, 76, 60, 0.2)", background: "rgba(20, 20, 25, 0.6)" }}>
        <div style={{ fontSize: 12, color: "var(--faint)", padding: "12px 0", textAlign: "center" }}>
          PWI Advisor unavailable — Check if your FastAPI service is running on Port 8000. 
          <button className="primary" onClick={run} style={{ fontSize: 11, marginLeft: 12, padding: "5px 12px" }}>Retry Connection</button>
        </div>
      </div>
    );

  const recs = [...(data.recommendations ?? [])]
    .sort((a, b) => (a.phase ?? 9) - (b.phase ?? 9))
    .filter((r) => activePhase === "all" || r.phase === activePhase);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 20, margin: "20px 0" }}>
      
      {/* Top metadata header bar */}
      <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "var(--card-bg, rgba(20, 20, 25, 0.65))", padding: "14px 20px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="pwi-card-title" style={{ margin: 0, fontSize: 18, fontWeight: 700, letterSpacing: "-0.02em" }}>Water Stewardship Intervention Strategy</span>
              <span className="pill" style={data.engine === "groq"
                ? { border: "1px solid var(--chip-computed)", color: "var(--chip-computed)", background: "rgba(107, 174, 214, 0.06)", fontSize: 10 }
                : { border: "1px solid var(--chip-proxy)", color: "var(--chip-proxy)", background: "rgba(253, 141, 60, 0.06)", fontSize: 10 }}>
                {data.engine === "groq" ? "AI GROUNDED (Groq)" : "DETERMINISTIC CATALOG"}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
              Phased roadmap to positive water impact (threshold ≥100% on Availability, Quality, Access).
            </div>
          </div>
          <button onClick={run} disabled={busy} style={{ fontSize: 11, padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)" }}>
            {busy ? "Computing..." : "Re-Run Engine"}
          </button>
        </div>
      </div>

      {/* 1. Executive summary on top */}
      {data.narrative && (
        <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "rgba(255, 255, 255, 0.02)", padding: "14px 20px" }}>
          <div style={{ fontSize: 10.5, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600, marginBottom: 6 }}>
            Executive Summary
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.6 }}>{data.narrative}</div>
        </div>
      )}

      {/* 2. Phased roadmap + Chat Advisor — side by side */}
      <div className="pwi-int-grid">

          {/* Stepper Card */}
          <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "var(--card-bg, rgba(20, 20, 25, 0.65))" }}>
            <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600, marginBottom: 12 }}>
              Phased Implementation Roadmap
            </div>
            
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {/* "All" selector */}
              <button
                onClick={() => { setActivePhase("all"); setExpanded(null); }}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderRadius: 8,
                  border: activePhase === "all" ? "1px solid var(--accent)" : "1px solid var(--border)",
                  background: activePhase === "all" ? "rgba(33, 113, 181, 0.12)" : "rgba(255,255,255,0.02)",
                  color: activePhase === "all" ? "#fff" : "var(--muted)",
                  textAlign: "left", cursor: "pointer", fontSize: 12
                }}
              >
                <span><b>Show All Recommendations</b></span>
                <span className="num" style={{ fontSize: 11, background: "rgba(255,255,255,0.08)", padding: "2px 8px", borderRadius: 10 }}>
                  {data.recommendations?.length || 0}
                </span>
              </button>

              {data.roadmap?.map((p: any) => {
                const count = (data.recommendations ?? []).filter((r: any) => r.phase === p.phase).length;
                const isSelected = activePhase === p.phase;
                return (
                  <button 
                    key={p.phase}
                    onClick={() => { setActivePhase(p.phase); setExpanded(null); }}
                    style={{
                      display: "flex", flexDirection: "column", padding: "12px 14px", borderRadius: 8,
                      border: isSelected ? "1px solid var(--accent)" : "1px solid var(--border)",
                      background: isSelected ? "rgba(33, 113, 181, 0.12)" : "rgba(255,255,255,0.02)",
                      color: isSelected ? "#fff" : "var(--muted)",
                      textAlign: "left", cursor: "pointer"
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: isSelected ? "var(--accent)" : "var(--muted)" }}>
                        Phase {p.phase}
                      </span>
                      <span className="num" style={{ fontSize: 10, background: "rgba(255,255,255,0.06)", padding: "1px 6px", borderRadius: 8 }}>
                        {count} item(s)
                      </span>
                    </div>
                    <div style={{ fontSize: 12, fontWeight: 500, color: isSelected ? "#fff" : "var(--text)" }}>{p.focus}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Integrated Conversational Advisor */}
          <div className="pwi-card" style={{ 
            border: "1px solid rgba(255, 255, 255, 0.08)", 
            background: "var(--card-bg, rgba(20, 20, 25, 0.65))", 
            display: "flex", flexDirection: "column", height: 420 
          }}>
            <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600, borderBottom: "1px solid var(--border)", paddingBottom: 8, marginBottom: 8 }}>
              Hydris PWI Chat Advisor
            </div>

            {/* Messages box */}
            <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, paddingRight: 4, marginBottom: 12 }}>
              {chatHistory.map((m, idx) => (
                <div key={idx} style={{ 
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                  background: m.role === "user" ? "var(--accent)" : "rgba(255, 255, 255, 0.04)",
                  border: m.role === "user" ? "none" : "1px solid var(--border)",
                  borderRadius: 12,
                  padding: "8px 12px",
                  fontSize: 11.5,
                  lineHeight: 1.5,
                  color: m.role === "user" ? "#fff" : "var(--text)"
                }}>
                  <div style={{ whiteSpace: "pre-wrap" }}>
                    {m.content.split("\n").map((line, lIdx) => (
                      // React-escaped bold rendering — LLM/chat output must never
                      // reach the DOM as raw HTML (XSS via crafted **markup**)
                      <div key={lIdx} style={{ marginBottom: 4 }}>
                        {line.split(/\*\*([^*]+)\*\*/g).map((part, pIdx) =>
                          pIdx % 2 === 1 ? <strong key={pIdx}>{part}</strong> : part
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {chatBusy && (
                <div style={{ alignSelf: "flex-start", background: "rgba(255,255,255,0.03)", borderRadius: 12, padding: "8px 12px", fontSize: 11, color: "var(--muted)" }}>
                  Advisor is writing...
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Quick Questions suggestion bubbles */}
            <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 6, marginBottom: 6, flexShrink: 0 }}>
              {sampleQuestions.map((q, idx) => (
                <button 
                  key={idx} 
                  onClick={() => handleSend(q)} 
                  disabled={chatBusy}
                  style={{ 
                    whiteSpace: "nowrap", 
                    fontSize: 9.5, 
                    padding: "4px 10px", 
                    borderRadius: 12, 
                    border: "1px solid var(--border)", 
                    background: "rgba(255,255,255,0.02)", 
                    color: "var(--muted)",
                    cursor: "pointer"
                  }}
                >
                  {q}
                </button>
              ))}
            </div>

            {/* Input area */}
            <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
              <input 
                type="text" 
                placeholder="Ask Advisor about cost, timeline, or XV checks..." 
                value={chatInput} 
                onChange={(e) => setChatInput(e.target.value)} 
                onKeyDown={(e) => e.key === "Enter" && handleSend()}
                disabled={chatBusy}
                style={{ 
                  flex: 1, 
                  background: "rgba(0, 0, 0, 0.3)", 
                  border: "1px solid var(--border)", 
                  borderRadius: 6, 
                  color: "#fff", 
                  padding: "8px 12px", 
                  fontSize: 12 
                }}
              />
              <button 
                className="primary" 
                onClick={() => handleSend()} 
                disabled={chatBusy || !chatInput.trim()} 
                style={{ padding: "0 16px", fontSize: 12 }}
              >
                Send
              </button>
            </div>
          </div>
      </div>

      {/* 3. Recommended interventions — full width, below */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>

          {/* Header: count + ⓘ toggle for the priority/cost guide */}
          <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.06)", background: "rgba(255, 255, 255, 0.02)", padding: "12px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <div style={{ fontSize: 11, color: "#fff", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 700 }}>
                Recommended interventions
                <span className="num" style={{ marginLeft: 8, fontSize: 10, background: "rgba(255,255,255,0.08)", padding: "2px 8px", borderRadius: 10, letterSpacing: 0 }}>
                  {recs.length}
                </span>
              </div>
              <button className="pwi-ib" onClick={() => setShowGuide(!showGuide)}
                aria-expanded={showGuide} title="What do the priority levels and cost bands mean?">
                ⓘ Priority & cost guide {showGuide ? "▲" : "▼"}
              </button>
            </div>

            {showGuide && (
              <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 12 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 9.5, color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>Priority Levels</div>
                    <div style={{ fontSize: 11, borderLeft: "2.5px solid #E74C3C", paddingLeft: 8 }}>
                      <span style={{ color: "#E74C3C", fontWeight: 700 }}>HIGH PRIORITY</span>
                      <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>Immediate compliance, binary operational license threats, or critical local stress.</div>
                    </div>
                    <div style={{ fontSize: 11, borderLeft: "2.5px solid #E67E22", paddingLeft: 8 }}>
                      <span style={{ color: "#E67E22", fontWeight: 700 }}>MEDIUM PRIORITY</span>
                      <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>Volumetric replenishment (NBS) or local employee household WASH needs.</div>
                    </div>
                    <div style={{ fontSize: 11, borderLeft: "2.5px solid #2ECC71", paddingLeft: 8 }}>
                      <span style={{ color: "#2ECC71", fontWeight: 700 }}>LOW PRIORITY</span>
                      <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>Long-term policy alignment, basin coalitions, and advocacy platforms.</div>
                    </div>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 9.5, color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>Cost Band Classification</div>
                    <div style={{ fontSize: 10.5, lineHeight: 1.45, color: "var(--text)" }}>
                      <div>• <b>Low cost</b>: &lt; $10k USD <span style={{ color: "var(--muted)" }}>(e.g. metering, simple fixtures, training)</span></div>
                      <div>• <b>Low-Medium cost</b>: $10k - $50k USD <span style={{ color: "var(--muted)" }}>(e.g. leak audits, minor piping)</span></div>
                      <div>• <b>Medium cost</b>: $50k - $250k USD <span style={{ color: "var(--muted)" }}>(e.g. filters, local community WASH)</span></div>
                      <div>• <b>Medium-High cost</b>: $250k - $1M USD <span style={{ color: "var(--muted)" }}>(e.g. WWTP biological upgrades)</span></div>
                      <div>• <b>High cost</b>: &gt; $1M USD <span style={{ color: "var(--muted)" }}>(e.g. massive basin-recharge reservoirs)</span></div>
                    </div>
                  </div>
                </div>
                <div style={{ fontSize: 9.5, color: "var(--faint)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  All estimates align with the corporate Alliance for Water Stewardship (AWS) Standard guidelines.
                </div>
              </div>
            )}
          </div>

          {/* Interventions table — hover (or click) a row for the full rationale */}
          {recs.length === 0 ? (
            <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "var(--card-bg, rgba(20, 20, 25, 0.65))", padding: "40px", textAlign: "center" }}>
              <div style={{ color: "var(--faint)", fontSize: 13 }}>No interventions found for the active filter.</div>
            </div>
          ) : (
            <div className="pwi-card" style={{ border: "1px solid rgba(255, 255, 255, 0.08)", background: "var(--card-bg, rgba(20, 20, 25, 0.65))", padding: 0, overflow: "hidden", minWidth: 0 }}>
              <div style={{ overflowX: "auto", minWidth: 0 }}>
                <table className="pwi-int-table">
                  <thead>
                    <tr>
                      <th>Intervention</th>
                      <th>Priority</th>
                      <th>Phase</th>
                      <th>Scope</th>
                      <th>Timeline</th>
                      <th>Cost</th>
                      <th style={{ textAlign: "right" }}>Impact</th>
                      <th style={{ textAlign: "right" }}>Conf.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recs.map((r: any, i: number) => (
                      <Fragment key={i}>
                        <tr
                          className={expanded === i ? "expanded" : ""}
                          style={{ borderLeft: `3px solid ${priColor[r.priority] || "var(--border)"}` }}
                          aria-expanded={expanded === i}
                          onClick={() => setExpanded(expanded === i ? null : i)}>
                          <td style={{ whiteSpace: "nowrap" }}>
                            <span className="pwi-int-caret">{expanded === i ? "▾" : "▸"}</span>
                            <span style={{ margin: "0 7px" }}>{interventionIcon(r.intervention)}</span>
                            <span style={{ fontWeight: 600, color: "#fff", whiteSpace: "normal" }}>{r.intervention}</span>
                          </td>
                          <td>
                            <span className="pill" style={{
                              background: priBg[r.priority] || "rgba(255,255,255,0.06)",
                              color: priColor[r.priority] || "#fff",
                              border: `1px solid ${priColor[r.priority] || "var(--border)"}`,
                              fontSize: 9, fontWeight: 700, padding: "1px 7px",
                            }}>
                              {(r.priority ?? "unranked").toUpperCase()}
                            </span>
                          </td>
                          <td className="num">P{r.phase ?? "?"}</td>
                          <td style={{ whiteSpace: "nowrap", color: "var(--muted)", fontSize: 11 }}>{r.pillar} {r.dimension}</td>
                          <td className="num" style={{ whiteSpace: "nowrap" }}>{r.duration}</td>
                          <td style={{ whiteSpace: "nowrap" }}>{r.cost_band}</td>
                          <td className="num" style={{ textAlign: "right", color: "#2ECC71", fontWeight: 600 }}>+{r.est_pwi_gain_pct ?? "?"}%</td>
                          <td className="num" style={{ textAlign: "right", color: "var(--faint)" }}>{r.confidence}%</td>
                        </tr>
                        {expanded === i && (
                          <tr className="pwi-int-detailrow">
                            <td colSpan={8} style={{ borderLeft: `3px solid ${priColor[r.priority] || "var(--border)"}` }}>
                              <div className="pwi-int-detail">
                                <div style={{ marginBottom: 6 }}>
                                  <span style={{ color: "var(--muted)", fontWeight: 600 }}>The Challenge: </span>
                                  {r.problem || r.rationale}
                                </div>
                                {r.solution_brief && (
                                  <div style={{ marginBottom: 6 }}>
                                    <span style={{ color: "var(--muted)", fontWeight: 600 }}>Strategic Action: </span>
                                    {r.solution_brief}
                                  </div>
                                )}
                                {r.priority_rationale && (
                                  <div style={{ padding: "6px 10px", borderRadius: 4, background: "rgba(255,255,255,0.03)", borderLeft: `2px solid ${priColor[r.priority] || "var(--border)"}`, fontSize: 11 }}>
                                    <span style={{ fontWeight: 600 }}>Priority Logic: </span>{r.priority_rationale}
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ fontSize: 10, color: "var(--faint)", padding: "8px 14px", borderTop: "1px solid var(--border)" }}>
                Click a row to expand the full challenge → action → priority rationale · click again to collapse
              </div>
            </div>
          )}

        </div>

      {/* Footer disclaimer */}
      <div style={{ fontSize: 9.5, color: "var(--faint)", textAlign: "center", marginTop: 4 }}>
        {data.disclaimer}
      </div>
    </div>
  );
}
