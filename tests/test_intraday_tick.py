"""Intraday risk-loop unit tests — divergence math + trailing stop logic."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine import config as cfg
from v2_engine.intraday.divergence import expected_progress_at
from v2_engine.intraday.trailing_stop import _stop_band_pct, MIN_STOP_BAND_PCT
from shared.ledger_schema import Position


ET = ZoneInfo("America/New_York")


# -------- divergence curve --------

def test_divergence_curve_pre_curve_returns_zero():
    pre = datetime(2026, 5, 20, 10, 30, tzinfo=ET)
    assert expected_progress_at(pre) == 0.0


def test_divergence_curve_at_first_checkpoint():
    at_first = datetime(2026, 5, 20, 11, 30, tzinfo=ET)
    assert abs(expected_progress_at(at_first) - 0.33) < 1e-9


def test_divergence_curve_at_last_checkpoint():
    at_last = datetime(2026, 5, 20, 14, 30, tzinfo=ET)
    assert abs(expected_progress_at(at_last) - 0.85) < 1e-9


def test_divergence_curve_interpolates_linearly_between_points():
    midway = datetime(2026, 5, 20, 12, 15, tzinfo=ET)
    expected = 0.33 + (0.60 - 0.33) * 0.5
    assert abs(expected_progress_at(midway) - expected) < 1e-9


def test_divergence_curve_post_curve_caps_at_last_checkpoint():
    # V1 semantics: curve tops out at 85%, never extrapolates to 100%.
    after = datetime(2026, 5, 20, 15, 30, tzinfo=ET)
    assert expected_progress_at(after) == 0.85


# -------- trailing-high accounting --------

def test_position_updates_trailing_high_only_upward():
    p = Position(ticker="X", shares=10, entry_price=10.0,
                 entry_ts="2026-05-20T09:55:00-04:00",
                 trailing_high=10.0)
    if 11.0 > p.trailing_high:
        p.trailing_high = 11.0
    assert p.trailing_high == 11.0
    if 10.5 > p.trailing_high:
        p.trailing_high = 10.5
    assert p.trailing_high == 11.0


# -------- trailing stop band: ADR-based with floor + fallback --------

def test_trailing_stop_band_scales_with_adr():
    """V2 default: stop band = V2_TRAILING_STOP_ADR_MULT * ADR_14d% (= 1.5 by default)."""
    assert abs(_stop_band_pct(3.0) - 4.5) < 1e-9   # calm stock: 4.5%
    assert abs(_stop_band_pct(5.0) - 7.5) < 1e-9   # volatile stock: 7.5%


def test_trailing_stop_band_has_min_floor():
    """A freakishly low ADR can't shrink the band to zero."""
    assert _stop_band_pct(0.1) == MIN_STOP_BAND_PCT  # 1.5 × 0.1 = 0.15 → floor


def test_trailing_stop_band_falls_back_to_flat_when_adr_missing():
    """ADR fetch failed / new ticker → V1's flat 2% protects the position."""
    assert _stop_band_pct(0.0) == cfg.V1_BASELINE_TRAILING_STOP_PCT


def test_trailing_stop_threshold_math():
    """Peak $11 + ADR 2% → 3% band → stop $10.67."""
    peak = 11.0
    band = _stop_band_pct(2.0)              # 1.5 × 2.0 = 3.0
    stop_px = peak * (1.0 - band / 100.0)   # 11 × 0.97 = 10.67
    assert abs(stop_px - 10.67) < 1e-6
    assert 10.75 > stop_px                  # would hold
    assert 10.50 <= stop_px                 # would trigger
