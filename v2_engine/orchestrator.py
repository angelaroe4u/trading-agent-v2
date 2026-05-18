"""v2_engine.orchestrator — V2 main loop (end-to-end)."""
from __future__ import annotations

import json
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


DECISIONS_DIR = Path(cfg.V2_REPO_PATH) / "memory" / "decisions"


def _log_trade(action, ticker, shares, price, reason="", pnl=None):
    """Append one row to v2_trade_log.jsonl. Powers dashboard markers."""
    row = {
        "ts": datetime.now(cfg.ET).isoformat(),
        "action": action, "ticker": ticker,
        "shares": shares, "price": price,
        "reason": reason, "pnl": pnl,
    }
    p = Path(cfg.V2_TRADE_LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _snapshot_council(trading_day, queue_dicts, bought_tickers):
    """Write memory/decisions/<day>/council_queue.json + bought.json.

    Required for the dashboard's per-trade drilldown to find the council's
    choice logic on historical days. Also lets the historical-replay test
    pass once V2 (or a patched V1) has been writing these.
    """
    day_dir = DECISIONS_DIR / trading_day
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "council_queue.json").write_text(json.dumps(queue_dicts, indent=2))
    (day_dir / "bought.json").write_text(json.dumps({"tickers": bought_tickers}, indent=2))


