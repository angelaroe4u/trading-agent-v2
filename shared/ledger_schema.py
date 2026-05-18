"""
shared.ledger_schema — common ledger shape.

Matches V1's `executioner_ledger.json` exactly so V2 can read V1 ledgers
without translation and side-by-side comparisons share semantics.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Position:
    ticker: str
    shares: float
    entry_price: float
    entry_ts: float                  # unix or ISO; we accept both
    expected_move_pct: float = 0.0
    thesis: str = ""
    conviction: float = 0.0
    adr_14d: float = 0.0
    # Intraday state
    peak_price: float = 0.0          # alias kept for back-compat
    trailing_high: float = 0.0
    trailing_stop_triggered: bool = False
    divergence_swap_attempted: bool = False
    last_divergence_check: str = ""  # ISO ts


@dataclass
class UnsettledProceed:
    amount: float
    settle_date: str        # YYYY-MM-DD


@dataclass
class Ledger:
    """Mirrors V1's ledger shape — see executioner_v2.py class Ledger."""
    settled_cash: float = 0.0
    unsettled: list[UnsettledProceed] = field(default_factory=list)
    pod: list[Position] = field(default_factory=list)
    bench: list[dict] = field(default_factory=list)
    last_council_queue: list[dict] = field(default_factory=list)
    last_light_watch: str = ""
    code_blue_paged: bool = False
    daily_flush_blacklist: list[str] = field(default_factory=list)
    blacklist_date: str = ""
    day_start_vault: float = 0.0
    last_deploy_date: str = ""

    # ---- I/O ----
    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        return cls(
            settled_cash = float(raw.get("settled_cash", 0.0)),
            unsettled    = [UnsettledProceed(**u) for u in raw.get("unsettled", [])],
            pod          = [Position(**pos) for pos in raw.get("pod", [])],
            bench        = list(raw.get("bench", [])),
            last_council_queue = list(raw.get("last_council_queue", [])),
            last_light_watch   = raw.get("last_light_watch", ""),
            code_blue_paged    = bool(raw.get("code_blue_paged", False)),
            daily_flush_blacklist = list(raw.get("daily_flush_blacklist", [])),
            blacklist_date     = raw.get("blacklist_date", ""),
            day_start_vault    = float(raw.get("day_start_vault", 0.0)),
            last_deploy_date   = raw.get("last_deploy_date", ""),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, default=str))

    # ---- properties ----
    @property
    def unsettled_total(self) -> float:
        return sum(u.amount for u in self.unsettled)

    @property
    def pod_cost(self) -> float:
        return sum(p.shares * p.entry_price for p in self.pod)

    @property
    def total_vault(self) -> float:
        return self.settled_cash + self.unsettled_total + self.pod_cost

    def is_blacklisted(self, ticker: str, today_str: str | None = None) -> bool:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_str = today_str or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        if self.blacklist_date != today_str:
            return False
        return ticker in self.daily_flush_blacklist

    def blacklist_add(self, ticker: str, today_str: str | None = None) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_str = today_str or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        if self.blacklist_date != today_str:
            self.blacklist_date = today_str
            self.daily_flush_blacklist = []
        if ticker not in self.daily_flush_blacklist:
            self.daily_flush_blacklist.append(ticker)
