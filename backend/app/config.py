"""Central configuration and paths for the Hydris Stewardship Copilot."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# --- Paths -------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BUILD_DIR = ROOT / "build"
BUILD_DIR.mkdir(exist_ok=True)

XLSX_PATH = DATA_DIR / "portfolio.xlsx"
PDF_PATHS = [
    DATA_DIR / "AWS_Standard-3.0_2026-_English.pdf",
    DATA_DIR / "AWS-Std.-V3.0-Guidance_FINAL_May-2026.pdf",
    DATA_DIR / "COMPENDIUM-OF-BEST-PRACTICES-IN-WATER-MANAGEMENT-3.0_Water-Resources-Vertical_2_8_23.pdf",
    DATA_DIR / "Industrial_Water_Management_Strategies.pdf",
    DATA_DIR / "Integrated_water_management.pdf",
    DATA_DIR / "volumetric-water-benefit-accounting-2-0.pdf",
    DATA_DIR / "FINAL_GUIDEBOOK_WQBA_WRI-LimnoTech-TNC.pdf",
]

DB_PATH = BUILD_DIR / "portfolio.db"
MANIFEST_PATH = BUILD_DIR / "manifest.json"
FAISS_INDEX_PATH = BUILD_DIR / "vectors.faiss"
CHUNKS_PATH = BUILD_DIR / "chunks.json"

print("entry")
try:
    # Load .env from the root directory (hydris rag)
    load_dotenv(ROOT / ".env")
except Exception:  # dotenv optional at import time
    pass

# --- Models ------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")
EMBED_MODEL = os.getenv("EMBED_MODEL")

# --- Retrieval knobs ---------------------------------------------------
CHUNK_CHARS = 1100          # target chunk size for PDF text
CHUNK_OVERLAP = 150
TOP_K = 5                   # semantic results returned to the model
