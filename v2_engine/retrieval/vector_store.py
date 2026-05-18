"""
v2_engine.retrieval.vector_store — dense FAISS index over dossier prose.

Built from V1's ``semantic_memory.db`` by ``memory_v2/migration_from_v1.py``.
Index lives at ``cfg.V2_FAISS_INDEX``. Embeddings produced by the model in
``cfg.V2_EMBEDDING_MODEL`` (default: ``sentence-transformers/all-MiniLM-L6-v2``).

The store is read-only at query time. Re-builds are incremental — see
``memory_v2/migration_from_v1.py``.
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

from v2_engine import config as cfg


_INDEX_CACHE: dict[str, Any] = {}


def _lazy_index():
    """Load FAISS index + tickers list on first use."""
    if "index" in _INDEX_CACHE:
        return _INDEX_CACHE
    path = Path(cfg.V2_FAISS_INDEX)
    meta = path.with_suffix(".meta.pkl")
    if not (path.exists() and meta.exists()):
        return None
    try:
        import faiss  # type: ignore
        idx = faiss.read_index(str(path))
        with meta.open("rb") as f:
            tickers, dossiers = pickle.load(f)
        _INDEX_CACHE["index"] = idx
        _INDEX_CACHE["tickers"] = tickers
        _INDEX_CACHE["dossiers"] = dossiers
        return _INDEX_CACHE
    except Exception as e:
        print(f"vector_store: failed to load FAISS index: {e}")
        return None


def _embed(query: str) -> list[float]:
    """Encode query with the same model that built the index."""
    try:
        from sentence_transformers import SentenceTransformer
        m = _INDEX_CACHE.get("embedder")
        if m is None:
            m = SentenceTransformer(cfg.V2_EMBEDDING_MODEL)
            _INDEX_CACHE["embedder"] = m
        return m.encode([query], normalize_embeddings=True)[0].tolist()
    except Exception as e:
        raise RuntimeError(f"vector_store: failed to embed query: {e}") from e


def dense_search(query: str, k: int = 80) -> list[dict]:
    """Return top-``k`` dossiers ranked by inner-product similarity."""
    cache = _lazy_index()
    if cache is None:
        return []
    import numpy as np
    vec = np.array([_embed(query)], dtype="float32")
    D, I = cache["index"].search(vec, k)
    out = []
    for score, i in zip(D[0], I[0]):
        if i < 0:
            continue
        out.append({
            "ticker":   cache["tickers"][i],
            "dossier":  cache["dossiers"][i],
            "score":    float(score),
            "relevance": float(score),     # normalized inner product == cosine
            "source":   "dense",
        })
    return out
