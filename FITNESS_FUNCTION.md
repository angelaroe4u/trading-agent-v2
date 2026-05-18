# Fitness Function — V1 Mirror, then Improve

> The fitness function is the **single most important file** in this project.
> It is the selection pressure for every Darwinian-bred quant model. Get this
> wrong and the evolution converges on the wrong objective.

## 1. The user's instruction (verbatim)

> "Fitness Function that will judge the newly bred quantitative models should
> mirror our current decision making and improve from there."

Two requirements stacked:

- **Mirror** — on V1's historical decisions, the fitness function must rank
  trades the same way V1 *implicitly* ranked them. If V1 chose pick `A`
  over `B` on day `D`, the fitness function evaluated on the same
  `(A, B, D, market_state)` must return `fitness(A) >= fitness(B)`.
- **Improve** — beyond that floor, fitness must additionally reward
  outcome quality: higher Sharpe, lower drawdown, better hit-rate. Where
  the mirror constraint is silent (e.g., picks V1 never considered),
  outcome quality is the only signal.

## 2. V1's implicit objective (decoded)

V1 never wrote down a single objective function. Its decisions are the
*joint product* of the council's prompts and the executioner's mechanical
rules. We reverse-engineered the objective from
`council_v2.py` + `executioner_v2.py`:

```
V1_OBJECTIVE(candidate)  =
      α  × conviction                                  # judge's confidence
    + β  × expected_move_pct                           # judge's forecast
    + γ  × is_above_conviction_gate(0.70)              # hard gate
    - δ  × intraday_already_realized_fraction          # missed-the-jump penalty
    + ε  × source_judge_bonus                          # if "source"="judge" (Opus self-pick)
    - ζ  × ticker_blacklisted_today                    # daily flush blacklist
```

The empirical weights (read from V1 code; see `v2_engine/config.py`
constants `V1_BASELINE_*`):

| Term | Weight | Source |
|---|---|---|
| `conviction`           | α = 1.00 | `POSITION_WEIGHTS` rank-by-conviction |
| `expected_move_pct`    | β = 0.50 | secondary sort in `_judge_synthesize` |
| `conviction_gate`      | γ = ∞    | hard gate at 0.70 — anything below is rejected outright |
| `intraday_realized`    | δ = 1.00 | `INTRADAY_FILTER_SKIP_THRESHOLD = 0.60` is a hard skip |
| `source = "judge"`     | ε = 0.05 | small Opus-self-pick preference |
| `blacklisted_today`    | ζ = ∞    | hard reject in `morning_deploy` |

The position-sizing weights `[0.50, 0.30, 0.20]` are *the same family of
weights*: they monotonically map conviction-rank → capital share.

## 3. The V1-mirror floor

```
mirror_score(c, day) =
      1.00 * c.conviction
    + 0.50 * c.expected_move_pct / 5.0        # normalized to per-day
    + 0.05 * (c.source == "judge")
    - 1.00 * c.intraday_realized_fraction
    - INF  * (c.conviction < 0.70)
    - INF  * (c.ticker in blacklist)
    - INF  * (not c.is_tradeable)
```

Higher score = ranked higher. Property we must verify in
`tests/test_fitness_mirrors_v1.py`:

> For every historical V1 deploy day `D` in `trade_log.jsonl`, sort the
> council's `queue` for day `D` by `mirror_score(·, D)` and assert that
> the top-3 by score == the top-3 V1 actually bought.

If that test passes, the mirror floor is correct.

## 4. The outcome-quality terms (the "improve" half)

Once the mirror floor is met, we add forward-looking outcome terms:

```
outcome_score(c, day) =
      w_sharpe   * realized_5d_sharpe(c)
    + w_hit      * realized_hit_rate_5d(c)
    + w_pnl      * realized_pnl_pct_5d(c)
    - w_dd       * realized_max_drawdown_pct_5d(c)
    - w_swap     * triggered_divergence_swap(c)
    - w_panic    * triggered_panic_sell(c)
    - w_cost     * llm_inference_cost(c)
```

Defaults (tunable per generation):

| Weight | Value | Why |
|---|---|---|
| `w_sharpe` | 0.40 | The PDF makes this the primary objective |
| `w_hit`    | 0.20 | Robustness over occasional moonshots |
| `w_pnl`    | 0.20 | Raw profitability |
| `w_dd`     | 0.30 | Drawdown is what kills accounts |
| `w_swap`   | 0.05 | Divergence swap = thesis was wrong → penalize |
| `w_panic`  | 0.10 | Panic sell = thesis missed a known risk → bigger penalty |
| `w_cost`   | 0.001 / token | Anti-bloat for over-eager retrieval |

## 5. The composite fitness

```
fitness(c, day, eval_window) =
      mirror_score(c, day)                              # V1 floor (always)
    + λ * outcome_score(c, day, eval_window)            # improvement term
```

`λ = 0.0` in generation 0 (we want offspring that *exactly* match V1).
`λ` increases each generation as offspring prove they don't degrade the
mirror score:

| Gen | λ | Selection rule |
|---|---|---|
| 0 | 0.0 | Pass: ≥ 99 % rank-correlation with V1 picks |
| 1 | 0.1 | Pass: mirror correlation ≥ 95 % AND outcome score positive |
| 2 | 0.3 | Pass: mirror correlation ≥ 90 % AND outcome score > Gen-1 |
| 3 | 0.5 | Pass: outcome score > Gen-2; mirror floor allowed to drift |
| 4+| 1.0 | Pure outcome optimization; mirror used only for sanity bound |

This *ratchets* exploration: every generation gets more freedom, but
only after the prior generation proves it hasn't lost what V1 already
knew.

## 6. Reference implementation

The full implementation lives in
[`v2_engine/evolution/fitness.py`](./v2_engine/evolution/fitness.py).

Key functions:
- `mirror_score(candidate, day) -> float`
- `outcome_score(candidate, day, eval_window) -> float`
- `fitness(candidate, day, eval_window, lam=0.0) -> float`
- `validate_mirrors_v1(trade_log_path) -> RankCorrelation` — used by the
  test and by `paper_trade/compare_report.py` for daily monitoring.

## 7. Things that are NOT fitness terms (deliberately)

- **Win rate alone.** Easy to game by clipping winners early; we use
  Sharpe + drawdown + pnl together.
- **Brevity of thesis.** The PDF wants empathetic user-facing output;
  evolutionary pressure on token count would crush that.
- **Distance from V1's exact tickers.** Mirror is on *ranking
  function*, not exact ticker overlap. V2 must be free to pick tickers
  V1 wasn't shown.
- **Anything from Alpaca's $100k paper balance.** See `MEMORY.md §6`.
