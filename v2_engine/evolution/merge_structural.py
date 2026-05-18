"""
v2_engine.evolution.merge_structural — Layer-block crossover (PDF §4).

Instead of interpolating every tensor, swap whole transformer-layer
blocks between parents. For LoRA adapters this means: for each layer
index `l`, randomly pick either parent A's or parent B's adapter on `l`.

Coarser than SLERP, faster to evaluate, and tends to preserve discrete
"capabilities" — useful when one parent is finance-tuned and the other
is math-tuned.
"""
from __future__ import annotations

import random
import re
from pathlib import Path


_LAYER_RX = re.compile(r"layers\.(\d+)\.")


def _layer_of(key: str) -> int | None:
    m = _LAYER_RX.search(key)
    return int(m.group(1)) if m else None


def merge_structural(adapter_a: str | Path, adapter_b: str | Path,
                     out: str | Path, swap_prob: float = 0.5,
                     seed: int | None = None) -> str:
    import torch  # noqa: F401  (kept so callers fail at import time if unavailable)
    from safetensors.torch import load_file, save_file
    rng = random.Random(seed)

    a = load_file(str(Path(adapter_a) / "adapter_model.safetensors"))
    b = load_file(str(Path(adapter_b) / "adapter_model.safetensors"))

    # Decide per-layer which parent contributes
    layers = sorted({l for l in (_layer_of(k) for k in a.keys()) if l is not None})
    picks = {l: ("a" if rng.random() < swap_prob else "b") for l in layers}

    merged = {}
    for k in a.keys() & b.keys():
        layer = _layer_of(k)
        if layer is None:
            merged[k] = a[k]   # non-layer tensors copy from A
            continue
        merged[k] = a[k] if picks[layer] == "a" else b[k]

    Path(out).mkdir(parents=True, exist_ok=True)
    save_file(merged, str(Path(out) / "adapter_model.safetensors"))
    return str(out)
