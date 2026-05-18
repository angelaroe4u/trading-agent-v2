"""
v2_engine.agents.base — common interface for every agent in the MAS.

The PDF (§2) calls for hyper-specialized agents spawned on demand by the
Generator. The interface is deliberately small so a LoRA-swap can replace
one agent's adapter without disturbing the rest.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """Passed to every agent invocation."""
    trading_day: str
    constraints: dict[str, Any] = field(default_factory=dict)   # from EDA
    retrieval: dict[str, Any] = field(default_factory=dict)     # from Extractor
    prior_outputs: dict[str, Any] = field(default_factory=dict) # other agents' outputs
    budget_tokens: int = 12_000


class Agent(ABC):
    """Base class — subclass per agent role."""
    name: str = "agent"
    requires_lora: bool = False

    @abstractmethod
    def run(self, ctx: AgentContext) -> Any:
        """Execute. Pure-ish: reads ctx, returns its piece of the puzzle."""
        ...

    def healthcheck(self) -> bool:
        """Return False if the agent can't run (model missing, key absent)."""
        return True
