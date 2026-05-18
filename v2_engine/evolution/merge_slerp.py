"""
v2_engine.evolution.merge_slerp — Spherical Linear Interpolation between
two LoRA adapter weight tensors.

Backend selection:
  1. mergekit (arcee-ai/mergekit) if installed — canonical, well-tested.
  2. Homegrown implementation as fallback — pure torch + safetensors.

Both paths produce the same on-disk format (adapter_model.safetensors).
"""
from __future__ import annotations

from pathlib import Path


def _try_mergekit(adapter_a, adapter_b, out, t):
    try:
        from mergekit.config import MergeConfiguration, ParameterSetting
        from mergekit.merge import MergeOptions, run_merge
        cfg = MergeConfiguration.model_validate({
            "merge_method": "slerp",
            "slices": [{
                "sources": [
                    {"model": str(adapter_a), "layer_range": [0, 999]},
                    {"model": str(adapter_b), "layer_range": [0, 999]},
                ]
            }],
            "parameters": {"t": float(t)},
            "dtype": "bfloat16",
        })
        run_merge(cfg, out_path=str(out), options=MergeOptions(cuda=False))
        return True
    except Exception as e:
        print(f"merge_slerp: mergekit unavailable / failed ({e}); using fallback")
        return False


def _slerp_vectors_torch(a, b, t):
    import torch
    a_flat = a.flatten().float()
    b_flat = b.flatten().float()
    dot = (a_flat @ b_flat) / (a_flat.norm() * b_flat.norm() + 1e-12)
    dot = torch.clamp(dot, -1.0, 1.0)
    theta = torch.acos(dot)
    if theta.abs() < 1e-6:
        return ((1 - t) * a + t * b).to(a.dtype)
    sin_theta = torch.sin(theta)
    w_a = torch.sin((1 - t) * theta) / sin_theta
    w_b = torch.sin(t * theta) / sin_theta
    return (w_a * a + w_b * b).to(a.dtype)


def _fallback_merge(adapter_a, adapter_b, out, t):
    from safetensors.torch import load_file, save_file
    a = load_file(str(Path(adapter_a) / "adapter_model.safetensors"))
    b = load_file(str(Path(adapter_b) / "adapter_model.safetensors"))
    merged = {k: _slerp_vectors_torch(a[k], b[k], t) for k in a.keys() & b.keys()}
    Path(out).mkdir(parents=True, exist_ok=True)
    save_file(merged, str(Path(out) / "adapter_model.safetensors"))


def merge_slerp(adapter_a, adapter_b, out, t=0.5):
    """Merge two LoRA adapters by SLERPing every matching tensor."""
    Path(out).mkdir(parents=True, exist_ok=True)
    if _try_mergekit(adapter_a, adapter_b, out, t):
        return str(out)
    _fallback_merge(adapter_a, adapter_b, out, t)
    return str(out)
