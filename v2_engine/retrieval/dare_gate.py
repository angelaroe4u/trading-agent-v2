"""
v2_engine.retrieval.dare_gate — Multi-Objective "propose-and-clip" gating (PDF §3).

Optimizes simultaneously for:

  - accuracy   — retrieval relevance
  - precision  — citation/source provenance is clean
  - cost       — token-budget bloat must stay below DARE_MAX_TOKENS

DARE = "Drop And REscale". Per PDF: the gate prunes retrieved chunks so
the Synthesizer's context window stays compact AND the resulting MSE on
numerical financial data drops.
"""
from __future__ import annotations

import tiktoken

from v2_engine import config as cfg


_ENCODER = None


def _enc():
    global _ENCODER
    if _ENCODER is None:
        try:
            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    return _ENCODER


def _tokens(s: str) -> int:
    enc = _enc()
    if enc is None:
        return len(s) // 4   # rough heuristic
    return len(enc.encode(s))


def propose_and_clip(
    hits: list[dict],
    target_k: int,
    min_accuracy: float | None = None,
    max_tokens: int | None = None,
    min_precision: float | None = None,
) -> list[dict]:
    """Return a subset of ``hits`` that satisfies the multi-objective gate.

    The "propose" step takes the highest-relevance hits first; the "clip"
    step drops any that would push token budget over ``max_tokens`` or that
    fall under the accuracy / precision floor.
    """
    min_accuracy  = min_accuracy  or cfg.V2_DARE_MIN_ACCURACY
    max_tokens    = max_tokens    or cfg.V2_DARE_MAX_TOKENS
    min_precision = min_precision or cfg.V2_DARE_MIN_PRECISION

    proposed = sorted(hits, key=lambda h: -h.get("relevance", 0.0))
    kept: list[dict] = []
    used_tokens = 0
    for h in proposed:
        if len(kept) >= target_k:
            break
        if h.get("relevance", 0.0) < min_accuracy:
            continue
        if h.get("precision", 1.0) < min_precision:
            continue
        cost = _tokens(h.get("dossier", ""))
        if used_tokens + cost > max_tokens:
            continue
        used_tokens += cost
        kept.append(h)
    return kept
