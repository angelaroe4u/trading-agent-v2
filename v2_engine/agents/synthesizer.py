"""
v2_engine.agents.synthesizer — applies EDA hard constraints and emits the
final candidate list to the orchestrator (PDF §6 step 6).
"""
from __future__ import annotations

from v2_engine.agents.base import Agent, AgentContext
from v2_engine.evolution.fitness import Candidate
from v2_engine import config as cfg


class Synthesizer(Agent):
    name = "synthesizer"

    def apply_constraints(self, candidates: list[Candidate], constraints: dict) -> list[Candidate]:
        out: list[Candidate] = []
        for c in candidates:
            if not constraints.get("market_is_open", True):
                continue
            if constraints.get("pattern_day_trader_locked"):
                # PDT-locked accounts can't open new positions; block all buys.
                continue
            fract_universe = constraints.get("fractionable_universe")
            if fract_universe is not None and c.ticker not in fract_universe:
                # We size with notional dollars; non-fractionable tickers
                # need a "whole shares" path. Mark and downgrade.
                c.thesis = (c.thesis or "") + " [whole-shares-only]"
            out.append(c)
        return out

    def run(self, ctx: AgentContext):     # pragma: no cover
        cands = ctx.prior_outputs.get("quant", [])
        return self.apply_constraints(cands, ctx.constraints)
