"""
paper_trade.side_by_side_runner
===============================

Drives a full trading day where V1 (in C:\\Projects\\tradingap) and V2 (this
folder) both deploy at 9:55 ET against their *separate* Alpaca paper
accounts and we write one row to ``comparison_ledger.jsonl`` per decision
event.

Three operating modes:

  shadow      V2 makes decisions but does NOT submit orders. Pure paper-
              shadow of V1 — used while we verify the mirror floor. Default.

  parallel    Both engines actually place orders against their own Alpaca
              keys. Use once shadow mode shows mirror correlation ≥ 0.85
              for 5 trading days.

  v2_only     V2 runs alone; V1 is offline. Used post-promotion.

Run:

    python -m paper_trade.side_by_side_runner --mode shadow
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Make V1's modules importable as a read-only mirror.
V1_REPO = os.getenv("V1_REPO_PATH", r"C:\Projects\tradingap")
if Path(V1_REPO).exists() and V1_REPO not in sys.path:
    sys.path.insert(0, V1_REPO)

from v2_engine import config as cfg
from v2_engine.orchestrator import V2Orchestrator
from v2_engine.evolution.fitness import Candidate, DayState, rank_queue, mirror_score
from shared import comparison_ledger as comp
from shared.ledger_schema import Ledger


# ---------------------------------------------------------------------------

def _load_v1_council_queue(trading_day: str) -> list[dict]:
    """Read V1's council queue from today's decision snapshot.

    V1 writes its queue snapshot to
    ``C:\\Projects\\tradingap\\memory\\decisions\\<YYYY-MM-DD>\\council_queue.json``
    (per V1's memory.py). If the file doesn't exist yet (it's < 9:51), we
    fall back to V1's live ledger ``last_council_queue``.
    """
    decisions_dir = Path(V1_REPO) / "memory" / "decisions" / trading_day
    queue_file = decisions_dir / "council_queue.json"
    if queue_file.exists():
        return json.loads(queue_file.read_text())
    # fallback: V1's live ledger
    ledger_path = Path(os.getenv("V1_LEDGER", str(Path(V1_REPO) / "executioner_ledger.json")))
    if ledger_path.exists():
        return list(Ledger.load(ledger_path).last_council_queue)
    return []


def _v1_bought_today(trading_day: str) -> list[str]:
    ledger_path = Path(os.getenv("V1_LEDGER", str(Path(V1_REPO) / "executioner_ledger.json")))
    if not ledger_path.exists():
        return []
    ledger = Ledger.load(ledger_path)
    if ledger.last_deploy_date != trading_day:
        return []
    return [p.ticker for p in ledger.pod[:3]]


def _candidates_from_v1_queue(queue: list[dict]) -> list[Candidate]:
    return [Candidate(
        ticker            = q["ticker"],
        conviction        = float(q.get("conviction", 0.0)),
        expected_move_pct = float(q.get("expected_move_pct", 0.0)),
        source            = q.get("source", "judge"),
        thesis            = q.get("thesis", ""),
        rank              = int(q.get("rank", 0)),
    ) for q in queue]


def _mirror_correlation(v1_queue: list[dict], v2_queue: list[dict]) -> float:
    """Spearman between V1's rank and V2's mirror_score-implied rank."""
    if not v1_queue or not v2_queue:
        return float("nan")
    day = DayState(trading_day=datetime.now(cfg.ET).date().isoformat())
    v1_cands = _candidates_from_v1_queue(v1_queue)
    scores = {c.ticker: mirror_score(c, day) for c in v1_cands}
    # rank by V1 source vs by our score
    from v2_engine.evolution.fitness import _spearman
    common = [c for c in v1_cands if c.ticker in scores]
    if len(common) < 2:
        return float("nan")
    v1_ranks = [c.rank for c in common]
    our_basis = [-scores[c.ticker] for c in common]
    return _spearman(v1_ranks, our_basis)


# ---------------------------------------------------------------------------

def run(mode: str = "shadow") -> None:
    today = datetime.now(cfg.ET).date().isoformat()
    print(f"[side_by_side] mode={mode}  trading_day={today}")

    # --- V2 deploys (shadow or real) ---
    orch = V2Orchestrator(generation=0)
    if mode == "shadow":
        # We only want V2's queue, not its orders. Hack: run the generator
        # + synthesizer pipeline without _execute_buy.
        constraints = orch.eda.probe(orch.ledger)
        v2_cands = orch.generator.generate_queue(today, constraints)
        v2_cands = orch.synthesizer.apply_constraints(v2_cands, constraints)
        day_state = DayState(trading_day=today)
        v2_ranked = rank_queue(v2_cands, day_state, generation=0)
        v2_queue = [orch._cand_to_dict(c) for c, _ in v2_ranked]
        v2_bought: list[str] = []
    else:
        orch.run_day()
        v2_queue = orch.ledger.last_council_queue
        v2_bought = [p.ticker for p in orch.ledger.pod[:3]]

    # --- Read V1's decision after V1 has deployed ---
    # Side-by-side runner is expected to fire at 9:56 ET, one minute after
    # both engines deploy. Adjust to your own schedule.
    v1_queue = _load_v1_council_queue(today)
    v1_bought = _v1_bought_today(today)

    # --- Write comparison row ---
    event = comp.build_deploy_event(
        trading_day=today,
        v1_queue=v1_queue,
        v2_queue=v2_queue,
        v1_bought=v1_bought,
        v2_bought=v2_bought,
        eda_constraints=orch.eda.last_probe,
        mirror_correlation=_mirror_correlation(v1_queue, v2_queue),
    )
    comp.write_event(event)
    print(f"[side_by_side] wrote event: agreement_top3={event.agreement_top3}/3 "
          f"corr={event.mirror_score_correlation:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["shadow", "parallel", "v2_only"], default="shadow")
    args = ap.parse_args()
    run(mode=args.mode)


if __name__ == "__main__":
    main()
