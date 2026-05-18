"""
v2_engine.agents.planner — decomposes a complex query/trigger into sub-tasks.

Only invoked in `full` mode by the Generator. For routine morning deploy,
the plan is implicit (build dossier universe, rank top N).
"""
from __future__ import annotations

from v2_engine.agents.base import Agent, AgentContext


class Planner(Agent):
    name = "planner"

    def run(self, ctx: AgentContext) -> dict:
        # TODO(angela): LoRA-swap to a planner adapter and prompt the base
        # model to emit a JSON plan. Stub returns a minimal plan that matches
        # V1's daily routine.
        return {
            "steps": [
                {"agent": "extractor", "intent": "build_dossier_universe", "k": 80},
                {"agent": "qa",        "intent": "verify_dossiers"},
                {"agent": "quant",     "intent": "rank_for_horizon", "horizon_days": 5},
                {"agent": "synthesizer","intent": "apply_constraints"},
            ],
            "horizon_days": 5,
        }
