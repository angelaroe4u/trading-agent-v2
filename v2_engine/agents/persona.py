"""
v2_engine.agents.persona — translates the Quant Agent's analytical output
into accessible, empathetic user-facing copy (PDF §6 step 7).

In V2 this is a LoRA-swapped persona adapter on the base model. In Gen 0
we delegate to Claude Haiku 4.5 (V1's utility model) so the output style
already matches V1's daily emails.
"""
from __future__ import annotations

import os

from v2_engine.agents.base import Agent, AgentContext
from v2_engine import config as cfg


class Persona(Agent):
    name = "persona"
    requires_lora = True

    def translate(self, thesis: str) -> str:
        """Rewrite ``thesis`` for the dashboard / daily email."""
        if not thesis:
            return ""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return thesis  # no rewrite if no key
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=cfg.V2_PERSONA_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content":
                    "Rewrite this trading thesis in two short sentences, "
                    "warm but precise, no jargon, no hype: " + thesis}],
            )
            return msg.content[0].text.strip()
        except Exception:
            return thesis

    def run(self, ctx: AgentContext):     # pragma: no cover
        return self.translate(ctx.prior_outputs.get("thesis", ""))
