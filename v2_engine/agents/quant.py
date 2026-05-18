"""
v2_engine.agents.quant — the Darwinian-evolved Quantitative Agent.

In generation 0 this is a thin wrapper around V1's `council_v2.run_council`
so we have a working baseline to compare against. From generation 1 on,
the Quant agent wears a LoRA adapter selected by the evolutionary loop in
``v2_engine.evolution`` (see ``fitness.py`` and ``tournament.py``).

The Quant agent's job is to assign ``conviction`` and ``expected_move_pct``
to each candidate ticker from the Extractor. It does NOT execute trades
and does NOT apply hard constraints — those belong to the Synthesizer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from v2_engine.agents.base import Agent, AgentContext
from v2_engine.evolution.fitness import Candidate
from v2_engine import config as cfg


class Quant(Agent):
    name = "quant"
    requires_lora = True

    def __init__(self, generation: int = 0, adapter_path: str | None = None):
        self.generation = generation
        self.adapter_path = adapter_path

    def run(self, ctx: AgentContext) -> list[Candidate]:
        if self.generation == 0:
            return self._gen0_via_v1_council(ctx)
        return self._gen_n_via_evolved_adapter(ctx)

    # ------------------------------------------------------------
    # Generation 0 — call V1's council directly for a baseline queue
    # ------------------------------------------------------------
    def _gen0_via_v1_council(self, ctx: AgentContext) -> list[Candidate]:
        v1_repo = os.getenv("V1_REPO_PATH", r"C:\Projects\tradingap")
        if v1_repo not in sys.path:
            sys.path.insert(0, v1_repo)
        try:
            import council_v2 as v1_council
        except Exception as e:
            print(f"V2 Quant gen-0: failed to import V1 council ({e}); returning []")
            return []
        try:
            queue = v1_council.run_council(ctx.trading_day)
        except Exception as e:
            print(f"V2 Quant gen-0: V1 council failed ({e}); returning []")
            return []
        return [self._row_to_candidate(r) for r in queue]

    # ------------------------------------------------------------
    # Generation 1+ — call evolved adapter via the base model
    # ------------------------------------------------------------
    def _gen_n_via_evolved_adapter(self, ctx: AgentContext) -> list[Candidate]:
        # TODO(angela): load self.adapter_path into the base model via peft,
        # prompt with the dossiers from ctx.retrieval, parse JSON output
        # into Candidate list. See lora/adapter_swap.py for the loader.
        return []

    @staticmethod
    def _row_to_candidate(row: dict) -> Candidate:
        return Candidate(
            ticker            = row["ticker"],
            conviction        = float(row.get("conviction", 0.0)),
            expected_move_pct = float(row.get("expected_move_pct", 0.0)),
            source            = row.get("source", "judge"),
            thesis            = row.get("thesis", ""),
            rank              = int(row.get("rank", 0)),
        )
