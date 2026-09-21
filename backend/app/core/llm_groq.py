"""Thin Groq (OpenAI-compatible) tool-use loop.

Given messages + tool specs + a dispatch table, it runs the function-calling
loop until the model returns a final text answer, collecting a trace of every
tool call (used by the UI to show what the copilot did and to gather citations).
"""
from __future__ import annotations
import json
import re

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.config import GROQ_API_KEY, GROQ_MODEL

# Some models (notably Llama-on-Groq) occasionally emit a malformed call like
#   <function=search_standard{"query": "..."}</function>
# which Groq rejects with a 400 tool_use_failed. We salvage it by parsing the
# name + JSON args out of failed_generation and running the tool anyway.
_MALFORMED = re.compile(r"<function=(\w+)\s*(\{.*?\})?\s*>?", re.DOTALL)

_client = None


def client():
    global _client
    if _client is None:
        from groq import Groq
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def run(messages: list[dict], tool_specs: list[dict], dispatch: dict,
        model: str = None, max_steps: int = 6) -> dict:
    """Run the tool-use loop. Returns {answer, trace, messages}."""
    model = model or GROQ_MODEL
    trace = []
    cache: dict = {}                       # (name, args_json) -> result, avoids recompute on repeats

    def execute(name, args):
        key = (name, json.dumps(args, sort_keys=True, default=str))
        if key in cache:
            return cache[key]
        fn = dispatch.get(name)
        if fn is None:
            result = {"error": f"unknown tool '{name}'"}
        else:
            try:
                result = fn(**args)
            except Exception as e:         # never crash the loop on a bad tool call
                result = {"error": f"{type(e).__name__}: {e}"}
        cache[key] = result
        trace.append({"tool": name, "args": args, "result": result})
        return result

    from groq import BadRequestError
    for _ in range(max_steps):
        try:
            resp = client().chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_specs,
                tool_choice="auto",
                temperature=0.2,
            )
        except BadRequestError as e:
            # Salvage a malformed tool call, feed the result back, and continue.
            body = getattr(e, "body", None) or {}
            failed = (body.get("error", {}) or {}).get("failed_generation", "") if isinstance(body, dict) else ""
            m = _MALFORMED.search(failed or str(e))
            if not m:
                raise
            name = m.group(1)
            try:
                args = json.loads(m.group(2) or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute(name, args)
            messages.append({"role": "assistant", "content": "", "tool_calls": None})
            messages.append({"role": "user",
                             "content": f"[recovered tool result for {name}({args})]:\n"
                                        f"{json.dumps(result, default=str)[:12000]}\n"
                                        "Use ONLY this data; continue and answer with citations."})
            continue

        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        # Append assistant turn (with any tool calls)
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ] if calls else None,
        })
        if not calls:
            return {"answer": msg.content or "", "trace": trace, "messages": messages}

        # Execute each requested tool
        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": c.id,
                "name": name,
                "content": json.dumps(result, default=str)[:12000],
            })
    return {"answer": "(stopped: reached max tool steps)", "trace": trace, "messages": messages}
