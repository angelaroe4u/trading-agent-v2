"""Smoke test: write + read one comparison ledger row end-to-end."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import comparison_ledger as comp


def test_roundtrip(tmp_path_factory):
    # tmp_path_factory uses a session-scoped path that pytest doesn't try to
    # auto-clean across files (the per-test tmp_path triggered a Windows-mount
    # recursion bug on this user's machine).
    tmp_root = tmp_path_factory.mktemp("v2_ledger")
    ledger = tmp_root / "comparison.jsonl"
    v1_queue = [{"rank": 1, "ticker": "AXTI", "conviction": 0.88,
                 "expected_move_pct": 4.5, "source": "judge"}]
    v2_queue = [{"rank": 1, "ticker": "AXTI", "conviction": 0.90,
                 "expected_move_pct": 4.7, "source": "judge"}]
    event = comp.build_deploy_event(
        trading_day="2026-05-20",
        v1_queue=v1_queue,
        v2_queue=v2_queue,
        v1_bought=["AXTI"],
        v2_bought=["AXTI"],
        eda_constraints={"market_is_open": True},
        mirror_correlation=1.0,
    )
    comp.write_event(event, path=ledger)
    events = comp.read_events(path=ledger)
    assert len(events) == 1
    e = events[0]
    assert e.trading_day == "2026-05-20"
    assert e.agreement_top3 == 1
    assert e.mirror_score_correlation == 1.0
    assert e.v1.bought == ["AXTI"]
    assert e.v2.bought == ["AXTI"]
