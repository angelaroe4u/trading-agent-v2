"""
v2_engine.retrieval.pi_serini — Agentic Lexical Retrieval (PDF §3).

Wraps BM25 in an LLM tool-use loop. The Extractor calls ``lexical_search``;
this module re-issues with refined keywords up to ``V2_PI_SERINI_MAX_ITERS``
times if relevance falls below the DARE accuracy floor.

Pseudo-relevance feedback per PDF: refined keywords come from the LLM
reading the top-N results' dossier prose, not from a fixed expansion
dictionary.
"""
from __future__ import annotations

import os
from typing import Any

from v2_engine import config as cfg
from v2_engine.retrieval.lexical_index import bm25_search


def _refine_keywords(query: str, hits: list[dict]) -> str:
    """Ask the base/judge model to propose refined keywords given the top hits."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or not hits:
        return query
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        snippets = "\n\n".join(h["dossier"][:600] for h in hits[:5])
        msg = client.messages.create(
            model=cfg.V2_PERSONA_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content":
                f"Original query: {query}\n\n"
                f"Top-5 results so far:\n{snippets}\n\n"
                "Return ONE refined search query (just the words, no JSON)."}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return query


def lexical_search(query: str, k: int = 80) -> list[dict]:
    """Pi-Serini lexical search with up to ``V2_PI_SERINI_MAX_ITERS`` refinements."""
    seen, accumulated = set(), []
    current = query
    for _ in range(cfg.V2_PI_SERINI_MAX_ITERS):
        hits = bm25_search(current, k=k)
        new = [h for h in hits if h["ticker"] not in seen]
        for h in new:
            seen.add(h["ticker"])
            accumulated.append(h)
        if not hits:
            break
        mean_rel = sum(h["relevance"] for h in hits[:10]) / max(min(len(hits), 10), 1)
        if mean_rel >= cfg.V2_DARE_MIN_ACCURACY:
            break
        current = _refine_keywords(current, hits)
        if current == query:
            break  # LLM didn't change the query — no progress to be made
    accumulated.sort(key=lambda h: -h["relevance"])
    return accumulated[:k]
