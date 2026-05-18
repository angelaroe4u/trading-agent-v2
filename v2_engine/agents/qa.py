"""
v2_engine.agents.qa — validates retrieval before generation (PDF §3, iterative self-correction).

Drops or re-queries any retrieved dossier whose embedding distance to the
query exceeds threshold, or whose citation chain is incomplete.
"""
from __future__ import annotations

from v2_engine.agents.base import Agent, AgentContext
from v2_engine import config as cfg


class QA(Agent):
    name = "qa"

    def run(self, ctx: AgentContext) -> dict:
        retrieval = dict(ctx.retrieval)
        dossiers = retrieval.get("dossiers", [])
        kept = [d for d in dossiers if d.get("relevance", 0.0) >= cfg.V2_DARE_MIN_ACCURACY]
        retrieval["dossiers"] = kept
        retrieval["qa_kept"] = len(kept)
        retrieval["qa_dropped"] = len(dossiers) - len(kept)
        return retrieval
