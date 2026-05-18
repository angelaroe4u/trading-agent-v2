"""
v2_engine.agents.eda — Enterprise Discovery Agent (PDF §5).

Runs BEFORE the Quant/Synthesizer so they can't propose operationally
invalid trades. Hard-constraint injection per PDF §5.

Probes:
  - Alpaca account flags (PDT, multiplier, daytrade count, cash shown)
  - Alpaca clock (is_open, next_close)
  - Symbol-level tradability (fractionable, marginable, shortable, etc.)
  - Internal ledger state (T+1 runway, blacklist date)
  - Detected anomalies (gap, VIX spike, halt) — used by Generator to
    decide between fast and full graph
"""
from __future__ import annotations

import os
from typing import Any

from v2_engine.agents.base import Agent, AgentContext
from shared.ledger_schema import Ledger


class EnterpriseDiscoveryAgent(Agent):
    name = "eda"

    def __init__(self):
        self.last_probe: dict[str, Any] = {}

    def probe(self, ledger: Ledger) -> dict[str, Any]:
        constraints: dict[str, Any] = {}
        try:
            from shared.alpaca_paper import probe_account
            constraints.update(probe_account())
        except Exception as e:
            constraints["alpaca_probe_error"] = str(e)
            constraints["market_is_open"] = True   # optimistic fallback for backtest paths

        # T+1 runway from internal ledger (V1 Fix #5 — never use account.cash)
        constraints["settled_cash"] = ledger.settled_cash
        constraints["unsettled_total"] = ledger.unsettled_total
        constraints["pod_size"] = len(ledger.pod)

        # Anomaly hooks — fill in once we hook market data
        constraints.setdefault("anomaly_detected", False)
        constraints.setdefault("vix_jump_pct", 0.0)
        constraints.setdefault("spy_change_pct", 0.0)

        # PDT lock
        if (constraints.get("daytrade_count", 0) >= 3
                and ledger.total_vault < 25_000):
            constraints["pattern_day_trader_locked"] = True

        self.last_probe = constraints
        return constraints

    def run(self, ctx: AgentContext) -> dict:
        # The orchestrator calls .probe(ledger) directly; this is the ABC parity stub.
        return self.last_probe
