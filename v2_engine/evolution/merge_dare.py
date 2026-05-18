"""
v2_engine.evolution.merge_dare — DARE (Drop And REscale) weight merging.

Distinct from `retrieval/dare_gate.py` (which is a *retrieval* gate with
the same acronym from the PDF). This file implements the model-merging
DARE technique from Yu et al. 2023 — randomly drops a fraction of
finetuned task deltas then rescales to preserve magnitude.

Canonical reference: arcee-ai/mergekit. Falls back to a minimal pure-torch
version if mergekit isn't installed.
"""
from __future__ import annotations

from pathlib import Path


def merge_dare(base, adapter, out, drop_rate=0.5, rescale=True):
    try:
        from mergekit.config import MergeConfiguration
        from mergekit.merge import MergeOptions, run_merge
        method = "dare_ties" if rescale else "dare_linear"
        cfg = MergeConfiguration.model_validate({
            "merge_method": method,
            "base_model": str(base),
            "models": [{"model": str(adapter), "parameters": {
                "weight": 1.0, "density": 1.0 - drop_rate,
            }}],
            "dtype": "bfloat16",
        })
        run_merge(cfg, out_path=str(out), options=MergeOptions(cuda=False))
        return str(out)
    except Exception as e:
        print(f"merge_dare: mergekit unavailable ({e}); using torch fallback")

    import torch
    from safetensors.torch import load_file, save_file
    base_sd = load_file(str(Path(base) / "adapter_model.safetensors"))
    adp_sd  = load_file(str(Path(adapter) / "adapter_model.safetensors"))
    rng = torch.Generator().manual_seed(0)
    merged = {}
    for k in adp_sd:
        if k not in base_sd:
            merged[k] = adp_sd[k]
            continue
        delta = adp_sd[k] - base_sd[k]
        mask = (torch.rand(delta.shape, generator=rng) > drop_rate).to(delta.dtype)
        kept = delta * mask
        if rescale and (1.0 - drop_rate) > 0:
            kept = kept / (1.0 - drop_rate)
        merged[k] = base_sd[k] + kept
    Path(out).mkdir(parents=True, exist_ok=True)
    save_file(merged, str(Path(out) / "adapter_model.safetensors"))
    return str(out)
