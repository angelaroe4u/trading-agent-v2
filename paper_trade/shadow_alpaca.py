"""
paper_trade.shadow_alpaca — read-only mirror of V1's Alpaca paper account.

In shadow mode the side-by-side runner needs to *see* V1's current
positions / cash so it can compute the agreement metrics, but it must
never *write* to V1's Alpaca account. This module wraps V1's Alpaca key
in a strict read-only client.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
load_dotenv()


def _client():
    from alpaca.trading.client import TradingClient
    key = os.getenv("V1_ALPACA_API_KEY")
    sec = os.getenv("V1_ALPACA_SECRET_KEY")
    if not (key and sec):
        return None
    return TradingClient(key, sec, paper=True)


def snapshot_v1() -> dict[str, Any]:
    """Return a small dict with V1's current Alpaca-side state.

    NEVER call this from any V2 write path. It exists purely to feed the
    comparison ledger with V1's effective positions.
    """
    tc = _client()
    if tc is None:
        return {"unavailable": True, "reason": "V1_ALPACA_API_KEY not set"}
    try:
        acct = tc.get_account()
        positions = tc.get_all_positions()
    except Exception as e:
        return {"unavailable": True, "reason": str(e)}
    return {
        "alpaca_cash_shown": float(getattr(acct, "cash", 0.0)),
        "equity": float(getattr(acct, "equity", 0.0)),
        "positions": [
            {"ticker": p.symbol,
             "qty": float(p.qty),
             "avg_entry_price": float(p.avg_entry_price),
             "market_value": float(p.market_value)}
            for p in positions
        ],
    }
