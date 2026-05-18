"""
v2_engine.retrieval.self_correction — LLM-based router (PDF §3).

Before generation, the router decides whether to use dense, sparse, or
hybrid retrieval; afterward, it evaluates retrieved chunks and, if
irrelevant, triggers an expansion (re-issue with refined query) instead
of letting the model hallucinate.

For routine morning deploy we default to hybrid; the router only kicks in
for "anomaly" triggers where keyword-vs-semantic gives different answers.
"""
from __future__ import annotations

from v2_engine.agents.base import AgentContext


_STRATEGIES = ("dense", "sparse", "hybrid")


def route(intent: str, k: int, ctx: AgentContext) -> str:
    """Return one of ``"dense" | "sparse" | "hybrid"``."""
    # Heuristics first; LLM gating optional (cost).
    if intent == "build_dossier_universe":
        return "hybrid"
    if "ticker:" in intent or "symbol:" in intent:
        return "sparse"
    if "narrative" in intent or "story" in intent:
        return "dense"
    return "hybrid"


def needs_expansion(hits: list[dict], threshold: float = 0.65) -> bool:
    """True if mean relevance of top-10 hits is below threshold."""
    if not hits:
        return True
    top = sorted(hits, key=lambda h: -h.get("relevance", 0.0))[:10]
    mean = sum(h.get("relevance", 0.0) for h in top) / len(top)
    return mean < threshold
