"""Build the semantic layer: chunk the AWS Standard PDFs + the workbook's
narrative sheets, embed them, and persist a FAISS index.

Citations: every chunk carries a human-readable `source` + `locator` so the
copilot can cite e.g. "AWS Standard v3.0, p.14" or "Workbook, 12 Supporting Docs".
"""
from __future__ import annotations
import re
from pathlib import Path

import openpyxl
from pypdf import PdfReader

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.config import PDF_PATHS, XLSX_PATH, CHUNK_CHARS, CHUNK_OVERLAP
from app.core import vectorstore

# Friendly source names for citation display
PDF_LABELS = {
    "AWS_Standard-3.0_2026-_English.pdf": "AWS Standard v3.0",
    "AWS-Std.-V3.0-Guidance_FINAL_May-2026.pdf": "AWS Standard v3.0 Guidance",
    "COMPENDIUM-OF-BEST-PRACTICES-IN-WATER-MANAGEMENT-3.0_Water-Resources-Vertical_2_8_23.pdf": "Compendium of Best Practices in Water Management 3.0",
    "Industrial_Water_Management_Strategies.pdf": "Industrial Water Management Strategies",
    "Integrated_water_management.pdf": "Integrated Water Management",
    "volumetric-water-benefit-accounting-2-0.pdf": "Volumetric Water Benefit Account 2.0",
    "FINAL_GUIDEBOOK_WQBA_WRI-LimnoTech-TNC.pdf": "Final Guidebook for WQBA"
}

# Workbook sheets that are narrative/context (best served by semantic search).
# The numeric/analytic sheets are handled by the SQL tools instead.
NARRATIVE_SHEETS = {
    "README", "12 Supporting Docs", "14 Confidence Score",
    "15 Recommendations", "01 Company Info",
}


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Paragraph-aware sliding window."""
    text = _clean(text)
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        # try to break on a paragraph/sentence boundary near the end
        window = text[start:end]
        brk = max(window.rfind("\n\n"), window.rfind(". "))
        if end < len(text) and brk > size * 0.5:
            end = start + brk + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - overlap, end) if end == len(text) else end - overlap
    return chunks


def pdf_chunks() -> list[dict]:
    out = []
    for path in PDF_PATHS:
        if not path.exists():
            print(f"  ! missing PDF: {path.name}")
            continue
        label = PDF_LABELS.get(path.name, path.name)
        reader = PdfReader(str(path))
        for pno, page in enumerate(reader.pages, start=1):
            txt = _clean(page.extract_text() or "")
            if len(txt) < 40:
                continue
            for j, ch in enumerate(chunk_text(txt, CHUNK_CHARS, CHUNK_OVERLAP)):
                out.append({
                    "text": f"[{label}, p.{pno}] {ch}",
                    "source": label,
                    "locator": f"p.{pno}",
                    "kind": "standard",
                })
        print(f"  {label:32s} {len(reader.pages)} pages")
    return out


def workbook_narrative_chunks() -> list[dict]:
    out = []
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    for sheet in wb.worksheets:
        if sheet.title not in NARRATIVE_SHEETS:
            continue
        lines = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
        text = _clean("\n".join(lines))
        for ch in chunk_text(text, CHUNK_CHARS, CHUNK_OVERLAP):
            out.append({
                "text": f"[Workbook: {sheet.title}] {ch}",
                "source": "Portfolio Workbook",
                "locator": sheet.title,
                "kind": "workbook",
            })
    print(f"  workbook narrative sheets: {len(NARRATIVE_SHEETS)}")
    return out


def main():
    print("Chunking sources...")
    chunks = pdf_chunks() + workbook_narrative_chunks()
    for i, c in enumerate(chunks):
        c["id"] = i
    print(f"Total chunks: {len(chunks)}  ->  embedding with local model...")
    vectorstore.build(chunks)
    print(f"FAISS index + chunks written to build/")


if __name__ == "__main__":
    main()
