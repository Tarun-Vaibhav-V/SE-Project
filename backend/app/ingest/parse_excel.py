"""Parse the 19-sheet PepsiCo water-stewardship workbook into:

  1. a clean SQLite DB  (one table per sheet)  -> deterministic analytic queries
  2. a manifest.json     (sheet -> table meta)  -> so tools/UI know what exists

Every sheet keeps its 'Data Status' / 'Source' / 'Confidence' columns so answers
built on this data can be cited and marked Sourced vs Illustrative.

Design: the workbook is semi-structured (title + subtitle rows, then a header
row, then data, sometimes a trailing TOTAL row and side legends).  A generic
detector finds the header row and the data block, then columns that are blank
or junk (numeric/None headers, all-empty legend columns) are dropped.
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path

import openpyxl

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.config import XLSX_PATH, DB_PATH, MANIFEST_PATH


# Sheets where a side-legend sits to the right of the real table: cap columns.
MAX_COLS = {
    "03 Basin Risk": 12,   # Site..Overall Risk Score; drops the rating-scale legend
}


def slugify(name: str) -> str:
    """'02 Site Portfolio' -> 'site_portfolio'."""
    name = re.sub(r"^\s*\d+\s*", "", name)          # drop leading sheet number
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    name = re.sub(r"_+", "_", name)
    return name or "sheet"


def _norm_col(val, idx: int) -> str:
    if val is None:
        return f"col_{idx}"
    s = str(val).strip()
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s or f"col_{idx}"


def _is_header_row(row) -> bool:
    """A header row has >=3 non-null cells that are mostly short text labels."""
    cells = [c for c in row if c is not None and str(c).strip()]
    if len(cells) < 3:
        return False
    texty = sum(1 for c in cells if isinstance(c, str))
    return texty >= max(3, int(0.6 * len(cells)))


def detect_table(rows: list[tuple]):
    """Return (header_row_index, header_labels, data_rows) or None."""
    for i in range(min(6, len(rows))):          # header is within first few rows
        row = rows[i]
        if i < 2:                               # rows 0-1 are title/subtitle
            continue
        if _is_header_row(row) and i + 1 < len(rows):
            below = [c for c in rows[i + 1] if c is not None and str(c).strip()]
            if len(below) >= 2:
                return i, row
    # fallback: first row (>=2) that looks like a header at all
    for i in range(2, min(8, len(rows))):
        if _is_header_row(rows[i]):
            return i, rows[i]
    return None


def clean_dataframe(rows, header_idx, header, max_cols=None):
    ncol = len(header) if max_cols is None else min(len(header), max_cols)
    header = header[:ncol]
    labels = [_norm_col(header[j], j) for j in range(ncol)]

    data = []
    for r in rows[header_idx + 1:]:
        vals = list(r) + [None] * (ncol - len(r))
        vals = vals[:ncol]
        if all(v is None or str(v).strip() == "" for v in vals):
            break                                # blank row ends the table
        data.append(vals)

    # Drop columns that are junk: numeric-only header AND empty data, or fully empty
    keep = []
    for j in range(ncol):
        col_vals = [row[j] for row in data]
        non_null = [v for v in col_vals if v is not None and str(v).strip() != ""]
        header_is_texty = isinstance(header[j], str) and header[j].strip() != ""
        # A real data column in this workbook always has a non-empty TEXT header.
        if not header_is_texty:
            continue                             # numeric/None header -> legend junk
        if not non_null:
            continue                             # empty column
        keep.append(j)

    labels = _dedupe([labels[j] for j in keep])
    data = [[row[j] for j in keep] for row in data]
    return labels, data


def _dedupe(labels):
    seen, out = {}, []
    for lab in labels:
        if lab in seen:
            seen[lab] += 1
            out.append(f"{lab}_{seen[lab]}")
        else:
            seen[lab] = 0
            out.append(lab)
    return out


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    manifest = {"sheets": []}

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        title = str(rows[0][0]) if rows[0] and rows[0][0] else sheet.title
        subtitle = ""
        if len(rows) > 1 and rows[1] and rows[1][0] and str(rows[1][0]).strip():
            # subtitle only if row1 is a single leading cell (not a header)
            if not _is_header_row(rows[1]):
                subtitle = str(rows[1][0]).strip()

        det = detect_table(rows)
        table = slugify(sheet.title)
        if det is None:
            manifest["sheets"].append({
                "sheet": sheet.title, "table": None, "title": title,
                "subtitle": subtitle, "columns": [], "n_rows": 0,
                "note": "no tabular block detected (narrative sheet)",
            })
            continue

        header_idx, header = det
        labels, data = clean_dataframe(rows, header_idx, header, MAX_COLS.get(sheet.title))

        # write to sqlite (all text; tools cast as needed)
        cols_sql = ", ".join(f'"{c}" TEXT' for c in labels)
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ({cols_sql})')
        placeholders = ", ".join("?" for _ in labels)
        conn.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',
            [[None if v is None else str(v) for v in row] for row in data],
        )

        manifest["sheets"].append({
            "sheet": sheet.title, "table": table, "title": title,
            "subtitle": subtitle, "columns": labels, "n_rows": len(data),
        })
        print(f"  {sheet.title:28s} -> {table:22s} {len(labels)} cols x {len(data)} rows")

    conn.commit()
    conn.close()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDB    -> {DB_PATH}")
    print(f"Manifest -> {MANIFEST_PATH}  ({len(manifest['sheets'])} sheets)")


if __name__ == "__main__":
    main()
