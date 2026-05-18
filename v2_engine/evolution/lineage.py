"""
v2_engine.evolution.lineage — track who-bred-from-whom across generations.

Persists a JSONL ancestry log. Each row is one Individual with its parents
+ fitness. Used to:

- Re-run any historical model exactly (reproducibility)
- Detect convergence (population collapsing onto a single ancestor)
- Visualize the evolutionary tree
"""
from __future__ import annotations

import json
from pathlib import Path

from v2_engine.evolution.population import Individual


def append(ind: Individual, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": ind.id, "generation": ind.generation,
            "parents": ind.parents, "fitness": ind.fitness,
            "mirror_score": ind.mirror_score,
            "outcome_score": ind.outcome_score,
            "adapter_path": ind.adapter_path,
            "metadata": ind.metadata,
        }) + "\n")


def read_all(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
