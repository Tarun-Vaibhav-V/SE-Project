"""Hydris Stewardship Copilot — Streamlit chat UI.

Run:  streamlit run app/ui/streamlit_app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.core.copilot import Copilot
from app.config import GROQ_API_KEY, GROQ_MODEL

st.set_page_config(page_title="Hydris Stewardship Copilot", page_icon="💧", layout="wide")

DEMO_QS = [
    "Which sites should I prioritise, and why?",
    "Which projects create the most impact?",
    "Which sites or projects are off-track and why?",
    "What does the AWS Standard require in the Implement step?",
]


@st.cache_resource
def get_copilot():
    return Copilot()


def render_citations(citations: list[dict]):
    if not citations:
        return
    chips = []
    for c in citations:
        if c.get("sheet"):
            label = c["sheet"]
            if c.get("data_status"):
                label += f" · {c['data_status']}"
        else:
            label = f"{c.get('source', '?')} {c.get('locator', '')}".strip()
        chips.append(label)
    st.caption("📎 Sources: " + "  •  ".join(dict.fromkeys(chips)))


def render_trace(trace: list[dict]):
    if not trace:
        return
    with st.expander(f"🔍 How the copilot reasoned ({len(trace)} tool call(s))"):
        for step in trace:
            st.markdown(f"**`{step['tool']}`**  `{step.get('args', {})}`")
            res = step.get("result", {})
            if isinstance(res, dict) and res.get("error"):
                st.error(res["error"])
            else:
                st.json(res, expanded=False)


# --- Sidebar -----------------------------------------------------------
with st.sidebar:
    st.title("💧 Hydris Copilot")
    st.caption("Stewardship Copilot · Problem Statement 04")
    st.markdown(
        "Grounded RAG over the **PepsiCo water-stewardship data pack** "
        "(19-sheet portfolio) and the **AWS Standard v3.0**. Every answer is cited."
    )
    st.divider()
    st.subheader("Try a question")
    for q in DEMO_QS:
        if st.button(q, use_container_width=True):
            st.session_state["pending"] = q
    st.divider()
    st.caption(f"Model: `{GROQ_MODEL}`")
    if not GROQ_API_KEY:
        st.warning("GROQ_API_KEY not set. Add it to `.env` to enable the copilot.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state["history"] = []
        st.rerun()

# --- Chat state --------------------------------------------------------
st.session_state.setdefault("history", [])   # display history [{role, content, citations, trace}]

st.title("Stewardship Copilot")

for turn in st.session_state["history"]:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn["role"] == "assistant":
            render_citations(turn.get("citations", []))
            render_trace(turn.get("trace", []))

# Handle a queued demo question or typed input
prompt = st.chat_input("Ask about the portfolio…")
if "pending" in st.session_state:
    prompt = st.session_state.pop("pending")

if prompt:
    st.session_state["history"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if not GROQ_API_KEY:
            st.error("GROQ_API_KEY not set — add it to `.env` and restart.")
        else:
            with st.spinner("Reasoning over the portfolio…"):
                # pass prior final answers as context (compact history)
                llm_history = [
                    {"role": t["role"], "content": t["content"]}
                    for t in st.session_state["history"][:-1]
                    if t["role"] in ("user", "assistant")
                ]
                try:
                    out = get_copilot().ask(prompt, history=llm_history)
                except Exception as e:
                    out = {"answer": f"⚠️ {type(e).__name__}: {e}", "citations": [], "trace": []}
            st.markdown(out["answer"])
            render_citations(out["citations"])
            render_trace(out["trace"])
            st.session_state["history"].append({
                "role": "assistant", "content": out["answer"],
                "citations": out["citations"], "trace": out["trace"],
            })
