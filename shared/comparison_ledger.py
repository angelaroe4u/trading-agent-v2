"""
shared.comparison_ledger — append-only JSONL log comparing V1 vs V2 decisions.

Schema documented in `COMPARISON_PROTOCOL.md §5`. Every decision event from
either engine writes ONE row. Read-only on V1's side (we never write to
V1's ledger). 5 trading days after the event, ``backfill_realized()``
attaches the actual outcome so we can score accuracy.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from v2_engine import config as cfg


@dataclass
class EngineSnapshot:
    """One engine's state at a decision event."""
    queue: list[dict] = field(default_factory=list)
    bought: list[str] = field(default_factory=list)
    shares: list[float] = field(default_factory=list)
    fills_avg_price: list[float] = field(default_factory=list)
    eda_constraints: dict = field(default_factory=dict)


@dataclass
class DecisionEvent:
    ts: str
    event: str                            # "deploy_decision" | "swap_decision" | "panic_sell" | "harvest"
    trading_day: str
    v1: EngineSnapshot
    v2: EngineSnapshot
    agreement_top3: int = 0
    agreement_top12: int = 0
    mirror_score_correlation: float = 0.0
    realized_5d_pct: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _overlap(a: list[dict], b: list[dict], k: int) -> int:
    ta = {x["ticker"] for x in a[:k]}
    tb = {x["ticker"] for x in b[:k]}
    return len(ta & tb)


def write_event(event: DecisionEvent, path: str | os.PathLike | None = None) -> None:
    """Append one decision event to the comparison ledger."""
    path = Path(path or cfg.V2_COMPARISON_LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event), default=str) + "\n")


def build_deploy_event(
    trading_day: str,
    v1_queue: list[dict],
    v2_queue: list[dict],
    v1_bought: list[str] | None = None,
    v2_bought: list[str] | None = None,
    eda_constraints: dict | None = None,
    mirror_correlation: float = 0.0,
) -> DecisionEvent:
    """Build (but don't yet write) the morning deploy decision event."""
    return DecisionEvent(
        ts = _now_iso(),
        event = "deploy_decision",
        trading_day = trading_day,
        v1 = EngineSnapshot(queue=v1_queue, bought=v1_bought or []),
        v2 = EngineSnapshot(queue=v2_queue, bought=v2_bought or [],
                             eda_constraints=eda_constraints or {}),
        agreement_top3  = _overlap(v1_queue, v2_queue, 3),
        agreement_top12 = _overlap(v1_queue, v2_queue, 12),
        mirror_score_correlation = mirror_correlation,
    )


def read_events(path: str | os.PathLike | None = None) -> list[DecisionEvent]:
    """Read all decision events from the JSONL."""
    path = Path(path or cfg.V2_COMPARISON_LEDGER)
    if not path.exists():
        return []
    out: list[DecisionEvent] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            v1 = EngineSnapshot(**row.get("v1", {}))
            v2 = EngineSnapshot(**row.get("v2", {}))
            out.append(DecisionEvent(
                ts = row["ts"],
                event = row["event"],
                trading_day = row["trading_day"],
                v1 = v1, v2 = v2,
                agreement_top3 = int(row.get("agreement_top3", 0)),
                agreement_top12 = int(row.get("agreement_top12", 0)),
                mirror_score_correlation = float(row.get("mirror_score_correlation", 0.0)),
                realized_5d_pct = dict(row.get("realized_5d_pct", {})),
            ))
    return out


def backfill_realized(
    events: Iterable[DecisionEvent],
    realized_by_ticker_day: dict[tuple[str, str], float],
) -> list[DecisionEvent]:
    """Attach 5-day realised returns to deploy events.

    ``realized_by_ticker_day`` is a precomputed map of
    ``(ticker, trading_day) -> realized_pct``. Caller is responsible for
    measuring 5 trading days forward from the event's date.
    """
    out = []
    for ev in events:
        if ev.event != "deploy_decision":
            out.append(ev)
            continue
        for ticker in set(ev.v1.bought) | set(ev.v2.bought):
            key = (ticker, ev.trading_day)
            if key in realized_by_ticker_day:
                ev.realized_5d_pct[ticker] = realized_by_ticker_day[key]
        out.append(ev)
    return out
