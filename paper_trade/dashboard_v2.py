"""
paper_trade.dashboard_v2 — Garden-themed V2 dashboard, port 5001.

Mirrors every panel from V1's app.py (KPIs, positions, trades, reasoning,
activity, live logs) with V2 colors and fonts, AND adds a clickable
per-trade drilldown: click any position (live or historical) to see the
price chart during the trade window plus the council's choice logic.

Reads:
  - v2_ledger.json                       (live state)
  - v2_trade_log.jsonl                   (past trades)
  - comparison_ledger.jsonl              (V1 vs V2 decision events)
  - memory/decisions/<date>/*.json       (per-day council snapshots, if present)
  - background_pictures/*.jpg            (cycling backgrounds)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from v2_engine import config as cfg
from shared.ledger_schema import Ledger
from shared import comparison_ledger as comp


BG_DIR = Path(cfg.V2_REPO_PATH) / "background_pictures"
DECISIONS_DIR = Path(cfg.V2_REPO_PATH) / "memory" / "decisions"


def create_app():
    try:
        from flask import Flask, jsonify, render_template_string, send_from_directory, abort
    except Exception:
        raise RuntimeError("flask not installed; run pip install flask")

    app = Flask("v2_dashboard")

    # ------ pages ------
    @app.route("/")
    def index():
        return render_template_string(PAGE)

    # ------ static: background images ------
    @app.route("/bg/<path:fn>")
    def bg(fn):
        if not BG_DIR.exists():
            abort(404)
        return send_from_directory(str(BG_DIR), fn)

    @app.route("/bg-list")
    def bg_list():
        if not BG_DIR.exists():
            return jsonify([])
        names = sorted([p.name for p in BG_DIR.iterdir()
                        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")])
        return jsonify(names)

    # ------ live KPIs / positions / bench ------
    @app.route("/api/data")
    def data():
        ledger = Ledger.load(cfg.V2_LEDGER)
        now_et = datetime.now(cfg.ET)
        return jsonify({
            "now_et": now_et.isoformat(),
            "market_status": _market_status(now_et),
            "next_event": _next_event(now_et),
            "kpis": {
                "settled_cash":     round(ledger.settled_cash, 2),
                "unsettled":        round(ledger.unsettled_total, 2),
                "deployed":         round(ledger.pod_cost, 2),
                "total_vault":      round(ledger.total_vault, 2),
                "day_start_vault":  round(ledger.day_start_vault, 2),
                "day_pnl":          round(ledger.total_vault - ledger.day_start_vault, 2),
            },
            "pod": [{
                "ticker": p.ticker, "shares": round(p.shares, 4),
                "entry": p.entry_price, "expected_move_pct": p.expected_move_pct,
                "thesis": p.thesis, "trailing_high": p.trailing_high,
                "entry_ts": p.entry_ts, "conviction": p.conviction,
            } for p in ledger.pod],
            "bench": (ledger.bench or [])[:6],
            "last_deploy_date": ledger.last_deploy_date,
        })

    # ------ recent trades ------
    @app.route("/api/trades")
    def trades():
        path = Path(cfg.V2_TRADE_LOG)
        rows = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-50:]:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return jsonify(rows)

    # ------ today's reasoning (pod thesis + bench) ------
    @app.route("/api/reasoning")
    def reasoning():
        ledger = Ledger.load(cfg.V2_LEDGER)
        return jsonify({
            "pod": [{
                "ticker": p.ticker, "thesis": p.thesis,
                "expected_move_pct": p.expected_move_pct,
                "conviction": p.conviction,
            } for p in ledger.pod],
            "bench": ledger.bench or [],
            "queue": ledger.last_council_queue or [],
        })

    # ------ comparison events feed ------
    @app.route("/api/comparison")
    def comparison():
        events = comp.read_events()[-20:]
        return jsonify([{
            "ts": e.ts, "trading_day": e.trading_day, "event": e.event,
            "v1_bought": e.v1.bought, "v2_bought": e.v2.bought,
            "agreement_top3": e.agreement_top3,
            "mirror_correlation": (round(e.mirror_score_correlation, 3)
                                   if e.mirror_score_correlation == e.mirror_score_correlation
                                   else None),
        } for e in events])

    # ------ activity timeline (synthetic; folds in everything) ------
    @app.route("/api/activity")
    def activity():
        items = []
        ledger = Ledger.load(cfg.V2_LEDGER)
        if ledger.last_deploy_date:
            items.append({"ts": ledger.last_deploy_date + "T09:55", "kind": "DEPLOY",
                          "text": f"Morning deploy: {','.join(p.ticker for p in ledger.pod)}"})
        path = Path(cfg.V2_TRADE_LOG)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-30:]:
                try:
                    r = json.loads(line)
                    items.append({"ts": r.get("ts", ""),
                                  "kind": r.get("action", "TRADE"),
                                  "text": f"{r.get('action','?')} {r.get('ticker','?')} {r.get('shares','?')}@{r.get('price','?')} ({r.get('reason','')[:80]})"})
                except Exception:
                    continue
        items.sort(key=lambda x: x["ts"], reverse=True)
        return jsonify(items[:40])

    # ------ live log tail ------
    @app.route("/api/logs")
    def logs():
        try:
            # Linux + systemd: pull last 120 lines of the V2 service
            out = subprocess.check_output(
                ["sudo", "journalctl", "-u", "angela-trade-fund-v2",
                 "-n", "120", "--no-pager", "-o", "short-iso"],
                stderr=subprocess.STDOUT, timeout=4,
            ).decode("utf-8", errors="replace")
        except Exception as e:
            out = f"(log fetch unavailable: {e})"
        return jsonify({"text": out})

    # ------ THE NEW ONE — per-trade drilldown ------
    @app.route("/api/position/<ticker>/<entry_iso>")
    def position_detail(ticker, entry_iso):
        """Return chart bars + council logic for a specific trade.

        ``entry_iso`` is the ISO timestamp (or YYYY-MM-DD date) the trade entered.
        Works for live positions in v2_ledger AND historical fills in v2_trade_log.
        """
        # 1. Figure out the trade window (entry -> exit) from logs
        window = _trade_window(ticker, entry_iso)

        # 2. Fetch 1-minute bars from Alpaca for that window
        bars = _fetch_minute_bars(ticker, window["start"], window["end"])

        # 3. Council reasoning from per-day snapshot OR live ledger
        logic = _trade_logic(ticker, window["trading_day"])

        # 4. Action markers (buy at entry, sell/swap/stop at exit)
        markers = _trade_markers(ticker, window)

        return jsonify({
            "ticker": ticker,
            "window": window,
            "bars": bars,
            "logic": logic,
            "markers": markers,
        })

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_status(now_et: datetime) -> str:
    """is_open / pre / post / closed (best-effort, weekday-aware, no holiday calendar)."""
    if now_et.weekday() >= 5:
        return "closed"
    open_t  = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et < open_t.replace(hour=9, minute=0):
        return "pre"
    if now_et < open_t:
        return "pre"
    if now_et < close_t:
        return "open"
    return "post"


def _next_event(now_et: datetime) -> dict:
    """Return {"label": "...", "ts_iso": "...", "secs_remaining": N}."""
    today = now_et.date()
    deploy = now_et.replace(hour=cfg.MORNING_DEPLOY_AT[0], minute=cfg.MORNING_DEPLOY_AT[1],
                            second=0, microsecond=0)
    harvest = now_et.replace(hour=cfg.HARVEST_AT[0], minute=cfg.HARVEST_AT[1],
                             second=0, microsecond=0)
    if now_et < deploy:
        target, label = deploy, "Morning deploy"
    elif now_et < harvest:
        target, label = harvest, "Harvest"
    else:
        target, label = deploy + timedelta(days=1), "Tomorrow's deploy"
        while target.weekday() >= 5:
            target += timedelta(days=1)
    return {"label": label, "ts_iso": target.isoformat(),
            "secs_remaining": int((target - now_et).total_seconds())}


def _trade_window(ticker: str, entry_iso: str) -> dict:
    """Find (entry_ts, exit_ts, trading_day) for a given ticker+entry."""
    entry_dt = _parse_iso(entry_iso)
    # exit comes from v2_trade_log.jsonl if there's a sell after entry
    exit_dt = None
    path = Path(cfg.V2_TRADE_LOG)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ticker") != ticker:
                continue
            ts = r.get("ts", "")
            if "SELL" in (r.get("action") or "").upper():
                try:
                    rt = _parse_iso(ts)
                    if rt > entry_dt and (exit_dt is None or rt < exit_dt):
                        exit_dt = rt
                except Exception:
                    pass
    if exit_dt is None:
        # Still live: end at now or today's 15:50
        now_et = datetime.now(cfg.ET)
        eod = now_et.replace(hour=cfg.HARVEST_AT[0], minute=cfg.HARVEST_AT[1],
                             second=0, microsecond=0)
        exit_dt = min(now_et, eod) if now_et.date() == entry_dt.date() else eod
    return {
        "start":  entry_dt.isoformat(),
        "end":    exit_dt.isoformat(),
        "trading_day": entry_dt.date().isoformat(),
    }


def _parse_iso(s: str) -> datetime:
    """Tolerant ISO parser; falls back to date-only midnight ET."""
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=cfg.ET)
        return d.astimezone(cfg.ET)
    except Exception:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=cfg.ET)


def _fetch_minute_bars(ticker: str, start_iso: str, end_iso: str) -> list[dict]:
    """1-minute OHLCV bars from Alpaca; empty list on any error (UI handles it)."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        c = StockHistoricalDataClient(
            os.getenv("V2_ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY"),
            os.getenv("V2_ALPACA_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY"),
        )
        # widen the window 10 min on either side for context
        start = _parse_iso(start_iso) - timedelta(minutes=10)
        end   = _parse_iso(end_iso)   + timedelta(minutes=10)
        req = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Minute,
                               start=start, end=end)
        df = c.get_stock_bars(req).df
        if df is None or df.empty:
            return []
        df = df.reset_index()
        return [{"ts": str(row["timestamp"]),
                 "o": float(row["open"]),  "h": float(row["high"]),
                 "l": float(row["low"]),   "c": float(row["close"]),
                 "v": float(row["volume"])} for _, row in df.iterrows()]
    except Exception as e:
        return [{"error": str(e)}]


