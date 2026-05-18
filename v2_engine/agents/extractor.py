"""
v2_engine.agents.extractor — pulls precise data from the hybrid DB.

The DB upgrade per PDF §3:

  - Dense vector search (FAISS over MiniLM embeddings of dossier prose)
  - Sparse lexical search (BM25 — Pi-Serini-style) wrapped in an LLM
    refinement loop in ``retrieval/pi_serini.py``
  - DARE-Agent gate prunes results by multi-objective accuracy / cost
  - Iterative self-correction router decides dense vs sparse vs hybrid

Output is a dict with the candidate universe + dossiers and the
provenance (which index returned which dossier) — critical for the
Synthesizer to assess source credibility.
"""
from __future__ import annotations

from v2_engine.agents.base import Agent, AgentContext
from v2_engine.retrieval.pi_serini import lexical_search
from v2_engine.retrieval.vector_store import dense_search
from v2_engine.retrieval.dare_gate import propose_and_clip
from v2_engine.retrieval.self_correction import route


class Extractor(Agent):
    name = "extractor"

    def run(self, ctx: AgentContext) -> dict:
        plan = ctx.prior_outputs.get("plan", {})
        k = int(plan.get("steps", [{}])[0].get("k", 80))

        # Self-correcting router picks strategy
        strategy = route(intent="build_dossier_universe", k=k, ctx=ctx)

        if strategy == "dense":
            hits = dense_search(query="momentum opportunities today", k=k * 2)
        elif strategy == "sparse":
            hits = lexical_search(query="momentum opportunities today", k=k * 2)
        else:  # hybrid
            d = dense_search(query="momentum opportunities today", k=k)
            s = lexical_search(query="momentum opportunities today", k=k)
            hits = _merge_unique(d, s, limit=k * 2)

        kept = propose_and_clip(hits, target_k=k)
        return {
            "strategy": strategy,
            "dossiers": kept,
            "n_hits": len(hits),
            "n_kept": len(kept),
        }


def _merge_unique(a: list[dict], b: list[dict], limit: int) -> list[dict]:
    seen, out = set(), []
    for x in a + b:
        if x["ticker"] in seen:
            continue
        seen.add(x["ticker"])
        out.append(x)
        if len(out) >= limit:
            break
    return out
