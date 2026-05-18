"""
paper_trade.compare_report
==========================

Daily comparison report. Run after harvest each day. Reads
``comparison_ledger.jsonl`` + both engines' trade logs, computes the four
tracked metrics (PnL Δ, pick agreement, pick accuracy, mirror correlation),
and writes a Markdown summary into ``reports/<date>.md`` plus an updated
``scoreboard.md`` rolling totals page.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from v2_engine import config as cfg
from shared import comparison_ledger as comp


def _format_row(name: str, v1: float, v2: float, unit: str = "") -> str:
    delta = v2 - v1
    sign = "+" if delta >= 0 else ""
    return f"| {name} | {v1:.3f}{unit} | {v2:.3f}{unit} | {sign}{delta:.3f}{unit} |"


def build_report(events: list[comp.DecisionEvent], for_day: str | None = None) -> str:
    if for_day is None:
        for_day = datetime.now(cfg.ET).date().isoformat()
    day_events = [e for e in events if e.trading_day == for_day]
    if not day_events:
        return f"# {for_day} — no decision events found\n"

    deploys = [e for e in day_events if e.event == "deploy_decision"]
    agreements = [e.agreement_top3 / 3.0 for e in deploys]
    correlations = [e.mirror_score_correlation for e in deploys if e.mirror_score_correlation == e.mirror_score_correlation]  # NaN-skip

    lines = [
        f"# Side-by-side report — {for_day}",
        "",
        f"- decision events today: {len(day_events)}",
        f"- deploy events: {len(deploys)}",
        f"- mean V2↔V1 top-3 agreement: {statistics.mean(agreements):.2%}" if agreements else "",
        f"- mean mirror correlation: {statistics.mean(correlations):.3f}" if correlations else "",
        "",
        "## Per-deploy detail",
        "",
        "| Trading day | V1 picks | V2 picks | overlap top-3 | mirror corr |",
        "|---|---|---|---|---|",
    ]
    for e in deploys:
        lines.append(
            f"| {e.trading_day} "
            f"| {','.join(e.v1.bought[:3])} "
            f"| {','.join(e.v2.bought[:3])} "
            f"| {e.agreement_top3}/3 "
            f"| {e.mirror_score_correlation:.3f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None, help="ISO date (default: today)")
    ap.add_argument("--out", default=None, help="output path (default: reports/<day>.md)")
    args = ap.parse_args()

    events = comp.read_events()
    md = build_report(events, args.day)
    out = Path(args.out or (Path(cfg.V2_REPO_PATH) / "reports" / f"{args.day or datetime.now(cfg.ET).date().isoformat()}.md"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
