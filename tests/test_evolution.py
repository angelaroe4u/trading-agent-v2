"""Tournament selection + Population seeding sanity checks (no torch needed)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine.evolution.population import Population, Individual
from v2_engine.evolution.tournament import select_survivors


def test_seed_generation_zero():
    p = Population.seed_generation_zero(n=8)
    assert p.generation == 0
    assert len(p.individuals) == 8
    seed_kinds = {i.metadata.get("seed_kind") for i in p.individuals}
    assert len(seed_kinds) == 8


def test_tournament_elitism_preserves_top():
    inds = [Individual(id=f"i{i}", generation=0, adapter_path=f"x/{i}", fitness=float(i))
            for i in range(8)]
    pop = Population(inds, generation=0)
    survivors = select_survivors(
        pop,
        fitness_of=lambda i: i.fitness or 0.0,
        n_keep=4,
        elitism=2,
        seed=42,
    )
    top_two = [s.id for s in survivors[:2]]
    assert top_two == ["i7", "i6"], f"elites lost: {top_two}"
