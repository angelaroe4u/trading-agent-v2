"""Single-account dual-ledger correctness checks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2_engine import config as cfg


def test_v2_prefix_constant():
    assert cfg.V2_CLIENT_ORDER_ID_PREFIX == "v2_"
    assert cfg.V1_CLIENT_ORDER_ID_PREFIX == "v1_"
    # The two prefixes must never share a prefix relationship that would
    # cause filter("v2_") to also catch V1 orders.
    assert not cfg.V1_CLIENT_ORDER_ID_PREFIX.startswith(cfg.V2_CLIENT_ORDER_ID_PREFIX)
    assert not cfg.V2_CLIENT_ORDER_ID_PREFIX.startswith(cfg.V1_CLIENT_ORDER_ID_PREFIX)


def test_v2_budget_separate_from_v1():
    # Defaults should match the user's directive: $2k V2 slice
    assert cfg.V2_TRADE_BUDGET_USD == 2000.0


def test_client_order_id_format():
    from shared.alpaca_paper import _client_order_id
    coid = _client_order_id("AAPL")
    assert coid.startswith("v2_")
    assert "AAPL" in coid
    assert len(coid) > 12   # prefix + ts + ticker + hex


def test_two_orders_get_unique_ids():
    from shared.alpaca_paper import _client_order_id
    a = _client_order_id("AAPL")
    b = _client_order_id("AAPL")
    assert a != b
