"""SQLite helpers for the structured portfolio layer.

Exposes clean record access + a guarded read-only SELECT so the copilot can
run ad-hoc analytic queries without any risk of mutating the data.
"""
from __future__ import annotations
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.config import DB_PATH, MANIFEST_PATH


def connect() -> sqlite3.Connection:
    # read-only URI connection: mutations are impossible
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _table_index() -> dict:
    idx = {}
    for s in manifest()["sheets"]:
        if s["table"]:
            idx[s["table"]] = s
    return idx


def sheet_for(table: str) -> dict | None:
    """Citation metadata for a table -> its source sheet."""
    return _table_index().get(table)


def tables() -> list[str]:
    return list(_table_index().keys())


def records(table: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(f'SELECT * FROM "{table}"').fetchall()
    return [dict(r) for r in rows]


_SELECT_RE = re.compile(r"^\s*select\b", re.IGNORECASE)
_FORBID_RE = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace)\b", re.IGNORECASE)


def run_select(sql: str, limit: int = 200) -> list[dict]:
    """Execute a single read-only SELECT. Raises ValueError on anything else."""
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Only a single statement is allowed.")
    if not _SELECT_RE.match(sql) or _FORBID_RE.search(sql):
        raise ValueError("Only read-only SELECT queries are permitted.")
    with connect() as c:
        rows = c.execute(sql).fetchmany(limit)
    return [dict(r) for r in rows]


# --- value parsing -----------------------------------------------------
def to_num(val) -> float | None:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("%", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None
