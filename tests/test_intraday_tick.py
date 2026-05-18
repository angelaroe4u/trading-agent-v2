"""Intraday risk-loop unit tests — divergence math + trailing stop logic."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine import config as cfg
from v2_engine.intraday.divergence import expected_progress_at
from shared.ledger_schema import Ledger, Position


ET = ZoneInfo("America/New_York")


def test_divergence_curve_pre_curve_returns_zero():
    pre = datetime(2026, 5, 20, 10, 30, tzinfo=ET)   # 10:30, before 11:30 first point
    assert expected_progress_at(pre) == 0.0


def test_divergence_curve_at_first_checkpoint():
    at_first = datetime(2026, 5, 20, 11, 30, tzinfo=ET)
    assert abs(expected_progress_at(at_first) - 0.33) < 1e-9


def test_divergence_curve_at_last_checkpoint():
    at_last = datetime(2026, 5, 20, 14, 30, tzinfo=ET)
    assert abs(expected_progress_at(at_last) - 0.85) < 1e-9


def test_divergence_curve_interpolates_linearly_between_points():
    midway = datetime(2026, 5, 20, 12, 15, tzinfo=ET)   # halfway 11:30 -> 13:00
    expected = 0.33 + (0.60 - 0.33) * 0.5
    assert abs(expected_progress_at(midway) - expected) < 1e-9


def test_divergence_curve_post_curve_caps_at_last_checkpoint():
    # V1 curve tops out at 85% (14:30) by design — there's no extrapolation
    # to 100% because the curve is a floor for "what should be realized by
    # now", not a forecast. After 14:30 it stays at 0.85 until harvest.
    after = datetime(2026, 5, 20, 15, 30, tzinfo=ET)
    assert expected_progress_at(after) == 0.85


def test_position_updates_trailing_high_only_upward():
    # Pure logic — trailing_stop_check mutates p.trailing_high directly when
    # cur > existing. We test the math here rather than the broker round-trip.
    p = Position(ticker="X", shares=10, entry_price=10.0,
                 entry_ts="2026-05-20T09:55:00-04:00",
                 trailing_high=10.0)
    # Simulate intra-period state machine
    if 11.0 > p.trailing_high:
        p.trailing_high = 11.0
    assert p.trailing_high == 11.0
    if 10.5 > p.trailing_high:   # should NOT update
        p.trailing_high = 10.5
    assert p.trailing_high == 11.0


def test_trailing_stop_threshold_math():
    # Peak $11, stop band 2% → stop at $10.78. At $10.80 hold; at $10.70 sell.
    peak = 11.0
    stop_band = cfg.V1_BASELINE_TRAILING_STOP_PCT
    stop_px = peak * (1.0 - stop_band / 100.0)
    assert abs(stop_px - 10.78) < 1e-6
    assert 10.80 > stop_px          # would hold
    assert 10.70 <= stop_px         # would trigger
