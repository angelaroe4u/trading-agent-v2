"""DARE gate — multi-objective accuracy / precision / token-cost clipping."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine.retrieval.dare_gate import propose_and_clip


def _h(ticker, relevance, dossier="x" * 100, precision=0.95):
    return {"ticker": ticker, "relevance": relevance,
            "dossier": dossier, "precision": precision}


def test_drops_below_accuracy_floor():
    hits = [_h("A", 0.95), _h("B", 0.50), _h("C", 0.90)]
    kept = propose_and_clip(hits, target_k=3, min_accuracy=0.80)
    assert {h["ticker"] for h in kept} == {"A", "C"}


def test_respects_target_k():
    hits = [_h(t, 0.99) for t in "ABCDEFGH"]
    kept = propose_and_clip(hits, target_k=3)
    assert len(kept) == 3


def test_respects_token_budget():
    hits = [_h("A", 0.99, dossier="x" * 50_000)]
    kept = propose_and_clip(hits, target_k=5, max_tokens=100)
    assert kept == []
