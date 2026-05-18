"""
v2_engine.intraday.context_filter — "missed the jump" filter for morning deploy.

Same logic as V1's intraday_context_filter:
  - For each council pick, compute already_moved_pct = (cur - open) / open * 100
  - Skip if already_moved >= INTRADAY_SKIP_THRESHOLD * expected_move_pct
  - Re-rank survivors by remaining_juice = expected_move - already_moved
"""
from __future__ import annotations

from v2_engine import config as cfg
from v2_engine.evolution.fitness import Candidate


def filter_intraday(candidates: list[Candidate]) -> list[Candidate]:
    """Annotate intraday_realized_pct and drop the 'missed the jump' picks."""
    from shared.alpaca_paper import latest_price, day_open

    survivors: list[Candidate] = []
    for c in candidates:
        if c.expected_move_pct <= 0:
            survivors.append(c)
            continue
        try:
            cur = latest_price(c.ticker)
            opx = day_open(c.ticker)
            if cur is None or opx is None or opx <= 0:
                survivors.append(c)
                continue
            already = (cur / opx - 1.0) * 100.0
            c.intraday_realized_pct = max(0.0, already)
            fraction = c.intraday_realized_pct / c.expected_move_pct
            remaining = c.expected_move_pct - c.intraday_realized_pct
            if fraction >= cfg.V1_BASELINE_INTRADAY_SKIP_THRESHOLD:
                continue
            if remaining < cfg.V1_BASELINE_INTRADAY_MIN_REMAIN_PP:
                continue
        except Exception:
            pass
        survivors.append(c)

    # Re-rank by remaining juice
    survivors.sort(
        key=lambda c: (c.expected_move_pct - c.intraday_realized_pct),
        reverse=True,
    )
    return survivors
