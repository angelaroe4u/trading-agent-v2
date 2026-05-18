"""
shared.alpaca_paper — thin wrapper around alpaca-py for V2's orders.

DESIGN: V2 shares one paper account with V1. Isolation is enforced by
``client_order_id`` prefix: every V2 order is tagged ``v2_<unix>_<ticker>``.
V2's reconciliation only inspects orders matching its prefix; V1's reconcile
only matches the rest. The shared paper account is the truth for fills, but
each ledger is the truth for its own pod/cash.

Mirrors V1's executioner_v2.py helpers with the same critical fixes:
- V1 Fix #1: floor-round quantities on sell
- V1 Fix #2: no cash deduct on 0-fill
- V1 Fix #3: 30s polling
- V1 Fix #4: is_tradeable() validation
- V1 Fix #5: never read account.cash for budget decisions
"""
from __future__ import annotations

import math
import os
import time
import uuid
from typing import Tuple

from dotenv import load_dotenv
load_dotenv()

from v2_engine import config as cfg


# ---------------------------------------------------------------------------

def _trading_client():
    """V2 uses V2_ALPACA_* if set, else falls back to ALPACA_* (V1's keys)."""
    from alpaca.trading.client import TradingClient
    api_key    = os.getenv("V2_ALPACA_API_KEY")    or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("V2_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not (api_key and secret_key):
        raise RuntimeError("Neither V2_ALPACA_* nor ALPACA_* keys set in .env")
    return TradingClient(api_key, secret_key, paper=True)


def _data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    api_key    = os.getenv("V2_ALPACA_API_KEY")    or os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("V2_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    return StockHistoricalDataClient(api_key, secret_key)


def _client_order_id(ticker: str) -> str:
    """Tag V2 orders so reconcile can filter them out of V1's view."""
    # Use uuid4 to guarantee uniqueness even if two orders fire same second.
    return f"{cfg.V2_CLIENT_ORDER_ID_PREFIX}{int(time.time())}_{ticker}_{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def latest_price(ticker: str) -> float | None:
    from alpaca.data.requests import StockLatestTradeRequest
    try:
        c = _data_client()
        trade = c.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=ticker))
        return float(trade[ticker].price)
    except Exception:
        return None


def latest_prices(tickers: list[str]) -> dict[str, float]:
    from alpaca.data.requests import StockLatestTradeRequest
    try:
        c = _data_client()
        trades = c.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=tickers))
        return {t: float(trades[t].price) for t in tickers if t in trades}
    except Exception:
        return {}


def day_open(ticker: str) -> float | None:
    """Today's regular-session open (Alpaca daily bar)."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from datetime import datetime, timezone, timedelta
    try:
        c = _data_client()
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=2),
        )
        bars = c.get_stock_bars(req).df
        if bars is None or bars.empty:
            return None
        return float(bars.iloc[-1]["open"])
    except Exception:
        return None


def adr_14d(ticker: str) -> float:
    """14-day Average Daily Range as a percent of close. V1 parity."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from datetime import datetime, timezone, timedelta
    try:
        c = _data_client()
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=30),
        )
        df = c.get_stock_bars(req).df
        if df is None or df.empty:
            return 0.0
        df = df.tail(14)
        ranges = ((df["high"] - df["low"]) / df["close"]) * 100.0
        return float(ranges.mean())
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Pre-trade validation — V1 Fix #4
# ---------------------------------------------------------------------------

def is_tradeable(ticker: str) -> bool:
    try:
        asset = _trading_client().get_asset(ticker)
        return bool(asset.tradable) and str(asset.status).lower() == "active"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Orders — V1 Fixes 1/2/3 + V2 client_order_id prefix
# ---------------------------------------------------------------------------

