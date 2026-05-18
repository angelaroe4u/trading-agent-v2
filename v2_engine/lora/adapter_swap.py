"""
v2_engine.lora.adapter_swap — single base model, many adapters (PDF §2).

Holds one ``transformers`` causal LM in memory; hot-swaps LoRA adapters
via ``peft.PeftModel.set_adapter`` for each role (Quant, Persona, etc.).

Lazy initialization — the base model isn't loaded until ``get()`` is
called, so unit tests and the side-by-side runner in shadow mode don't
have to pay the GPU cost.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from v2_engine import config as cfg


_STATE: dict[str, Any] = {"base": None, "adapters": {}, "active": None}


def get():
    """Return ``(model, tokenizer)`` with the base model loaded once."""
    if _STATE["base"] is not None:
        return _STATE["base"]
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except Exception as e:
        raise RuntimeError("transformers / peft not installed — pip install -e .") from e

    tok = AutoTokenizer.from_pretrained(cfg.V2_BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        cfg.V2_BASE_MODEL,
        torch_dtype="auto",
        device_map="auto",
    )
    _STATE["base"] = (model, tok)
    return _STATE["base"]


def register_adapter(name: str, path: str | Path) -> None:
    """Load a LoRA adapter and register it under ``name``."""
    from peft import PeftModel
    model, tok = get()
    if name in _STATE["adapters"]:
        return
    peft_model = PeftModel.from_pretrained(model, str(path), adapter_name=name)
    _STATE["base"] = (peft_model, tok)
    _STATE["adapters"][name] = str(path)


def activate(name: str) -> None:
    """Switch the active adapter."""
    model, _ = get()
    if hasattr(model, "set_adapter"):
        model.set_adapter(name)
    _STATE["active"] = name


def active() -> str | None:
    return _STATE["active"]
