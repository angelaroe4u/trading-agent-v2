"""
v2_engine.evolution.tournament — Selection step (PDF §4).

K-tournament: sample K individuals at random; the highest-fitness one wins
a slot in the next generation. Repeat until the next generation is filled.

Elitism: the top E individuals (default 2) always survive without
having to win their tournament. Prevents catastrophic generational
regression on a bad evaluation slice.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable

from v2_engine.evolution.population import Individual, Population


def select_survivors(
    pop: Population,
    fitness_of: Callable[[Individual], float],
    n_keep: int,
    tournament_size: int = 3,
    elitism: int = 2,
    seed: int | None = None,
) -> list[Individual]:
    rng = random.Random(seed)
    individuals = list(pop.individuals)
    individuals.sort(key=lambda i: fitness_of(i), reverse=True)

    survivors = list(individuals[:elitism])
    while len(survivors) < n_keep:
        sample = rng.sample(individuals, min(tournament_size, len(individuals)))
        winner = max(sample, key=fitness_of)
        survivors.append(winner)
    return survivors
