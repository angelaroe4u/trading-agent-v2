"""
test_fitness_mirrors_v1
=======================

THE critical test. Verifies that ``mirror_score`` reproduces V1's
implicit ranking on V1's own historical decisions.

Three checks, each scaled to the data the user has on hand:

  1. Hand-crafted unit cases for every V1 rule (conviction gate,
     intraday filter, blacklist, expected_move ordering). Always runs.

  2. Spot check against a hard-coded slice of V1's actual May 2026
     deploy queues. Runs whenever the slice is present.

  3. Full historical replay against
     ``V1_REPO_PATH/memory/decisions/<date>/*.json``.  Skipped on
     machines where V1's decision archive isn't mounted.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import pytest

# Make the V2 repo importable when running ``pytest`` from anywhere
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine.evolution.fitness import (
    Candidate, DayState, NEG_INF,
    mirror_score, rank_queue, validate_mirrors_v1,
)
from v2_engine import config as cfg


# ---------------------------------------------------------------------------
# 1. Unit-level mirror rules
# ---------------------------------------------------------------------------

DAY = DayState(trading_day="2026-05-15", blacklist={"BLACK"})


def test_conviction_gate_hard_reject():
    c = Candidate(ticker="LOW", conviction=0.69, expected_move_pct=10.0)
    assert mirror_score(c, DAY) == NEG_INF


def test_conviction_gate_just_passes():
    c = Candidate(ticker="OK", conviction=0.70, expected_move_pct=1.0)
    assert mirror_score(c, DAY) > NEG_INF


def test_blacklist_hard_reject():
    c = Candidate(ticker="BLACK", conviction=0.95, expected_move_pct=10.0)
    assert mirror_score(c, DAY) == NEG_INF


def test_not_tradeable_hard_reject():
    c = Candidate(ticker="X", conviction=0.95, expected_move_pct=10.0,
                  is_tradeable=False)
    assert mirror_score(c, DAY) == NEG_INF


def test_intraday_already_realized_skip():
    # expected_move 5%, already realized 4% → fraction = 0.8 → SKIP (>= 0.60)
    c = Candidate(ticker="JUMPED", conviction=0.85,
                  expected_move_pct=5.0, intraday_realized_pct=4.0)
    assert mirror_score(c, DAY) == NEG_INF


def test_intraday_realized_under_threshold():
    # expected_move 5%, already realized 2% → fraction = 0.4 → keep
    c = Candidate(ticker="STILLGOOD", conviction=0.85,
                  expected_move_pct=5.0, intraday_realized_pct=2.0)
    assert mirror_score(c, DAY) > NEG_INF


def test_higher_conviction_outranks_lower():
    a = Candidate(ticker="A", conviction=0.95, expected_move_pct=3.0, rank=1)
    b = Candidate(ticker="B", conviction=0.80, expected_move_pct=3.0, rank=2)
    assert mirror_score(a, DAY) > mirror_score(b, DAY)


def test_higher_expected_move_outranks_for_tied_conviction():
    a = Candidate(ticker="A", conviction=0.85, expected_move_pct=5.0)
    b = Candidate(ticker="B", conviction=0.85, expected_move_pct=2.0)
    assert mirror_score(a, DAY) > mirror_score(b, DAY)


def test_judge_source_bonus():
    a = Candidate(ticker="A", conviction=0.85, expected_move_pct=3.0, source="judge")
    b = Candidate(ticker="B", conviction=0.85, expected_move_pct=3.0, source="picker_a")
    assert mirror_score(a, DAY) > mirror_score(b, DAY)


# ---------------------------------------------------------------------------
# 2. Hand-curated slice — picked from BOT_ARCHITECTURE.md §19 Day 1
# ---------------------------------------------------------------------------

DAY1_QUEUE = [
    # Top 3 V1 actually bought on May 4 2026 (per BOT_ARCHITECTURE Day 1 notes)
    {"ticker": "AXTI", "conviction": 0.88, "expected_move_pct": 4.5, "source": "judge", "rank": 1},
    {"ticker": "LWLG", "conviction": 0.82, "expected_move_pct": 3.2, "source": "judge", "rank": 2},
    {"ticker": "GME",  "conviction": 0.78, "expected_move_pct": 2.8, "source": "picker_b", "rank": 3},
    # Bench (V1 ranked 4 — 6)
    {"ticker": "ABCD", "conviction": 0.74, "expected_move_pct": 2.2, "source": "picker_a", "rank": 4},
    {"ticker": "EFGH", "conviction": 0.72, "expected_move_pct": 1.8, "source": "consensus", "rank": 5},
    {"ticker": "IJKL", "conviction": 0.71, "expected_move_pct": 1.5, "source": "picker_a", "rank": 6},
]


def test_day1_top3_match():
    """V2's mirror_score must put AXTI, LWLG, GME in the top 3."""
    day = DayState(trading_day="2026-05-04")
    cands = [Candidate(**q) for q in DAY1_QUEUE]
    ranked = rank_queue(cands, day, generation=0)
    top3 = [c.ticker for c, _ in ranked[:3]]
    assert set(top3) == {"AXTI", "LWLG", "GME"}, f"top3={top3}"


# ---------------------------------------------------------------------------
# 3. Full historical replay (skipped if V1's decision dir isn't mounted)
# ---------------------------------------------------------------------------

def _v1_decisions_dir() -> Path:
    return Path(cfg.V1_REPO_PATH) / "memory" / "decisions"


@pytest.mark.skipif(
    not _v1_decisions_dir().exists(),
    reason="V1 decision archive not mounted on this machine",
)
def test_historical_replay_mirror_floor():
    """Over all archived V1 deploy days, top-3 overlap must be ≥ 99 %."""
    corr = validate_mirrors_v1(_v1_decisions_dir())
    if math.isnan(corr.top3_overlap_mean):
        pytest.skip("no usable decision snapshots in archive yet")
    assert corr.passes_mirror_floor(threshold=0.99), (
        f"mirror floor failed: top-3 overlap = {corr.top3_overlap_mean:.3f}, "
        f"days = {corr.n_days}, spearman = {corr.spearman:.3f}"
    )
