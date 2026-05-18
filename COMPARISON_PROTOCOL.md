# Side-by-Side Paper-Trading Protocol

## 1. Goal

Measure the **decision-accuracy delta** between V1 and V2 in real market
conditions. Not just P&L — also: did V2 pick what V1 picked? When they
differed, who was right?

## 2. Setup

| Item | V1 | V2 |
|---|---|---|
| Repo | `/opt/tradingap` (Hetzner) | `Trading Agent 2.0/` (laptop or sibling box) |
| Alpaca paper key | `ALPACA_API_KEY` in `/opt/tradingap/.env` | **new key** in `Trading Agent 2.0/.env` as `V2_ALPACA_API_KEY` |
| Ledger | `executioner_ledger.json` | `v2_ledger.json` (same schema) |
| Trade log | `trade_log.jsonl` | `v2_trade_log.jsonl` |
| Starting cash | $2,000 (current V1 vault) | $2,000 (mirror V1 start; **never** use Alpaca's $100k) |
| Deploy time | 9:55 ET | 9:55 ET |
| Harvest time | 15:50 ET | 15:50 ET |

Both engines see the **same market data** (Alpaca's data feed is identical
across paper accounts). Both compute against the same
`semantic_memory.db` (V2 reads it through the new hybrid layer).

## 3. The daily routine

```
09:00  EDA probe (V2 only) — confirm both Alpaca accounts are live,
        log margin / PDT status, market is open today.

09:20  Both engines wake. roll_settlements() on both ledgers.

09:50  Both engines run morning_deploy.
        V1 → council_v2.run_council(today)
        V2 → orchestrator.run_day(today)
        Both emit a `queue` of 12 ranked candidates with conviction,
        expected_move_pct, thesis, source.

09:51  → comparison_ledger.jsonl writes ONE row:
        {
          "event": "deploy_decision",
          "date": "...",
          "v1_queue": [...12...],
          "v2_queue": [...12...],
          "agreement_top3": <int>,        # how many of V2's top 3 are in V1's top 3
          "agreement_top12": <int>,
          "mirror_score_correlation": <float>,
        }

09:55  Both engines buy their top 3 with [0.50, 0.30, 0.20] weights.

11:30 / 13:00 / 14:30   Divergence checks on both pods.
        V1 may call Opus to swap.
        V2 may call its Synthesizer to swap.
        Each swap event → comparison_ledger row with both engines'
        swap-or-hold decision on each other's positions
        (counterfactual: what would V1 have done with V2's position?).

15:50  Both engines harvest. Both write daily P&L to their ledgers.

16:00  compare_report.py runs:
        - Realized PnL today: V1 vs V2
        - Decisions made today: V1 vs V2
        - Per-pick accuracy: did the picker's expected_move actually realize?
        - Cumulative scoreboard.

16:35  Email goes out as today.  Add a "V1 vs V2 today" appendix.
```

## 4. The four numbers we track

| Metric | Definition | Target |
|---|---|---|
| **PnL Δ** | `V2_daily_pnl - V1_daily_pnl` | rolling mean > 0 |
| **Pick agreement** | `|V1_top3 ∩ V2_top3| / 3` | > 0.66 during mirror phase, falls as λ grows |
| **Pick accuracy** | for each engine, `realized_5d_return >= expected_move_pct` count / total picks | V2 ≥ V1 |
| **Mirror correlation** | Spearman rank corr of V1 vs V2 queue rankings | per `FITNESS_FUNCTION.md §5` |

PnL alone is too noisy (3 names × small caps × 4 weeks ≠ a signal). Pick
accuracy is the real edge metric.

## 5. Decision-event schema (`comparison_ledger.jsonl`)

One JSON line per decision event. Schema:

```jsonc
{
  "ts": "2026-05-20T09:51:14-04:00",
  "event": "deploy_decision" | "swap_decision" | "panic_sell" | "harvest",
  "trading_day": "2026-05-20",
  "v1": {
    "queue": [ { "rank":1, "ticker":"...", "conviction":..., "expected_move_pct":..., "source":"...", "thesis":"..." }, ... ],
    "bought": [ "AAA", "BBB", "CCC" ],
    "shares": [ ..., ..., ... ],
    "fills_avg_price": [ ..., ..., ... ]
  },
  "v2": {
    "queue": [ ... ],
    "bought": [ ... ],
    "shares": [ ... ],
    "fills_avg_price": [ ... ],
    "eda_constraints": { "pattern_day_trader": false, "daytrade_count": 0, ... }
  },
  "agreement_top3": 2,
  "agreement_top12": 8,
  "mirror_score_correlation": 0.93,
  "realized_5d_pct": { "AAA": 2.1, "BBB": -0.8, "CCC": 4.4, ... }    // filled in 5 days later
}
```

The last field is back-filled by `compare_report.py` 5 trading days
after the event.

## 6. Failure isolation

If V2 crashes mid-day, V1 keeps trading. V1's behavior is *unchanged*
by V2's presence. The shared market data layer is read-only from V2's
side; V2 *never* writes to `executioner_ledger.json`.

If V1's Hetzner box dies, V2 is unaffected — it has its own ledger and
its own Alpaca key.

## 7. Promotion criteria (when does V2 take over?)

V2 replaces V1 as the primary engine when **all** are true over a
20-trading-day rolling window:

1. `PnL Δ` mean > 0
2. `Pick accuracy` V2 ≥ V1
3. Sharpe ratio V2 > Sharpe V1
4. Max-drawdown V2 ≤ max-drawdown V1 × 1.20  (no worse than 20 % worse)
5. Mirror correlation ≥ 0.85 (we haven't drifted into something unrecognizable)

Until then, V2 is observatory.