class V2Orchestrator:
    def __init__(self, ledger_path=cfg.V2_LEDGER, generation=0):
        self.ledger_path = Path(ledger_path)
        self.ledger = Ledger.load(self.ledger_path)
        if (self.ledger.settled_cash == 0 and not self.ledger.pod
                and not self.ledger.unsettled):
            self.ledger.settled_cash = cfg.V2_TRADE_BUDGET_USD
            self.ledger.day_start_vault = cfg.V2_TRADE_BUDGET_USD
            self.ledger.save(self.ledger_path)
        self.generation = generation
        self.eda = EnterpriseDiscoveryAgent()
        self.generator = Generator(generation=generation)
        self.synthesizer = Synthesizer()
        self.persona = Persona()
        self._last_divergence = 0.0
        self._last_trailing = 0.0
        self._last_news = 0.0

    def run_day(self):
        self._night_guard()
        if self._already_deployed_today():
            print("V2: already deployed today")
        else:
            self._wait_until(*cfg.MORNING_DEPLOY_AT)
            self.morning_deploy()
        while True:
            now = datetime.now(cfg.ET)
            if (now.hour, now.minute) >= cfg.HARVEST_AT:
                break
            self._intraday_tick()
            time.sleep(30)
        self.harvest()

    def morning_deploy(self):
        today = datetime.now(cfg.ET).date().isoformat()
        self.ledger.day_start_vault = self.ledger.total_vault
        self.ledger.last_deploy_date = today
        self._save()
        constraints = self.eda.probe(self.ledger)
        candidates = self.generator.generate_queue(today, constraints)
        candidates = self.synthesizer.apply_constraints(candidates, constraints)
        candidates = filter_intraday(candidates)
        day_state = DayState(
            trading_day=today,
            blacklist=set(self.ledger.daily_flush_blacklist)
                if self.ledger.blacklist_date == today else set(),
            market_open=constraints.get("market_is_open", True),
        )
        ranked = rank_queue(candidates, day_state, generation=self.generation)
        top_n = ranked[: cfg.V1_BASELINE_POD_SIZE]
        budget = self.ledger.settled_cash
        weights = self._renormalized_weights(len(top_n))
        for (cand, _fit), w in zip(top_n, weights):
            self._execute_buy(cand, budget * w)
        self.ledger.bench = [self._cand_to_dict(c) for c, _ in
                             ranked[cfg.V1_BASELINE_POD_SIZE: cfg.V1_BASELINE_BENCH_DEPTH]]
        self.ledger.last_council_queue = [self._cand_to_dict(c) for c, _ in ranked]
        self._save()
        # Per-day snapshot for dashboard drilldown + replay test
        try:
            _snapshot_council(today, self.ledger.last_council_queue,
                              [p.ticker for p in self.ledger.pod[:3]])
        except Exception as e:
            print(f"V2: snapshot failed: {e}")
        for cand, _ in top_n:
            cand.thesis = self.persona.translate(cand.thesis)
        try:
            ev = comp.build_deploy_event(
                trading_day=today, v1_queue=[],
                v2_queue=self.ledger.last_council_queue,
                v2_bought=[p.ticker for p in self.ledger.pod[:3]],
                eda_constraints=constraints,
            )
            comp.write_event(ev)
        except Exception:
            pass

    def _intraday_tick(self):
        now = time.time()
        if now - self._last_trailing >= 120:
            trailing_stop_check(self.ledger, self._save)
            self._last_trailing = now
        if now - self._last_divergence >= cfg.V1_BASELINE_DIVERGENCE_CHECK_INT_MIN * 60:
            divergence_check(self.ledger, self._save)
            self._last_divergence = now
        if now - self._last_news >= cfg.V1_BASELINE_LIGHT_NEWS_INTERVAL_MIN * 60:
            light_news_watch(self.ledger, self._save)
            self._last_news = now

    def harvest(self):
        from shared.alpaca_paper import alp_sell
        tomorrow = (datetime.now(cfg.ET).date() + timedelta(days=1)).isoformat()
        for pos in list(self.ledger.pod):
            qty, px = alp_sell(pos.ticker, pos.shares)
            if qty > 0 and px > 0:
                pnl = (px - pos.entry_price) * qty
                _log_trade("HARVEST-SELL", pos.ticker, qty, px,
                           reason="end-of-day harvest", pnl=pnl)
                self.ledger.unsettled.append(UnsettledProceed(amount=qty * px, settle_date=tomorrow))
        self.ledger.pod.clear()
        self._save()

    def _already_deployed_today(self):
        return self.ledger.last_deploy_date == datetime.now(cfg.ET).date().isoformat()

    def _night_guard(self):
        now = datetime.now(cfg.ET)
        cutoff = now.replace(hour=cfg.NIGHT_GUARD_CUTOFF[0], minute=cfg.NIGHT_GUARD_CUTOFF[1],
                             second=0, microsecond=0)
        wake = now.replace(hour=cfg.NIGHT_GUARD_WAKE[0], minute=cfg.NIGHT_GUARD_WAKE[1],
                           second=0, microsecond=0)
        if now >= cutoff:
            wake += timedelta(days=1)
        elif now >= wake:
            return
        while wake.weekday() >= 5:
            wake += timedelta(days=1)
        while datetime.now(cfg.ET) < wake:
            time.sleep(300)
        self._roll_settlements()

    def _roll_settlements(self):
        today = datetime.now(cfg.ET).date().isoformat()
        remaining = []
        for u in self.ledger.unsettled:
            if u.settle_date <= today:
                self.ledger.settled_cash += u.amount
            else:
                remaining.append(u)
        self.ledger.unsettled = remaining
        self._save()

    def _wait_until(self, hour, minute):
        target = datetime.now(cfg.ET).replace(hour=hour, minute=minute, second=0, microsecond=0)
        while datetime.now(cfg.ET) < target:
            time.sleep(10)

    def _execute_buy(self, c, dollars):
        from shared.alpaca_paper import alp_buy, is_tradeable, adr_14d
        if not is_tradeable(c.ticker):
            return
        shares, px = alp_buy(c.ticker, dollars)
        if shares <= 0 or px <= 0:
            return
        self.ledger.settled_cash -= shares * px
        self.ledger.pod.append(Position(
            ticker=c.ticker, shares=shares, entry_price=px,
            entry_ts=datetime.now(cfg.ET).isoformat(),
            expected_move_pct=c.expected_move_pct, conviction=c.conviction,
            adr_14d=adr_14d(c.ticker), thesis=c.thesis,
            trailing_high=px, peak_price=px,
        ))
        _log_trade("BUY", c.ticker, shares, px,
                   reason=f"morning deploy: {c.thesis[:120]}")

    def _renormalized_weights(self, n):
        base = cfg.V1_BASELINE_POSITION_WEIGHTS[:n]
        s = sum(base) or 1.0
        return [w / s for w in base]

    def _cand_to_dict(self, c):
        return {"rank": c.rank, "ticker": c.ticker, "conviction": c.conviction,
                "expected_move_pct": c.expected_move_pct, "source": c.source,
                "thesis": c.thesis}

    def _save(self):
        self.ledger.save(self.ledger_path)


def main():
    V2Orchestrator(generation=0).run_day()


if __name__ == "__main__":
    main()