def alp_buy(ticker: str, dollars: float,
            whole_shares: bool = False, poll_seconds: int = 30) -> Tuple[float, float]:
    """Notional market buy tagged with V2's client_order_id prefix.

    Returns ``(filled_qty, filled_avg_price)``. On 0-fill, returns ``(0.0, 0.0)``
    — caller MUST NOT deduct cash (V1 Fix #2).
    """
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    tc = _trading_client()
    coid = _client_order_id(ticker)
    if whole_shares:
        px = latest_price(ticker) or 1.0
        qty = max(int(dollars // px), 1)
        order_req = MarketOrderRequest(
            symbol=ticker, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            client_order_id=coid,
        )
    else:
        order_req = MarketOrderRequest(
            symbol=ticker, notional=round(dollars, 2),
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            client_order_id=coid,
        )
    o = tc.submit_order(order_req)
    return _poll_fill(tc, o, poll_seconds)


def alp_sell(ticker: str, shares: float, poll_seconds: int = 30) -> Tuple[float, float]:
    """Sell; floor-rounds quantity (V1 Fix #1); tagged client_order_id."""
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    qty = math.floor(shares * 1_000_000) / 1_000_000
    if qty <= 0:
        return 0.0, 0.0
    tc = _trading_client()
    coid = _client_order_id(ticker)
    o = tc.submit_order(MarketOrderRequest(
        symbol=ticker, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        client_order_id=coid,
    ))
    return _poll_fill(tc, o, poll_seconds)


def _poll_fill(tc, order, poll_seconds: int) -> Tuple[float, float]:
    iters = max(1, poll_seconds // 2)
    for _ in range(iters):
        time.sleep(2)
        try:
            fill = tc.get_order_by_id(order.id)
        except Exception:
            continue
        status = str(fill.status).lower()
        if "fill" in status:
            return float(fill.filled_qty or 0), float(fill.filled_avg_price or 0)
        if status in ("canceled", "expired", "rejected"):
            return 0.0, 0.0
    try:
        tc.cancel_order_by_id(order.id)
    except Exception:
        pass
    return 0.0, 0.0


# ---------------------------------------------------------------------------
# V2-scoped reconcile — only sees V2 orders
# ---------------------------------------------------------------------------

def list_v2_orders(limit: int = 500) -> list:
    """Return only orders whose client_order_id starts with V2's prefix."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    try:
        tc = _trading_client()
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
        all_orders = tc.get_orders(filter=req)
    except Exception:
        return []
    pfx = cfg.V2_CLIENT_ORDER_ID_PREFIX
    return [o for o in all_orders if (o.client_order_id or "").startswith(pfx)]


def list_v2_positions() -> list[dict]:
    """Best-effort: return Alpaca positions attributable to V2.

    Single-account note: Alpaca aggregates positions per symbol; we can't
    truly split V1 from V2 on the broker side. We surface ALL positions
    and let each engine's ledger be the source-of-truth for *its* share.
    Use this only for sanity checks (e.g. did SOME order fill on this symbol)
    not for budget accounting.
    """
    try:
        tc = _trading_client()
        return [{"ticker": p.symbol,
                 "qty": float(p.qty),
                 "avg_entry_price": float(p.avg_entry_price),
                 "market_value": float(p.market_value)}
                for p in tc.get_all_positions()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# EDA — discovery probe
# ---------------------------------------------------------------------------

def probe_account() -> dict:
    """Return hard constraints the Synthesizer must respect."""
    try:
        tc = _trading_client()
        acct = tc.get_account()
        clock = tc.get_clock()
    except Exception as e:
        return {"alpaca_probe_error": str(e), "market_is_open": False}
    return {
        "is_paper": True,
        "pattern_day_trader": bool(getattr(acct, "pattern_day_trader", False)),
        "daytrade_count": int(getattr(acct, "daytrade_count", 0)),
        "multiplier": float(getattr(acct, "multiplier", 1)),
        "regt_buying_power": float(getattr(acct, "regt_buying_power", 0.0)),
        # Reminder: this is the shared paper-account cash. Do NOT use for budget.
        "alpaca_cash_shown": float(getattr(acct, "cash", 0.0)),
        "market_is_open": bool(clock.is_open),
        "next_close": str(clock.next_close),
    }
