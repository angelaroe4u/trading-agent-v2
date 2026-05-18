"""
v2_engine.evolution.fitness
===========================

The single most important module in V2.

Two-stage objective, per `FITNESS_FUNCTION.md`:

  fitness(c, day, eval_window, lam) = mirror_score(c, day)
                                    + lam * outcome_score(c, day, eval_window)

`mirror_score` is the **V1 floor** — reverse-engineered from
`council_v2.py` + `executioner_v2.py` so that ranking candidates by it
reproduces V1's own pick order on historical days.

`outcome_score` is the **improvement term** — forward-looking metrics
(Sharpe, hit rate, PnL, drawdown) measured on a 5-trading-day window
matching V1's HORIZON_DAYS.

`lam` follows the schedule in `config.V2_LAMBDA_SCHEDULE` so each
generation gets more freedom only after the prior one proves it didn't
break the floor.

Public API:

    mirror_score(candidate, day_state)            -> float
    outcome_score(candidate, day_state, returns)  -> float
    fitness(candidate, day_state, returns, lam)   -> float
    validate_mirrors_v1(trade_log_path)           -> RankCorrelation
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from v2_engine import config as cfg

NEG_INF = float("-inf")


# ---------------------------------------------------------------------------
# Data classes — minimal so this module doesn't pull in transformers etc.
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """A single trade idea emitted by the council/quant agent."""
    ticker: str
    conviction: float                           # 0.0–1.0
    expected_move_pct: float                    # net % over HORIZON_DAYS
    source: str = "judge"                       # "judge" | "picker_a" | "picker_b" | "consensus"
    thesis: str = ""
    rank: int = 0                               # rank in the queue, 1-indexed
    intraday_realized_pct: float = 0.0          # how much of expected_move was already realized at 9:55
    is_tradeable: bool = True
    blacklisted: bool = False


@dataclass
class DayState:
    """Conditions on the day the candidate was generated."""
    trading_day: str                            # ISO date
    blacklist: set[str] = field(default_factory=set)
    market_open: bool = True
    pdt_blocked: bool = False                   # from EDA probe
    fractionable_universe: set[str] | None = None


@dataclass
class RealizedReturns:
    """Outcome data, filled in HORIZON_DAYS after the decision."""
    pnl_pct: float = 0.0                        # net % over HORIZON_DAYS
    sharpe_5d: float = 0.0
    hit: bool = False                           # realized >= expected_move_pct
    max_drawdown_pct: float = 0.0               # negative number
    triggered_divergence_swap: bool = False
    triggered_panic_sell: bool = False
    llm_inference_cost_usd: float = 0.0


@dataclass
class RankCorrelation:
    """Result of comparing V2's ranking to V1's actual buys."""
    n_days: int
    spearman: float
    top3_overlap_mean: float                    # 0.0–1.0
    days_with_full_top3_match: int

    def passes_mirror_floor(self, threshold: float = 0.99) -> bool:
        return self.top3_overlap_mean >= threshold


# ---------------------------------------------------------------------------
# Mirror score — bit-for-bit reproduction of V1's implicit ranking
# ---------------------------------------------------------------------------

# Coefficients reverse-engineered from V1 code; see FITNESS_FUNCTION.md §2.
ALPHA_CONVICTION         = 1.00
BETA_EXPECTED_MOVE       = 0.50 / cfg.V1_BASELINE_HORIZON_DAYS   # per-day normalised
EPSILON_JUDGE_SOURCE     = 0.05
DELTA_INTRADAY_REALIZED  = 1.00


def mirror_score(c: Candidate, day: DayState) -> float:
    """Return V1's implicit ranking score for `c`.

    Hard rejections (return ``-inf``) match V1's hard rejects:
      - conviction below the gate (``V1_BASELINE_CONVICTION_GATE``)
      - ticker on today's flush blacklist
      - non-tradeable (failed ``is_tradeable``)
      - intraday already realised >= INTRADAY_SKIP_THRESHOLD of expected
        move ('missed the jump' filter)
    """
    # Hard rejects (in V1, these are early-skips, not score modifiers)
    if c.conviction < cfg.V1_BASELINE_CONVICTION_GATE:
        return NEG_INF
    if not c.is_tradeable or c.blacklisted or c.ticker in day.blacklist:
        return NEG_INF
    # intraday context filter: skip "missed the jump" picks
    if c.expected_move_pct > 0:
        realized_fraction = c.intraday_realized_pct / c.expected_move_pct
        if realized_fraction >= cfg.V1_BASELINE_INTRADAY_SKIP_THRESHOLD:
            return NEG_INF
    else:
        realized_fraction = 0.0

    score = (
        ALPHA_CONVICTION       * c.conviction
        + BETA_EXPECTED_MOVE   * c.expected_move_pct
        + EPSILON_JUDGE_SOURCE * (1.0 if c.source == "judge" else 0.0)
        - DELTA_INTRADAY_REALIZED * realized_fraction
    )
    return score


# ---------------------------------------------------------------------------
# Outcome score — the "improvement" half
# ---------------------------------------------------------------------------

W_SHARPE = 0.40
W_HIT    = 0.20
W_PNL    = 0.20
W_DD     = 0.30      # subtracted
W_SWAP   = 0.05      # subtracted
W_PANIC  = 0.10      # subtracted
W_COST   = 0.001     # subtracted, per dollar


def outcome_score(c: Candidate, day: DayState, r: RealizedReturns) -> float:
    """Forward-looking score; only meaningful after the eval window closes."""
    return (
        W_SHARPE * r.sharpe_5d
        + W_HIT  * (1.0 if r.hit else 0.0)
        + W_PNL  * (r.pnl_pct / 100.0)
        - W_DD   * (abs(r.max_drawdown_pct) / 100.0)
        - W_SWAP * (1.0 if r.triggered_divergence_swap else 0.0)
        - W_PANIC* (1.0 if r.triggered_panic_sell else 0.0)
        - W_COST * r.llm_inference_cost_usd
    )


# ---------------------------------------------------------------------------
# Composite fitness
# ---------------------------------------------------------------------------

def fitness(
    c: Candidate,
    day: DayState,
    returns: RealizedReturns | None = None,
    lam: float | None = None,
    generation: int | None = None,
) -> float:
    """Composite fitness used for Darwinian selection.

    Parameters
    ----------
    c, day
        Candidate + market-day state.
    returns
        Realised 5-day returns. If ``None``, only the mirror floor is scored
        (use this for live ranking, before the eval window closes).
    lam
        Lambda weight on the outcome term. If ``None``, looked up from
        ``cfg.V2_LAMBDA_SCHEDULE[generation]`` (default generation = 0).
    """
    if lam is None:
        gen = 0 if generation is None else int(generation)
        lam = cfg.V2_LAMBDA_SCHEDULE.get(gen, cfg.V2_LAMBDA_SCHEDULE[max(cfg.V2_LAMBDA_SCHEDULE)])

    base = mirror_score(c, day)
    if base == NEG_INF:
        return NEG_INF
    if returns is None or lam == 0.0:
        return base
    return base + lam * outcome_score(c, day, returns)


# ---------------------------------------------------------------------------
# Validation — does this fitness function actually reproduce V1?
# ---------------------------------------------------------------------------

def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation; pure-python, no scipy dep here."""
    if len(a) != len(b) or len(a) < 2:
        return float("nan")

    def _ranks(xs: Sequence[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        ranks = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    da = math.sqrt(sum((x - mean_a) ** 2 for x in ra))
    db = math.sqrt(sum((x - mean_b) ** 2 for x in rb))
    if da == 0 or db == 0:
        return float("nan")
    return num / (da * db)


def _candidate_from_v1_queue_entry(entry: dict, day: DayState) -> Candidate:
    """Build a Candidate from a row of V1's ``last_council_queue``."""
    return Candidate(
        ticker            = entry["ticker"],
        conviction        = float(entry.get("conviction", 0.0)),
        expected_move_pct = float(entry.get("expected_move_pct", 0.0)),
        source            = str(entry.get("source", "judge")),
        thesis            = str(entry.get("thesis", "")),
        rank              = int(entry.get("rank", 0)),
        intraday_realized_pct = float(entry.get("intraday_realized_pct", 0.0)),
        is_tradeable      = bool(entry.get("is_tradeable", True)),
        blacklisted       = entry["ticker"] in day.blacklist,
    )


def validate_mirrors_v1(
    decisions_dir: str | Path,
    trade_log_path: str | Path | None = None,
) -> RankCorrelation:
    """Walk historical V1 decision snapshots and check that ``mirror_score``
    reproduces V1's actual buys.

    Expects either:
      - a ``decisions_dir`` directory laid out like V1's
        ``memory/decisions/<date>/council_queue.json``, OR
      - a ``trade_log_path`` JSONL file we can group by date.

    Returns a :class:`RankCorrelation` with mean top-3 overlap and Spearman
    rank correlation across all valid days.
    """
    p = Path(decisions_dir)
    spear_per_day: list[float] = []
    overlaps: list[float] = []
    full_matches = 0

    if p.exists():
        day_dirs = sorted(d for d in p.iterdir() if d.is_dir())
    else:
        day_dirs = []

    for day_dir in day_dirs:
        queue_path = day_dir / "council_queue.json"
        bought_path = day_dir / "bought.json"
        if not (queue_path.exists() and bought_path.exists()):
            continue
        try:
            queue = json.loads(queue_path.read_text())
            bought = json.loads(bought_path.read_text())
        except Exception:
            continue

        day = DayState(trading_day=day_dir.name)
        cands = [_candidate_from_v1_queue_entry(e, day) for e in queue]
        scores = [mirror_score(c, day) for c in cands]

        # Spearman: rank candidates by V1's `rank` field vs by our score
        v1_ranks = [c.rank for c in cands]
        # invert score so "lower is better" matches rank semantics
        our_ranks_basis = [-s if s != NEG_INF else float("inf") for s in scores]
        spear = _spearman(v1_ranks, our_ranks_basis)
        if not math.isnan(spear):
            spear_per_day.append(spear)

        # Top-3 overlap
        order = sorted(range(len(cands)), key=lambda i: -scores[i])
        our_top3 = {cands[i].ticker for i in order[:3]}
        bought_set = set(bought.get("tickers", []))[:3] if isinstance(bought, dict) else set(bought[:3])
        if our_top3 == bought_set:
            full_matches += 1
        if bought_set:
            overlaps.append(len(our_top3 & bought_set) / max(len(bought_set), 1))

    return RankCorrelation(
        n_days = len(day_dirs),
        spearman = (statistics.mean(spear_per_day) if spear_per_day else float("nan")),
        top3_overlap_mean = (statistics.mean(overlaps) if overlaps else float("nan")),
        days_with_full_top3_match = full_matches,
    )


# ---------------------------------------------------------------------------
# Convenience: rank a queue by fitness (used by V2's orchestrator)
# ---------------------------------------------------------------------------

def rank_queue(
    candidates: Iterable[Candidate],
    day: DayState,
    returns_by_ticker: dict[str, RealizedReturns] | None = None,
    lam: float | None = None,
    generation: int | None = None,
) -> list[tuple[Candidate, float]]:
    """Return ``(candidate, fitness)`` sorted highest fitness first.

    Hard rejects (``-inf``) are dropped from the result, matching V1's
    behaviour where the conviction gate and blacklist remove candidates
    entirely rather than just demoting them.
    """
    out: list[tuple[Candidate, float]] = []
    for c in candidates:
        r = (returns_by_ticker or {}).get(c.ticker)
        f = fitness(c, day, returns=r, lam=lam, generation=generation)
        if f == NEG_INF:
            continue
        out.append((c, f))
    out.sort(key=lambda t: t[1], reverse=True)
    return out
