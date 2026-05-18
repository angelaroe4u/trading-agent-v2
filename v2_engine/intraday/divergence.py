"""v2_engine.intraday.divergence — port of V1's divergence_check + Opus swap."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Callable

from v2_engine import config as cfg
from shared.ledger_schema import Ledger, Position, UnsettledProceed


def expected_progress_at(now_dt: datetime) -> float:
    """Linear interp 0.0-1.0 across DIVERGENCE_CURVE checkpoints."""
    minutes_now = now_dt.hour * 60 + now_dt.minute
    curve = [(h * 60 + m, frac) for h, m, frac in cfg.V1_BASELINE_DIVERGENCE_CURVE]
    if minutes_now <= curve[0][0]:
        return curve[0][1] if minutes_now == curve[0][0] else 0.0
    if minutes_now >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        m0, f0 = curve[i]
        m1, f1 = curve[i + 1]
        if m0 <= minutes_now <= m1:
            return f0 + (f1 - f0) * (minutes_now - m0) / (m1 - m0)
    return 0.0


def _opus_swap_decision(ledger, position, actual_pct, expected_pct, trigger_reason):
    """Ask Opus 4.6: swap or hold? Defaults to hold on any error."""
    try:
        import anthropic
    except Exception:
        return {"action": "hold", "rationale": "anthropic SDK unavailable"}
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"action": "hold", "rationale": "no ANTHROPIC_API_KEY"}
    held = {p.ticker for p in ledger.pod}
    bench_summary = []
    for b in (ledger.bench or [])[:6]:
        t = b.get("ticker")
        if t in held or ledger.is_blacklisted(t):
            continue
        bench_summary.append({
            "ticker": t,
            "expected_move_pct": b.get("expected_move_pct"),
            "conviction": b.get("conviction"),
            "thesis": (b.get("thesis") or "")[:280],
        })
    original = next((q for q in (ledger.last_council_queue or [])
                     if q.get("ticker") == position.ticker), None)
    original_thesis = (original or {}).get("thesis", "") or "(unknown)"
    now_dt = datetime.now(cfg.ET)
    prompt = (
        f"POSITION DIVERGENCE CHECK — {now_dt:%H:%M ET}\n\n"
        f"Ticker: {position.ticker}\n"
        f"Original thesis: {original_thesis[:400]}\n"
        f"EOD target: {position.expected_move_pct:+.2f}%\n"
        f"Expected progress: {expected_pct:+.2f}%\n"
        f"Actual progress: {actual_pct:+.2f}%\n"
        f"Trigger: {trigger_reason}\n\n"
        f"BENCH:\n{json.dumps(bench_summary, indent=2)}\n\n"
        "Decide: swap or hold?\n"
        'Reply STRICT JSON: {"action":"swap"|"hold","rationale":"...","new_ticker":"XYZ or null"}'
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        r = client.messages.create(model=cfg.V2_JUDGE_MODEL, max_tokens=400,
                                   messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        return {"action": "hold", "rationale": f"Opus error: {type(e).__name__}"}


def _execute_swap(ledger, position, opus_rationale, save):
    """Sell divergent; buy next bench pick. Mirrors V1."""
    from shared.alpaca_paper import alp_sell, alp_buy, is_tradeable, adr_14d
    settle_day = (datetime.now(cfg.ET).date() + timedelta(days=1)).isoformat()
    shares, px = alp_sell(position.ticker, position.shares)
    if shares <= 0 or px <= 0:
        return
    proceeds = shares * px
    ledger.unsettled.append(UnsettledProceed(amount=proceeds, settle_date=settle_day))
    ledger.blacklist_add(position.ticker)
    try:
        ledger.pod.remove(position)
    except ValueError:
        pass
    save()
    if ledger.settled_cash < 10:
        return
    held = {p.ticker for p in ledger.pod}
    next_pick = next((b for b in (ledger.bench or [])
                      if b.get("ticker") not in held
                      and not ledger.is_blacklisted(b.get("ticker", ""))), None)
    if not next_pick:
        return
    ledger.bench.remove(next_pick)
    tkr = next_pick["ticker"]
    if not is_tradeable(tkr):
        save()
        return
    rebuy = ledger.settled_cash * 0.50
    shares, px = alp_buy(tkr, rebuy)
    if shares <= 0 or px <= 0:
        save()
        return
    ledger.settled_cash -= shares * px
    ledger.pod.append(Position(
        ticker=tkr, shares=shares, entry_price=px,
        entry_ts=datetime.now(cfg.ET).isoformat(),
        conviction=float(next_pick.get("conviction", 0.5) or 0.5),
        adr_14d=adr_14d(tkr),
        expected_move_pct=float(next_pick.get("expected_move_pct") or 0.0),
        thesis=str(next_pick.get("thesis", "")),
        trailing_high=px, peak_price=px,
    ))
    save()


def divergence_check(ledger, save):
    """Main hook. Runs every DIVERGENCE_CHECK_INTERVAL_MIN minutes."""
    if not ledger.pod:
        return
    from shared.alpaca_paper import latest_price
    now_dt = datetime.now(cfg.ET)
    expected_frac = expected_progress_at(now_dt)
    if expected_frac <= 0:
        return
    for p in list(ledger.pod):
        try:
            if isinstance(p.entry_ts, str):
                entry_dt = datetime.fromisoformat(p.entry_ts)
            else:
                entry_dt = datetime.fromtimestamp(float(p.entry_ts), tz=cfg.ET)
        except Exception:
            continue
        if (now_dt - entry_dt).total_seconds() / 60 < cfg.V1_BASELINE_DIVERGENCE_GRACE_MIN:
            continue
        if p.last_divergence_check:
            try:
                last_dt = datetime.fromisoformat(p.last_divergence_check)
                if (now_dt - last_dt).total_seconds() / 60 < cfg.V1_BASELINE_DIVERGENCE_COOLDOWN_MIN:
                    continue
            except Exception:
                pass
        if p.divergence_swap_attempted:
            continue
        target = float(p.expected_move_pct or 0)
        if target <= 0:
            continue
        px = latest_price(p.ticker)
        if px is None:
            continue
        actual_pct   = (px / p.entry_price - 1) * 100
        expected_pct = target * expected_frac
        lag_pp       = expected_pct - actual_pct
        triggered = False
        reason = None
        if lag_pp > cfg.V1_BASELINE_DIVERGENCE_LAG_PP:
            triggered, reason = True, f"lags curve by {lag_pp:+.2f}pp"
        elif actual_pct < cfg.V1_BASELINE_DIVERGENCE_DRAWDOWN_PCT:
            triggered, reason = True, f"drawdown {actual_pct:+.2f}%"
        if not triggered:
            continue
        p.last_divergence_check = now_dt.isoformat()
        decision = _opus_swap_decision(ledger, p, actual_pct, expected_pct, reason)
        if decision.get("action") == "swap":
            p.divergence_swap_attempted = True
            _execute_swap(ledger, p, decision.get("rationale", ""), save)
        save()
