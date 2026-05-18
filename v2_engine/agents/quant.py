"""
v2_engine.agents.quant — Quant Agent.

Gen-0: tries V1's council first. If V1's DB is incomplete or council errors,
falls back to a simple Alpaca-based momentum pick so V2 still trades.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from v2_engine.agents.base import Agent, AgentContext
from v2_engine.evolution.fitness import Candidate
from v2_engine import config as cfg


# A short, liquid universe used by the fallback. Modify in one place.
FALLBACK_UNIVERSE = [
    "AAPL","MSFT","NVDA","TSLA","AMD","META","AMZN","GOOGL","NFLX","AVGO",
    "PLTR","SOFI","MARA","RIOT","COIN","HOOD","SHOP","ROKU","SNAP","UBER",
    "F","GM","BAC","JPM","XOM","CVX","WMT","TGT","DIS","NKE",
]


class Quant(Agent):
    name = "quant"
    requires_lora = True

    def __init__(self, generation: int = 0, adapter_path: str | None = None):
        self.generation = generation
        self.adapter_path = adapter_path

    def run(self, ctx: AgentContext) -> list[Candidate]:
        if self.generation == 0:
            cands = self._gen0_via_v1_council(ctx)
            if cands:
                return cands
            print("V2 Quant: V1 council returned no candidates — using momentum fallback")
            return self._fallback_momentum(ctx)
        return self._gen_n_via_evolved_adapter(ctx)

    # ----- V1 council path -----
    def _gen0_via_v1_council(self, ctx):
        """Import V1's council and call run_council().

        V1's semantic_memory.py opens the DB with a RELATIVE path, so we must
        chdir into V1_REPO_PATH for the duration of the call — otherwise
        SQLite silently creates an empty DB in our cwd and every table lookup
        fails with 'no such table'.
        """
        v1_repo = os.getenv("V1_REPO_PATH", "/opt/tradingap"
                            if os.name == "posix" else r"C:\Projects\tradingap")
        if v1_repo not in sys.path:
            sys.path.insert(0, v1_repo)
        try:
            import council_v2 as v1_council
        except Exception as e:
            print(f"V2 Quant gen-0: cannot import V1 council ({e})")
            return []
        prev_cwd = os.getcwd()
        try:
            os.chdir(v1_repo)
            queue = v1_council.run_council(ctx.trading_day)
        except Exception as e:
            print(f"V2 Quant gen-0: V1 council failed ({e}); returning []")
            return []
        finally:
            os.chdir(prev_cwd)
        print(f"V2 Quant gen-0: V1 council returned {len(queue) if queue else 0} candidates")
        return [self._row_to_candidate(r) for r in (queue or [])]

    # ----- Fallback: rank FALLBACK_UNIVERSE by 5-day momentum via Alpaca -----
    def _fallback_momentum(self, ctx) -> list[Candidate]:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
        except Exception as e:
            print(f"V2 Quant fallback: alpaca SDK missing ({e})")
            return []
        c = StockHistoricalDataClient(
            os.getenv("V2_ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY"),
            os.getenv("V2_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY"),
        )
        end = datetime.now()
        start = end - timedelta(days=10)
        try:
            req = StockBarsRequest(symbol_or_symbols=FALLBACK_UNIVERSE,
                                   timeframe=TimeFrame.Day, start=start, end=end)
            df = c.get_stock_bars(req).df
        except Exception as e:
            print(f"V2 Quant fallback: Alpaca bars fetch failed ({e})")
            return []
        if df is None or df.empty:
            return []

        # Compute 5-day momentum per ticker = (last_close / 5d_ago_close) - 1
        out: list[Candidate] = []
        for ticker in FALLBACK_UNIVERSE:
            try:
                sub = df.xs(ticker, level=0)
                if len(sub) < 5:
                    continue
                last = float(sub["close"].iloc[-1])
                five_ago = float(sub["close"].iloc[-5])
                mom = (last / five_ago - 1.0) * 100.0
                if mom <= 0:
                    continue
                # Map momentum to conviction in [0.70, 0.99]
                conv = max(0.70, min(0.99, 0.70 + mom / 20.0))
                out.append(Candidate(
                    ticker=ticker,
                    conviction=conv,
                    expected_move_pct=mom * 0.6,  # rough 5d → forward 5d projection
                    source="fallback_momentum",
                    thesis=f"5d momentum {mom:+.2f}% (fallback while V1 council DB is incomplete)",
                ))
            except Exception:
                continue
        out.sort(key=lambda c: -c.conviction)
        # Rank 1..N
        for i, c in enumerate(out, 1):
            c.rank = i
        print(f"V2 Quant fallback: generated {len(out)} momentum candidates "
              f"(top: {[(c.ticker, round(c.conviction,2)) for c in out[:5]]})")
        return out[: cfg.V1_BASELINE_QUEUE_SIZE]

    def _gen_n_via_evolved_adapter(self, ctx):
        return []

    @staticmethod
    def _row_to_candidate(row: dict) -> Candidate:
        return Candidate(
            ticker            = row["ticker"],
            conviction        = float(row.get("conviction", 0.0)),
            expected_move_pct = float(row.get("expected_move_pct", 0.0)),
            source            = row.get("source", "judge"),
            thesis            = row.get("thesis", ""),
            rank              = int(row.get("rank", 0)),
        )
