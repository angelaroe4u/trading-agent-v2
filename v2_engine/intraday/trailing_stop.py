"""
v2_engine.intraday.trailing_stop — ADR-based trailing stop.

Per-position stop band = max(MIN_BAND_PCT, V2_TRAILING_STOP_ADR_MULT * ADR_14d%).
If ADR is unavailable / zero (new ticker, fetch failure), we fall back to V1's
flat V1_BASELINE_TRAILING_STOP_PCT so the position is never left unprotected.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from v2_engine import config as cfg
from shared.ledger_schema import Ledger, UnsettledProceed


# Hard floor so a freakishly low ADR can't shrink the band to zero
MIN_STOP_BAND_PCT = 0.50


def _stop_band_pct(adr_14d: float) -> float:
    """Return stop band as percent of trailing high. ADR-driven; floored."""
    band = cfg.V2_TRAILING_STOP_ADR_MULT * (adr_14d or 0.0)
    if band <= 0:
        return cfg.V1_BASELINE_TRAILING_STOP_PCT
    return max(MIN_STOP_BAND_PCT, band)


def trailing_stop_check(ledger: Ledger, save: Callable[[], None]) -> None:
    if not ledger.pod:
        return
    from shared.alpaca_paper import latest_prices, alp_sell

    tickers = [p.ticker for p in ledger.pod]
    prices = latest_prices(tickers)
    if not prices:
        return

    settle_day = (datetime.now(cfg.ET).date() + timedelta(days=1)).isoformat()

    sells = []
    for p in list(ledger.pod):
        if p.trailing_stop_triggered:
            continue
        cur = prices.get(p.ticker)
        if cur is None:
            continue
        # Update trailing peak
        if not p.trailing_high or cur > p.trailing_high:
            p.trailing_high = cur
            p.peak_price = cur
        band_pct = _stop_band_pct(p.adr_14d)
        stop_px = p.trailing_high * (1.0 - band_pct / 100.0)
        if cur <= stop_px:
            sells.append((p, cur, stop_px, p.trailing_high, band_pct))

    if not sells:
        save()
        return

    for p, cur, stop_px, peak, band in sells:
        shares, px = alp_sell(p.ticker, p.shares)
        if shares <= 0 or px <= 0:
            continue
        proceeds = shares * px
        ledger.unsettled.append(UnsettledProceed(amount=proceeds, settle_date=settle_day))
        p.trailing_stop_triggered = True
        ledger.blacklist_add(p.ticker)
        try:
            ledger.pod.remove(p)
        except ValueError:
            pass
    save()
