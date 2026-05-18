"""
v2_engine.evolution.mutate — Gaussian perturbation of a LoRA adapter.

Adds noise ``ε ~ N(0, sigma)`` to a random subset of tensors (default 20%).
Small sigma keeps the adapter recognizable; the evolutionary pressure
filters out destructive mutations via the fitness function.
"""
from __future__ import annotations

import random
from pathlib import Path


def mutate(adapter: str | Path, out: str | Path,
           sigma: float = 0.01, fraction: float = 0.2,
           seed: int | None = None) -> str:
    import torch
    from safetensors.torch import load_file, save_file
    rng = random.Random(seed)

    sd = load_file(str(Path(adapter) / "adapter_model.safetensors"))
    keys = list(sd.keys())
    rng.shuffle(keys)
    target = keys[: max(1, int(len(keys) * fraction))]

    for k in target:
        sd[k] = sd[k] + torch.randn_like(sd[k]) * sigma

    Path(out).mkdir(parents=True, exist_ok=True)
    save_file(sd, str(Path(out) / "adapter_model.safetensors"))
    return str(out)
