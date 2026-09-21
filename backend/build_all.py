"""One-command build of both retrieval layers.

    python build_all.py

Parses the workbook -> SQLite, then chunks+embeds the PDFs/narrative -> FAISS.
"""
from app.ingest import parse_excel, ingest_pdfs

if __name__ == "__main__":
    print("== 1/2  Parsing workbook -> SQLite ==")
    parse_excel.main()
    print("\n== 2/2  Building semantic index -> FAISS ==")
    ingest_pdfs.main()
    print("\nDone. Launch the copilot with:  streamlit run app/ui/streamlit_app.py")
