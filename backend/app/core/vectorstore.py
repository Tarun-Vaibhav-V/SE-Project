"""Local embedding + FAISS vector store.

Small corpus (a few hundred chunks), so a flat inner-product index over
L2-normalised vectors (= cosine similarity) is exact and instant.  The
embedding model runs locally (sentence-transformers), so no API key is
needed to build or query the semantic layer.
"""
from __future__ import annotations
import json
from pathlib import Path

import faiss
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.config import EMBED_MODEL, FAISS_INDEX_PATH, CHUNKS_PATH

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    vecs = get_model().encode(
        texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
    )
    return np.asarray(vecs, dtype="float32")


def build(chunks: list[dict]):
    """chunks: [{id, text, source, locator, kind}]  -> writes index + chunks.json"""
    vecs = embed([c["text"] for c in chunks])
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    faiss.write_index(index, str(FAISS_INDEX_PATH))
    CHUNKS_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return index


class VectorStore:
    """Loads the persisted index + chunk metadata for querying."""

    def __init__(self):
        self.index = faiss.read_index(str(FAISS_INDEX_PATH))
        self.chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))

    def search(self, query: str, k: int = 5) -> list[dict]:
        qv = embed([query])
        scores, idx = self.index.search(qv, k)
        out = []
        for score, i in zip(scores[0], idx[0]):
            if i < 0:
                continue
            c = dict(self.chunks[i])
            c["score"] = round(float(score), 4)
            out.append(c)
        return out