def _trade_logic(ticker: str, trading_day: str) -> dict:
    """Return the council's reasoning for this ticker on this day.

    Looks in V2's per-day snapshot first; falls back to live ledger; finally
    to the comparison ledger for any deploy event on that date.
    """
    snap = DECISIONS_DIR / trading_day / "council_queue.json"
    if snap.exists():
        try:
            queue = json.loads(snap.read_text())
            for q in queue:
                if q.get("ticker") == ticker:
                    return {"source": str(snap), "row": q, "queue_size": len(queue)}
        except Exception:
            pass
    ledger = Ledger.load(cfg.V2_LEDGER)
    for q in (ledger.last_council_queue or []):
        if q.get("ticker") == ticker:
            return {"source": "v2_ledger.last_council_queue", "row": q,
                    "queue_size": len(ledger.last_council_queue or [])}
    # Last resort: comparison ledger
    for e in comp.read_events():
        if e.trading_day == trading_day:
            for q in e.v2.queue:
                if q.get("ticker") == ticker:
                    return {"source": "comparison_ledger.jsonl", "row": q,
                            "queue_size": len(e.v2.queue)}
    return {"source": "unknown", "row": None, "queue_size": 0}


def _trade_markers(ticker: str, window: dict) -> list[dict]:
    """Buy / sell markers from v2_trade_log within the window."""
    path = Path(cfg.V2_TRADE_LOG)
    if not path.exists():
        return []
    markers = []
    start = _parse_iso(window["start"])
    end   = _parse_iso(window["end"])
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ticker") != ticker:
            continue
        try:
            rt = _parse_iso(r.get("ts", ""))
        except Exception:
            continue
        if start - timedelta(minutes=1) <= rt <= end + timedelta(minutes=1):
            markers.append({"ts": rt.isoformat(), "action": r.get("action", ""),
                            "price": r.get("price"), "shares": r.get("shares"),
                            "pnl": r.get("pnl"), "reason": r.get("reason", "")})
    return markers


