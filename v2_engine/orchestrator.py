"""
v2_engine.orchestrator — V2 main loop. Replaces V1's executioner_v2.run_day().

Now end-to-end:

  - Night guard (sleep 16:15 -> 9:20)
  - 9:50 morning_deploy: EDA probe -> Generator (Quant agent calls V1 council
    in Gen-0) -> Synthesizer hard constraints -> intraday context filter ->
    rank by fitness (V1-mirror floor) -> conviction-weighted buys [0.5,0.3,0.2]
  - Intraday loop: divergence_check (5 min), trailing_stop_check (2 min),
    light_news_watch (12 min)
  - 15:50 harvest: liquidate pod, proceeds -> unsettled (T+1)

Shares Alpaca paper account with V1. Isolation via client_order_id prefix.
Single source of truth for V2 cash/pod is `v2_ledger.json`.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from v2_engine import config as cfg
from v2_engine.agents.generator import Generator
from v2_engine.agents.eda import EnterpriseDiscoveryAgent
from v2_engine.agents.synthesizer import Synthesizer
from v2_engine.agents.persona import Persona
from v2_engine.evolution.fitness import Candidate, DayState, rank_queue
from v2_engine.intraday.divergence import divergence_check
from v2_engine.intraday.trailing_stop import trailing_stop_check
from v2_engine.intraday.news_watch import light_news_watch
from v2_engine.intraday.context_filter import filter_intraday
from shared.ledger_schema import Ledger, Position, UnsettledProceed
from shared import comparison_ledger as comp


class V2Orchestrator:
    def __init__(self, ledger_path: str | os.PathLike = cfg.V2_LEDGER, generation: int = 0):
        self.ledger_path = Path(ledger_path)
        self.ledger = Ledger.load(self.ledger_path)
        # Seed initial budget on first run
        if self.ledger.settled_cash == 0 and not self.ledger.pod and not self.ledger.unsettled:
            self.ledger.settled_cash = cfg.V2_TRADE_BUDGET_USD
            self.ledger.day_start_vault = cfg.V2_TRADE_BUDGET_USD
            self.ledger.save(self.ledger_path)

        self.generation = generation
        self.eda = EnterpriseDiscoveryAgent()
        self.generator = Generator(generation=generation)
        self.synthesizer = Synthesizer()
        self.persona = Persona()

        # tick-cadence accounting
        self._last_divergence = 0.0
        self._last_trailing = 0.0
        self._last_news = 0.0

    # -----------------------------------------------------------------
    def run_day(self) -> None:
        self._night_guard()
        if self._already_deployed_today():
            print("V2: already deployed today — skipping re-deploy")
        else:
            self._wait_until(*cfg.MORNING_DEPLOY_AT)
            self.morning_deploy()

        # Intraday loop
        while True:
            now = datetime.now(cfg.ET)
            if (now.hour, now.minute) >= cfg.HARVEST_AT:
                break
            self._intraday_tick()
            time.sleep(30)

        self.harvest()

    # -----------------------------------------------------------------
    def morning_deploy(self) -> None:
        today = datetime.now(cfg.ET).date().isoformat()
        self.ledger.day_start_vault = self.ledger.total_vault
        self.ledger.last_deploy_date = today
        self._save()

        constraints = self.eda.probe(self.ledger)

        # Generator returns candidates with conviction + expected_move_pct
        candidates: list[Candidate] = self.generator.generate_queue(today, constraints)
        candidates = self.synthesizer.apply_constraints(candidates, constraints)

        # Intraday context filter: skip "missed the jump" picks
        candidates = filter_intraday(candidates)

        day_state = DayState(
            trading_day=today,
            blacklist=set(self.ledger.daily_flush_blacklist)
                       if self.ledger.blacklist_date == today else set(),
            market_open=constraints.get("market_is_open", True),
        )
        ranked = rank_queue(candidates, day_state, generation=self.generation)
        top_n = ranked[: cfg.V1_BASELINE_POD_SIZE]

        # Conviction-weighted buys
        budget = self.ledger.settled_cash
        weights = self._renormalized_weights(len(top_n))
        for (cand, _fit), weight in zip(top_n, weights):
            dollars = budget * weight
            self._execute_buy(cand, dollars)

        self.ledger.bench = [self._cand_to_dict(c) for c, _ in
                             ranked[cfg.V1_BASELINE_POD_SIZE: cfg.V1_BASELINE_BENCH_DEPTH]]
        self.ledger.last_council_queue = [self._cand_to_dict(c) for c, _ in ranked]
        self._save()

        # Rewrite theses in user-facing voice (best effort)
        for cand, _ in top_n:
            cand.thesis = self.persona.translate(cand.thesis)

        # Emit decision event to comparison ledger
        try:
            ev = comp.build_deploy_event(
                trading_day=today,
                v1_queue=[],   # populated by side_by_side_runner separately
                v2_queue=self.ledger.last_council_queue,
                v2_bought=[p.ticker for p in self.ledger.pod[:3]],
                eda_constraints=constraints,
            )
            comp.write_event(ev)
        except Exception:
            pass

    # -----------------------------------------------------------------
    def _intraday_tick(self) -> None:
        now = time.time()
        if now - self._last_trailing >= cfg.V1_BASELINE_TRAILING_STOP_PCT * 0 + 120:   # every 2 min
            trailing_stop_check(self.ledger, self._save)
            self._last_trailing = now
        if now - self._last_divergence >= cfg.V1_BASELINE_DIVERGENCE_CHECK_INT_MIN * 60:
            divergence_check(self.ledger, self._save)
            self._last_divergence = now
        if now - self._last_news >= cfg.V1_BASELINE_LIGHT_NEWS_INTERVAL_MIN * 60:
            light_news_watch(self.ledger, self._save)
            self._last_news = now

    # -----------------------------------------------------------------
    def harvest(self) -> None:
        from shared.alpaca_paper import alp_sell
        tomorrow = (datetime.now(cfg.ET).date() + timedelta(days=1)).isoformat()
        for pos in list(self.ledger.pod):
            qty, px = alp_sell(pos.ticker, pos.shares)
            if qty > 0 and px > 0:
                self.ledger.unsettled.append(UnsettledProceed(amount=qty * px, settle_date=tomorrow))
        self.ledger.pod.clear()
        self._save()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _already_deployed_today(self) -> bool:
        return self.ledger.last_deploy_date == datetime.now(cfg.ET).date().isoformat()

    def _night_guard(self) -> None:
        now = datetime.now(cfg.ET)
        cutoff = now.replace(hour=cfg.NIGHT_GUARD_CUTOFF[0], minute=cfg.NIGHT_GUARD_CUTOFF[1],
                             second=0, microsecond=0)
        wake = now.replace(hour=cfg.NIGHT_GUARD_WAKE[0], minute=cfg.NIGHT_GUARD_WAKE[1],
                           second=0, microsecond=0)
        if now >= cutoff:
            wake = wake + timedelta(days=1)
        elif now >= wake:
            return   # mid-day, no guard
        while wake.weekday() >= 5:
            wake += timedelta(days=1)
        while datetime.now(cfg.ET) < wake:
            time.sleep(300)
        # Roll T+1 settlements once we wake
        self._roll_settlements()

    def _roll_settlements(self) -> None:
        today = datetime.now(cfg.ET).date().isoformat()
        remaining = []
        for u in self.ledger.unsettled:
            if u.settle_date <= today:
                self.ledger.settled_cash += u.amount
            else:
                remaining.append(u)
        self.ledger.unsettled = remaining
        self._save()

    def _wait_until(self, hour: int, minute: int) -> None:
        target = datetime.now(cfg.ET).replace(hour=hour, minute=minute, second=0, microsecond=0)
        while datetime.now(cfg.ET) < target:
            time.sleep(10)

    def _execute_buy(self, c: Candidate, dollars: float) -> None:
        from shared.alpaca_paper import alp_buy, is_tradeable, adr_14d
        if not is_tradeable(c.ticker):
            return
        shares, px = alp_buy(c.ticker, dollars)
        if shares <= 0 or px <= 0:
            print(f"V2: 0-fill {c.ticker}; no cash deducted")
            return
        self.ledger.settled_cash -= shares * px
        self.ledger.pod.append(Position(
            ticker=c.ticker, shares=shares, entry_price=px,
            entry_ts=datetime.now(cfg.ET).isoformat(),
            expected_move_pct=c.expected_move_pct,
            conviction=c.conviction,
            adr_14d=adr_14d(c.ticker),
            thesis=c.thesis,
            trailing_high=px, peak_price=px,
        ))

    def _renormalized_weights(self, n: int) -> list[float]:
        base = cfg.V1_BASELINE_POSITION_WEIGHTS[:n]
        s = sum(base) or 1.0
        return [w / s for w in base]

    def _cand_to_dict(self, c: Candidate) -> dict:
        return {
            "rank": c.rank, "ticker": c.ticker,
            "conviction": c.conviction, "expected_move_pct": c.expected_move_pct,
            "source": c.source, "thesis": c.thesis,
        }

    def _save(self) -> None:
        self.ledger.save(self.ledger_path)


def main() -> None:
    """Entry point for the systemd service."""
    V2Orchestrator(generation=0).run_day()


if __name__ == "__main__":
    main()
