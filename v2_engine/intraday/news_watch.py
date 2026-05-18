"""
v2_engine.intraday.news_watch — light news watch (Grok-3-mini every ~12 min).

Same behavior as V1's light_news_watch: fetch fresh news for held tickers,
ask Grok-3-mini "is this a code-blue event?", PANIC-SELL only the affected
ticker if yes. Defaults to no-op on any error (conservative).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Callable

from v2_engine import config as cfg
from shared.ledger_schema import Ledger, UnsettledProceed


def _grok_classify(ticker: str, headlines: list[str]) -> dict:
    """Return {"code_blue": bool, "reason": str}."""
    if not headlines:
        return {"code_blue": False, "reason": "no headlines"}
    try:
        from openai import OpenAI
    except Exception:
        return {"code_blue": False, "reason": "openai SDK unavailable"}

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return {"code_blue": False, "reason": "XAI_API_KEY not set"}

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        prompt = (
            f"You are a fast news-triage classifier for an algo-trading bot.\n"
            f"Ticker: {ticker}\n"
            f"Latest headlines:\n"
            + "\n".join(f"- {h}" for h in headlines[:10]) +
            "\n\n"
            "Is any of these a 'code-blue' event (regulatory action, fraud, "
            "sector contagion, halt, bankruptcy filing) that would justify "
            "an immediate panic-sell?\n"
            'Reply STRICT JSON: {"code_blue": true|false, "reason": "..."}'
        )
        r = client.chat.completions.create(
            model=os.getenv("GROK_LIGHT_MODEL", "grok-3-mini"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        return {"code_blue": False, "reason": f"grok call failed: {type(e).__name__}"}


def light_news_watch(ledger: Ledger, save: Callable[[], None],
                     fetch_headlines: Callable[[str], list[str]] | None = None) -> None:
    """Run if it's been >= LIGHT_NEWS_INTERVAL_MIN since last watch."""
    if not ledger.pod:
        return
    now = datetime.now(cfg.ET)
    last = ledger.last_light_watch
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).total_seconds() / 60 < cfg.V1_BASELINE_LIGHT_NEWS_INTERVAL_MIN:
                return
        except Exception:
            pass

    ledger.last_light_watch = now.isoformat()

    from shared.alpaca_paper import alp_sell

    for p in list(ledger.pod):
        headlines = fetch_headlines(p.ticker) if fetch_headlines else []
        verdict = _grok_classify(p.ticker, headlines)
        if not verdict.get("code_blue"):
            continue
        # PANIC-SELL just this ticker
        shares, px = alp_sell(p.ticker, p.shares)
        if shares <= 0 or px <= 0:
            continue
        settle_day = (now.date() + timedelta(days=1)).isoformat()
        ledger.unsettled.append(UnsettledProceed(amount=shares * px, settle_date=settle_day))
        ledger.blacklist_add(p.ticker)
        try:
            ledger.pod.remove(p)
        except ValueError:
            pass
        ledger.code_blue_paged = True
    save()
