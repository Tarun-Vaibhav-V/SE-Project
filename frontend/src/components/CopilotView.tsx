import { useState, useRef, useEffect } from "react";
import { sendChatMessage } from "../lib/data";
import "../styles/copilot.css";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: any[];
  trace?: any[];
  error?: string;
}

const DEMO_QS = [
  "Which sites should I prioritise, and why?",
  "Which projects create the most impact?",
  "Which sites or projects are off-track and why?",
  "What does the AWS Standard require in the Implement step?",
];

export default function CopilotView() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [openTraces, setOpenTraces] = useState<Record<number, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSend = async (text: string) => {
    if (!text.trim() || loading) return;
    
    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const history = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const res = await sendChatMessage(text, history);
      
      const assistantMsg: Message = {
        role: "assistant",
        content: res.answer || "No response received.",
        citations: res.citations || [],
        trace: res.trace || [],
      };
      
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: Message = {
        role: "assistant",
        content: `⚠️ Failed to fetch response: ${err?.message || "Unknown error"}`,
        error: err?.message || "Error",
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const toggleTrace = (index: number) => {
    setOpenTraces((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  const clearChat = () => {
    setMessages([]);
    setOpenTraces({});
  };

  const formatMessageContent = (text: string) => {
    const lines = text.split("\n");
    return lines.map((line, idx) => {
      if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
        const content = line.trim().substring(2);
        return (
          <li key={idx} style={{ marginLeft: 16, marginBottom: 4 }}>
            {formatBold(content)}
          </li>
        );
      }
      if (/^\d+\.\s/.test(line.trim())) {
        const content = line.trim().replace(/^\d+\.\s/, "");
        return (
          <li key={idx} style={{ marginLeft: 16, marginBottom: 4, listStyleType: "decimal" }}>
            {formatBold(content)}
          </li>
        );
      }
      if (!line.trim()) {
        return <div key={idx} style={{ height: 8 }} />;
      }
      return (
        <p key={idx} style={{ marginBottom: 6 }}>
          {formatBold(line)}
        </p>
      );
    });
  };

  const formatBold = (text: string) => {
    const parts = text.split(/\*\*([^*]+)\*\*/g);
    return parts.map((part, index) => {
      if (index % 2 === 1) {
        return <strong key={index} style={{ color: "#fff", fontWeight: 600 }}>{part}</strong>;
      }
      return part;
    });
  };

  const renderCitations = (citations: any[]) => {
    if (!citations || citations.length === 0) return null;
    
    const chips: string[] = [];
    citations.forEach((c) => {
      let label = "";
      if (c.sheet) {
        label = c.sheet;
        if (c.data_status) {
          label += ` · ${c.data_status}`;
        }
      } else {
        label = `${c.source || "?"} ${c.locator || ""}`.trim();
      }
      if (label && !chips.includes(label)) {
        chips.push(label);
      }
    });

    return (
      <div className="copilot-citations">
        <div className="copilot-citation-title">📎 Sources & Citations:</div>
        {chips.map((chip, idx) => (
          <span key={idx} className="copilot-citation-chip">
            {chip}
          </span>
        ))}
      </div>
    );
  };

  return (
    <div className="copilot-container">
      <div className="copilot-sidebar">
        <div className="copilot-sidebar-title">
          <span>💧</span>
          <span>Hydris Copilot</span>
        </div>
        <div className="copilot-sidebar-desc">
          Stewardship analyst powered by grounded RAG. Analyzes the PepsiCo water stewardship data pack (19 sheets) and AWS Standard v3.0 methodology.
        </div>
        
        <div className="copilot-divider" />
        
        <div className="copilot-demo-header">Try a question</div>
        {DEMO_QS.map((q, idx) => (
          <button
            key={idx}
            className="copilot-demo-btn"
            onClick={() => handleSend(q)}
            disabled={loading}
          >
            {q}
          </button>
        ))}

        <button className="copilot-clear-btn" onClick={clearChat}>
          Clear conversation
        </button>
      </div>

      <div className="copilot-chat-area">
        <div className="copilot-messages">
          {messages.length === 0 ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "var(--faint)", gap: 8 }}>
              <span style={{ fontSize: 32 }}>💧</span>
              <p style={{ fontSize: 13 }}>Ask any question about PepsiCo water risk, sites or AWS standards.</p>
              <p style={{ fontSize: 11 }}>Example: "Which sites or projects are off-track and why?"</p>
            </div>
          ) : (
            messages.map((m, idx) => (
              <div key={idx} className={`copilot-message ${m.role}`}>
                <div className="copilot-bubble">
                  {m.role === "assistant" ? formatMessageContent(m.content) : m.content}
                  
                  {m.role === "assistant" && renderCitations(m.citations || [])}
                  
                  {m.role === "assistant" && m.trace && m.trace.length > 0 && (
                    <div className="copilot-trace-container">
                      <div className="copilot-trace-header" onClick={() => toggleTrace(idx)}>
                        <span>🔍 Reasoned via {m.trace.length} tool call(s)</span>
                        <span>{openTraces[idx] ? "▲" : "▼"}</span>
                      </div>
                      {openTraces[idx] && (
                        <div className="copilot-trace-body">
                          {m.trace.map((step, sIdx) => {
                            const hasError = step.result && step.result.error;
                            return (
                              <div key={sIdx} className={`copilot-trace-step ${hasError ? "copilot-trace-error" : ""}`}>
                                <div className="copilot-trace-step-title">
                                  {step.tool}
                                </div>
                                {step.args && Object.keys(step.args).length > 0 && (
                                  <div className="copilot-trace-step-args">
                                    Args: {JSON.stringify(step.args)}
                                  </div>
                                )}
                                <div className="copilot-trace-step-result">
                                  {hasError ? step.result.error : JSON.stringify(step.result, null, 2)}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div className="copilot-message-meta">
                  <span>{m.role === "user" ? "You" : "Copilot"}</span>
                </div>
              </div>
            ))
          )}

          {loading && (
            <div className="copilot-message assistant">
              <div className="copilot-loader">
                <div className="copilot-pulse" />
                <span>Reasoning over the portfolio…</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="copilot-input-container">
          <input
            type="text"
            placeholder="Ask about the portfolio, sites, projects, or AWS standard..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend(input)}
            disabled={loading}
          />
          <button
            className="primary copilot-send-btn"
            onClick={() => handleSend(input)}
            disabled={loading || !input.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