# ---------------------------------------------------------------------------
# HTML  (single template, embedded for portability)
# ---------------------------------------------------------------------------
PAGE = r"""
<!doctype html><html lang=en><head>
<meta charset=utf-8>
<title>V2 — Garden</title>
<link rel=preconnect href=https://fonts.googleapis.com>
<link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@400;600;700&family=Pacifico&family=Comfortaa:wght@500;700&display=swap" rel=stylesheet>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{
    --fuchsia:#ff3aa0; --fuchsia-2:#c41e7a;
    --blue:#1ea7ff;    --blue-2:#0d6cd6;
    --green:#3ddc84;   --green-2:#16a34a;
    --leaf:#0b4f3a;    --soil:#3a1f0b;
    --paper:#fff8fbcc; --ink:#1a1f2c;
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;font-family:'Fredoka',system-ui,sans-serif;color:var(--ink)}
  body{
    background:#0e1116; min-height:100vh;
    background-size:cover; background-position:center;
    transition:background-image 2.5s ease-in-out;
  }
  body::before{
    content:""; position:fixed; inset:0;
    background:linear-gradient(180deg, rgba(255,255,255,.18) 0%, rgba(34,197,94,.18) 60%, rgba(0,0,0,.30) 100%);
    pointer-events:none; z-index:0;
  }
  .wrap{position:relative; z-index:1; padding:24px; max-width:1500px; margin:0 auto}
  header{display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px}
  h1{font-family:'Pacifico',cursive; font-size:42px; margin:0;
     color:white; text-shadow:0 3px 14px rgba(0,0,0,.5), 0 0 18px rgba(255,58,160,.6)}
  .clock{font-family:'Comfortaa'; font-weight:700; color:#fff; font-size:18px;
         padding:8px 14px; border-radius:999px; background:rgba(255,255,255,.18); backdrop-filter:blur(8px)}
  .pill{display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:999px;
        font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em}
  .pill.open{background:var(--green); color:white}
  .pill.pre,.pill.post{background:var(--blue); color:white}
  .pill.closed{background:#888; color:white}
  .grid-k{display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:18px}
  .card{background:var(--paper); border-radius:18px; padding:14px 16px;
        backdrop-filter:blur(14px) saturate(140%);
        box-shadow:0 8px 32px rgba(0,0,0,.18), inset 0 0 0 1px rgba(255,255,255,.5)}
  .card.k{position:relative; overflow:hidden}
  .card.k::after{content:""; position:absolute; right:-30px; top:-30px; width:120px; height:120px;
                 background:radial-gradient(circle,var(--fuchsia) 0,transparent 70%); opacity:.25}
  .k-label{font-family:'Comfortaa'; font-weight:700; font-size:11px; letter-spacing:.08em;
           text-transform:uppercase; color:var(--fuchsia-2); position:relative; z-index:1}
  .k-val{font-family:'Fredoka'; font-weight:700; font-size:26px; margin-top:4px;
         font-variant-numeric:tabular-nums; position:relative; z-index:1}
  .k-val.neg{color:var(--fuchsia-2)}
  .k-val.pos{color:var(--green-2)}
  .countdown{font-family:'Comfortaa'; font-weight:500; color:var(--blue-2); font-size:13px; margin-top:2px}
  .panels{display:grid; grid-template-columns:1.4fr 1fr; gap:14px; margin-bottom:14px}
  .panels-2{display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px}
  h2{font-family:'Pacifico'; font-size:24px; color:var(--leaf); margin:6px 0 10px}
  table{width:100%; border-collapse:collapse; font-size:13px}
  th,td{padding:8px 10px; text-align:left; border-bottom:1px solid #00000018}
  th{font-family:'Comfortaa'; font-weight:700; font-size:11px; text-transform:uppercase;
     letter-spacing:.05em; color:var(--blue-2)}
  tr.click{cursor:pointer; transition:background .15s}
  tr.click:hover{background:linear-gradient(90deg, #ff3aa022, #1ea7ff22)}
  td.tk{font-family:'Comfortaa'; font-weight:700; color:var(--fuchsia-2)}
  td.pl-pos{color:var(--green-2); font-weight:600}
  td.pl-neg{color:var(--fuchsia-2); font-weight:600}
  .bench-chip{display:inline-flex; gap:4px; align-items:center; padding:4px 10px;
              margin:3px; border-radius:999px; background:linear-gradient(90deg,var(--blue),var(--green));
              color:white; font-size:11px; font-weight:700; cursor:pointer}
  .bench-chip small{opacity:.85; font-weight:500}
  .activity{max-height:380px; overflow-y:auto}
  .activity .row{padding:6px 0; border-bottom:1px dashed #00000010; font-size:12px}
  .activity .kind{display:inline-block; min-width:74px; padding:2px 8px; border-radius:6px;
                  font-family:'Comfortaa'; font-weight:700; font-size:10px; text-align:center;
                  margin-right:8px; color:white; background:var(--blue)}
  .kind.BUY{background:var(--green-2)}
  .kind.SELL,.kind.HARVEST-SELL{background:var(--fuchsia-2)}
  .kind.TRAIL-STOP-SELL,.kind.SWAP-SELL{background:#d97706}
  .kind.SWAP-BUY{background:#16a34a}
  .kind.DEPLOY{background:var(--blue-2)}
  pre.logs{background:#0d1117; color:#9be9a8; padding:12px; border-radius:12px;
           font-family:ui-monospace,monospace; font-size:11px; max-height:300px; overflow:auto; margin:0}
  /* modal */
  .modal-bg{position:fixed; inset:0; background:rgba(0,0,0,.55); display:none;
            align-items:center; justify-content:center; z-index:10; padding:20px}
  .modal-bg.show{display:flex}
  .modal{background:var(--paper); border-radius:24px; max-width:1100px; width:100%;
         max-height:90vh; overflow:auto; padding:24px 28px;
         box-shadow:0 20px 60px rgba(0,0,0,.4)}
  .modal h3{font-family:'Pacifico'; font-size:30px; color:var(--leaf); margin:0 0 4px}
  .modal .meta{font-family:'Comfortaa'; font-size:12px; color:var(--blue-2); margin-bottom:14px}
  .modal .close{float:right; background:linear-gradient(90deg,var(--fuchsia),var(--fuchsia-2));
                color:white; border:0; padding:6px 14px; border-radius:999px;
                font-family:'Comfortaa'; font-weight:700; cursor:pointer}
  .modal .logic{background:#ffffffaa; border-radius:12px; padding:12px; font-size:13px; margin-top:14px}
  .modal .logic .thesis{font-family:'Fredoka'; font-size:14px; line-height:1.5; color:var(--ink)}
  .modal .row2{display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:10px}
  .modal .row2 div{background:#ffffff80; border-radius:10px; padding:8px 10px}
  .modal .row2 small{display:block; font-family:'Comfortaa'; font-size:10px; text-transform:uppercase;
                     letter-spacing:.05em; color:var(--blue-2)}
  .modal .row2 b{font-size:18px; font-family:'Fredoka'; color:var(--fuchsia-2)}
  .modal .markers{margin-top:10px; font-size:12px}
  .modal .markers .m{display:inline-block; margin:3px; padding:3px 10px; border-radius:8px;
                     background:var(--blue); color:white; font-family:'Comfortaa'; font-weight:600}
</style>
</head><body>
<div class=wrap>
  <header>
    <div>
      <h1>V2 · Garden</h1>
      <div style="color:#fff; font-family:'Comfortaa'; font-weight:500; text-shadow:0 2px 8px rgba(0,0,0,.5)">
        Multi-Agent RAG · side-by-side with V1
      </div>
    </div>
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; justify-content:flex-end">
      <span class=clock id=clock>—</span>
      <span class=pill id=mkt>—</span>
      <span class=clock id=countdown style="background:rgba(255,58,160,.85); color:white">—</span>
    </div>
  </header>

  <div class=grid-k id=kpis></div>

  <div class=panels>
    <div class=card>
      <h2>Open Positions <small style="font-family:Comfortaa;font-size:11px;color:#888">click any row</small></h2>
      <table id=pod><thead><tr>
        <th>Ticker</th><th>Shares</th><th>Entry</th><th>Current</th>
        <th>P/L $</th><th>P/L %</th><th>EOD target</th>
      </tr></thead><tbody></tbody></table>
      <h2 style="margin-top:16px">Today's Reasoning</h2>
      <div id=theses></div>
      <div id=bench></div>
    </div>
    <div class=card>
      <h2>Activity Timeline</h2>
      <div class=activity id=activity></div>
    </div>
  </div>

  <div class=panels-2>
    <div class=card>
      <h2>Recent Trades</h2>
      <table id=trades><thead><tr>
        <th>Time</th><th>Action</th><th>Ticker</th><th>Shares</th><th>Price</th><th>P/L</th>
      </tr></thead><tbody></tbody></table>
    </div>
    <div class=card>
      <h2>V1 vs V2 Comparison</h2>
      <table id=cmp><thead><tr>
        <th>Day</th><th>V1 picks</th><th>V2 picks</th><th>Top-3 agree</th><th>Mirror corr</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div class=card>
    <h2>Live Bot Output</h2>
    <pre class=logs id=logs>—</pre>
  </div>
</div>

<!-- Trade drilldown modal -->
<div class=modal-bg id=modalBg>
  <div class=modal id=modal>
    <button class=close onclick=closeModal()>Close</button>
    <h3 id=mTicker>—</h3>
    <div class=meta id=mMeta>—</div>
    <canvas id=chart height=200></canvas>
    <div class=markers id=mMarkers></div>
    <div class=logic>
      <div style="font-family:Comfortaa;font-weight:700;font-size:12px;color:var(--blue-2);
                  text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">
        Council choice logic
      </div>
      <div class=thesis id=mThesis>—</div>
      <div class=row2 id=mStats></div>
      <div style="font-family:Comfortaa;font-size:10px;color:#888;margin-top:8px" id=mSource></div>
    </div>
  </div>
</div>

<script>
const $ = sel => document.querySelector(sel);
let chart, lastPrices = {};

// Backgrounds cycle every 14s with a slow crossfade
async function startBackgrounds(){
  const r = await fetch('/bg-list'); const files = await r.json();
  if(!files.length) return;
  let i = 0;
  const setBg = ()=>{ document.body.style.backgroundImage = `url(/bg/${files[i % files.length]})`; i++; };
  setBg(); setInterval(setBg, 14000);
}

function fmtUSD(n){ return '$' + (Math.round(n*100)/100).toFixed(2); }
function fmtPct(n){ return (Math.round(n*100)/100).toFixed(2) + '%'; }

async function refreshAll(){
  const d = await fetch('/api/data').then(r=>r.json());
  const k = d.kpis;
  $('#clock').textContent = new Date(d.now_et).toLocaleTimeString('en-US',{timeZone:'America/New_York'}) + ' ET';
  const mkt = $('#mkt'); mkt.className = 'pill ' + d.market_status; mkt.textContent = d.market_status;
  const cd = d.next_event; const m = Math.floor(cd.secs_remaining/60), s = cd.secs_remaining%60;
  $('#countdown').textContent = `${cd.label}: ${m>=0? m : '—'}m ${s>=0? s : ''}s`;

  $('#kpis').innerHTML = `
    <div class="card k"><div class=k-label>Total Vault</div><div class=k-val>${fmtUSD(k.total_vault)}</div></div>
    <div class="card k"><div class=k-label>Day P&L</div><div class="k-val ${k.day_pnl>=0?'pos':'neg'}">${k.day_pnl>=0?'+':''}${fmtUSD(k.day_pnl)}</div></div>
    <div class="card k"><div class=k-label>Settled Cash</div><div class=k-val>${fmtUSD(k.settled_cash)}</div></div>
    <div class="card k"><div class=k-label>Deployed</div><div class=k-val>${fmtUSD(k.deployed)}</div></div>
    <div class="card k"><div class=k-label>Unsettled (T+1)</div><div class=k-val>${fmtUSD(k.unsettled)}</div></div>
    <div class="card k"><div class=k-label>Day Start Vault</div><div class=k-val>${fmtUSD(k.day_start_vault)}</div></div>`;

  // pod table — clickable rows
  const tbody = $('#pod tbody');
  tbody.innerHTML = (d.pod||[]).map(p=>{
    const cur = lastPrices[p.ticker] || p.entry;
    const pl  = (cur - p.entry) * p.shares;
    const plp = ((cur/p.entry)-1)*100;
    const cls = pl>=0?'pl-pos':'pl-neg';
    return `<tr class=click onclick="openTrade('${p.ticker}','${p.entry_ts}')">
      <td class=tk>${p.ticker}</td><td>${p.shares}</td><td>${fmtUSD(p.entry)}</td>
      <td>${fmtUSD(cur)}</td><td class="${cls}">${pl>=0?'+':''}${fmtUSD(pl)}</td>
      <td class="${cls}">${plp>=0?'+':''}${fmtPct(plp)}</td>
      <td>${fmtPct(p.expected_move_pct||0)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan=7 style="text-align:center;color:#888">no positions</td></tr>';

  // theses + bench
  $('#theses').innerHTML = (d.pod||[]).map(p=>`
    <div style="margin:8px 0;padding:10px;background:#ffffff80;border-radius:10px">
      <b style="color:var(--fuchsia-2)">${p.ticker}</b>
      <small style="color:#888"> · conv ${p.conviction || '?'} · target ${fmtPct(p.expected_move_pct||0)}</small>
      <div style="font-size:13px;margin-top:4px">${p.thesis || '<i style=color:#aaa>(no thesis)</i>'}</div>
    </div>`).join('');
  $('#bench').innerHTML = '<div style="margin-top:8px"><small style="color:var(--blue-2);font-family:Comfortaa;font-weight:700">Bench:</small> ' +
    (d.bench||[]).map(b=>`<span class=bench-chip onclick="alert('Bench: '+JSON.stringify(${JSON.stringify(b)},null,2))">${b.ticker} <small>${fmtPct(b.expected_move_pct||0)}</small></span>`).join('') + '</div>';
}

async function refreshTrades(){
  const rows = await fetch('/api/trades').then(r=>r.json());
  $('#trades tbody').innerHTML = rows.slice(-12).reverse().map(r=>{
    const cls = (r.pnl||0) >= 0 ? 'pl-pos' : 'pl-neg';
    return `<tr class=click onclick="openTrade('${r.ticker}','${r.ts||r.entry_ts||''}')">
      <td>${(r.ts||'').slice(11,16)}</td>
      <td><span class="kind ${r.action||''}">${r.action||''}</span></td>
      <td class=tk>${r.ticker}</td><td>${r.shares||''}</td><td>${r.price?fmtUSD(r.price):''}</td>
      <td class="${cls}">${r.pnl?(r.pnl>=0?'+':'')+fmtUSD(r.pnl):''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan=6 style="text-align:center;color:#888">no trades yet</td></tr>';
}

async function refreshComp(){
  const ev = await fetch('/api/comparison').then(r=>r.json());
  $('#cmp tbody').innerHTML = ev.map(e=>`
    <tr><td>${e.trading_day}</td><td>${(e.v1_bought||[]).join(', ') || '—'}</td>
        <td>${(e.v2_bought||[]).join(', ') || '—'}</td>
        <td>${e.agreement_top3}/3</td>
        <td>${e.mirror_correlation ?? '—'}</td></tr>`).join('') ||
    '<tr><td colspan=5 style="text-align:center;color:#888">awaiting first deploy</td></tr>';
}

async function refreshActivity(){
  const a = await fetch('/api/activity').then(r=>r.json());
  $('#activity').innerHTML = a.map(x=>`
    <div class=row><span class="kind ${(x.kind||'').replace(/[^A-Z\-]/g,'')}">${x.kind}</span>
    <small style="color:#888">${(x.ts||'').slice(0,16).replace('T',' ')}</small><br>
    <span style="font-size:12px">${x.text||''}</span></div>`).join('') ||
    '<div style="color:#888;font-size:12px;padding:8px">no activity yet</div>';
}

async function refreshLogs(){
  const r = await fetch('/api/logs').then(r=>r.json());
  $('#logs').textContent = r.text || '—';
  $('#logs').scrollTop = $('#logs').scrollHeight;
}

// ---- per-trade drilldown ----
async function openTrade(ticker, entryTs){
  $('#modalBg').classList.add('show');
  $('#mTicker').textContent = ticker;
  $('#mMeta').textContent = 'entry ' + (entryTs||'?') + ' · loading…';
  $('#mThesis').textContent = 'loading…';
  $('#mStats').innerHTML = ''; $('#mMarkers').innerHTML = ''; $('#mSource').textContent = '';
  try{
    const d = await fetch(`/api/position/${encodeURIComponent(ticker)}/${encodeURIComponent(entryTs)}`).then(r=>r.json());
    const bars = (d.bars||[]).filter(b=>!b.error);
    $('#mMeta').textContent = `${d.window.start.slice(0,16).replace('T',' ')} → ${d.window.end.slice(0,16).replace('T',' ')} (${bars.length} 1-min bars)`;
    if(chart) chart.destroy();
    const ctx = document.getElementById('chart').getContext('2d');
    chart = new Chart(ctx, {
      type:'line',
      data:{
        labels: bars.map(b=>b.ts.slice(11,16)),
        datasets:[{
          label: ticker + ' price',
          data: bars.map(b=>b.c),
          borderColor:'#ff3aa0', backgroundColor:'rgba(255,58,160,.15)',
          fill:true, tension:.25, pointRadius:0, borderWidth:2,
        }],
      },
      options:{
        responsive:true, plugins:{legend:{display:false}},
        scales:{ y:{ticks:{color:'#1a1f2c'}}, x:{ticks:{color:'#1a1f2c',maxTicksLimit:8}} },
      },
    });
    // markers list
    $('#mMarkers').innerHTML = '<b style="font-family:Comfortaa;font-size:11px;color:var(--blue-2)">EVENTS:</b> ' +
      (d.markers||[]).map(m=>`<span class=m>${(m.action||'').slice(0,12)} @${m.price||'?'}${m.pnl?' · P/L '+(m.pnl>=0?'+':'')+m.pnl.toFixed(2):''}</span>`).join('') || '<i style=color:#888>no markers</i>';
    // logic
    const logic = d.logic || {};
    const row = logic.row || {};
    $('#mThesis').textContent = row.thesis || '(no thesis recorded — V2 hadn\'t deployed yet on this day, or the snapshot wasn\'t written)';
    $('#mStats').innerHTML = `
      <div><small>Conviction</small><b>${row.conviction || '—'}</b></div>
      <div><small>Expected move</small><b>${row.expected_move_pct ? row.expected_move_pct+'%' : '—'}</b></div>
      <div><small>Source</small><b>${row.source || '—'}</b></div>`;
    $('#mSource').textContent = 'logic source: ' + (logic.source || 'unknown') + ' · queue size: ' + (logic.queue_size||0);
  }catch(e){
    $('#mMeta').textContent = 'error: ' + e.message;
  }
}
function closeModal(){ $('#modalBg').classList.remove('show'); }
$('#modalBg').addEventListener('click', e=>{ if(e.target.id==='modalBg') closeModal(); });
window.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });

startBackgrounds();
refreshAll(); refreshTrades(); refreshComp(); refreshActivity(); refreshLogs();
setInterval(refreshAll, 3000);
setInterval(refreshTrades, 8000);
setInterval(refreshComp, 12000);
setInterval(refreshActivity, 10000);
setInterval(refreshLogs, 5000);
</script>
</body></html>
"""


def main() -> None:
    app = create_app()
    port = int(os.getenv("V2_DASHBOARD_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
