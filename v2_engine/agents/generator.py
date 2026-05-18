"""
v2_engine.agents.generator — Recursive Meta-Agent (PDF §2).

Decides WHICH sub-agents to spawn for the current trigger and orchestrates
them. Two operating modes:

  fast   — only {Extractor → Quant → Synthesizer}. Used for routine
           morning deploy when EDA reports no anomalies.

  full   — {Planner → Extractor → QA → Quant → Synthesizer}. Used when EDA
           flags an anomaly (gap > 2 %, VIX spike, halt) or the user issues
           a non-routine query.

Returns a ranked queue of `fitness.Candidate` objects, NOT a buy list.
The orchestrator owns ranking via `fitness.rank_queue`.
"""
from __future__ import annotations

from typing import Any

from v2_engine.agents.base import Agent, AgentContext
from v2_engine.agents.planner import Planner
from v2_engine.agents.extractor import Extractor
from v2_engine.agents.qa import QA
from v2_engine.agents.quant import Quant
from v2_engine.agents.synthesizer import Synthesizer
from v2_engine.evolution.fitness import Candidate


class Generator(Agent):
    name = "generator"

    def __init__(self, generation: int = 0):
        self.generation = generation
        self.planner = Planner()
        self.extractor = Extractor()
        self.qa = QA()
        self.quant = Quant(generation=generation)
        self.synthesizer = Synthesizer()

    # PDF §2: spawn agents recursively based on the query/trigger
    def _choose_mode(self, constraints: dict[str, Any]) -> str:
        if constraints.get("anomaly_detected"):
            return "full"
        return "fast"

    def generate_queue(self, trading_day: str, constraints: dict) -> list[Candidate]:
        ctx = AgentContext(trading_day=trading_day, constraints=constraints)
        mode = self._choose_mode(constraints)

        if mode == "full":
            ctx.prior_outputs["plan"] = self.planner.run(ctx)
        ctx.retrieval = self.extractor.run(ctx)
        if mode == "full":
            ctx.retrieval = self.qa.run(ctx)
        candidates = self.quant.run(ctx)
        return candidates

    def run(self, ctx: AgentContext):     # pragma: no cover — kept for Agent ABC parity
        return self.generate_queue(ctx.trading_day, ctx.constraints)
