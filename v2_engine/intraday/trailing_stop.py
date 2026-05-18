"""
v2_engine.intraday.trailing_stop — flat -2% trailing stop from peak.

Mirror of V1's trailing_stop_check (V4.4: flat percent, tighter than ADR-based).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from v2_engine import config as cfg
from shared.ledger_schema import Ledger, UnsettledProceed


def trailing_stop_check(ledger: Ledger, save: Callable[[], None]) -> None:
    if not ledger.pod:
        return
    from shared.alpaca_paper import latest_prices, alp_sell

    tickers = [p.ticker for p in ledger.pod]
    prices = latest_prices(tickers)
    if not prices:
        return

    settle_day = (datetime.now(cfg.ET).date() + timedelta(days=1)).isoformat()
    stop_pct = cfg.V1_BASELINE_TRAILING_STOP_PCT

    sells = []
    for p in list(ledger.pod):
        if p.trailing_stop_triggered:
            continue
        cur = prices.get(p.ticker)
        if cur is None:
            continue
        if not p.trailing_high or cur > p.trailing_high:
            p.trailing_high = cur
            p.peak_price = cur
        stop_px = p.trailing_high * (1.0 - stop_pct / 100.0)
        if cur <= stop_px:
            sells.append((p, cur, stop_px, p.trailing_high))

    if not sells:
        save()
        return

    for p, cur, stop_px, peak in sells:
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
