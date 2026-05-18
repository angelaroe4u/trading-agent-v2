"""
v2_engine.evolution.population — the population of candidate quant adapters.

A Population owns N LoRA adapters, each on disk under
``models/quant/gen<G>/individual_<i>/``. Each generation:

  1. Score all individuals against `fitness.fitness(...)`
  2. Select top-K survivors via tournament.py
  3. Breed them via merge_slerp / merge_structural / mutate
  4. Persist new generation; bump G

Lineage (who-bred-from-whom) is tracked in ``lineage.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from v2_engine import config as cfg


@dataclass
class Individual:
    id: str                 # unique within the lifetime of the experiment
    generation: int
    adapter_path: str
    parents: list[str] = field(default_factory=list)
    fitness: float | None = None
    mirror_score: float | None = None
    outcome_score: float | None = None
    metadata: dict = field(default_factory=dict)


class Population:
    def __init__(self, individuals: list[Individual], generation: int):
        self.individuals = individuals
        self.generation = generation

    @classmethod
    def seed_generation_zero(cls, n: int = cfg.V2_POPULATION_SIZE) -> "Population":
        """Generation 0 = clones of a single base wearing N varied adapters."""
        base = Path(cfg.V2_REPO_PATH) / "models" / "quant" / "gen0"
        base.mkdir(parents=True, exist_ok=True)
        inds = [Individual(
            id=f"gen0-i{i}",
            generation=0,
            adapter_path=str(base / f"individual_{i}"),
            metadata={"seed_kind": _seed_kind(i)},
        ) for i in range(n)]
        return cls(inds, generation=0)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "generation": self.generation,
            "individuals": [asdict(i) for i in self.individuals],
        }, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Population":
        raw = json.loads(Path(path).read_text())
        inds = [Individual(**i) for i in raw["individuals"]]
        return cls(inds, generation=int(raw["generation"]))


def _seed_kind(i: int) -> str:
    """Variety knobs for generation 0 — see ARCHITECTURE_V2.md §5."""
    return [
        "finance-sentiment",
        "math-reasoning",
        "code-reasoning",
        "general-instruct",
        "long-context",
        "news-classification",
        "json-strict",
        "chain-of-thought",
    ][i % 8]
