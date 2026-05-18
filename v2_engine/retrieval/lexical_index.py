"""
v2_engine.retrieval.lexical_index — BM25 over the same dossiers.

Default backend: ``rank_bm25`` (pure Python; survives Hetzner's 8 GB RAM).
Future: swap for Pyserini's BM25 if precision lags. ``pi_serini.py`` wraps
this with the LLM-driven keyword refinement loop from PDF §3.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from v2_engine import config as cfg


_BM25_CACHE: dict[str, Any] = {}


def _lazy_index():
    if "bm25" in _BM25_CACHE:
        return _BM25_CACHE
    path = Path(cfg.V2_BM25_INDEX)
    if not path.exists():
        return None
    with path.open("rb") as f:
        bm25, tickers, dossiers, tokenizer = pickle.load(f)
    _BM25_CACHE["bm25"] = bm25
    _BM25_CACHE["tickers"] = tickers
    _BM25_CACHE["dossiers"] = dossiers
    _BM25_CACHE["tokenizer"] = tokenizer
    return _BM25_CACHE


def bm25_search(query: str, k: int = 80) -> list[dict]:
    cache = _lazy_index()
    if cache is None:
        return []
    tokenizer = cache["tokenizer"]
    bm25 = cache["bm25"]
    scores = bm25.get_scores(tokenizer(query))
    # top-k indices
    top = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    if not top:
        return []
    s_max = max(scores[i] for i in top) or 1.0
    return [{
        "ticker":   cache["tickers"][i],
        "dossier":  cache["dossiers"][i],
        "score":    float(scores[i]),
        "relevance": float(scores[i] / s_max),
        "source":   "sparse",
    } for i in top]
