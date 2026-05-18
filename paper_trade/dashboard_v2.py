"""
paper_trade.dashboard_v2 — minimal Flask dashboard for V2, on port 5001.

Side-by-side companion to V1's app.py (port 5000). Reads:
  - v2_ledger.json
  - v2_trade_log.jsonl
  - comparison_ledger.jsonl

Does NOT modify any V1 file. Plain JSON endpoints + a single HTML page.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from v2_engine import config as cfg
from shared.ledger_schema import Ledger
from shared import comparison_ledger as comp


def create_app():
    try:
        from flask import Flask, jsonify, render_template_string
    except Exception:
        raise RuntimeError("flask not installed; pip install flask in /opt/tradingap/venv")

    app = Flask("v2_dashboard")

    @app.route("/")
    def index():
        return render_template_string(PAGE)

    @app.route("/api/v2_state")
    def v2_state():
        ledger = Ledger.load(cfg.V2_LEDGER)
        return jsonify({
            "settled_cash":   round(ledger.settled_cash, 2),
            "unsettled":      round(ledger.unsettled_total, 2),
            "pod_cost":       round(ledger.pod_cost, 2),
            "total_vault":    round(ledger.total_vault, 2),
            "day_start_vault": round(ledger.day_start_vault, 2),
            "last_deploy_date": ledger.last_deploy_date,
            "pod": [{
                "ticker": p.ticker, "shares": p.shares,
                "entry": p.entry_price, "expected_move_pct": p.expected_move_pct,
                "thesis": p.thesis[:200], "trailing_high": p.trailing_high,
            } for p in ledger.pod],
            "bench": ledger.bench[:6],
        })

    @app.route("/api/comparison")
    def comparison():
        events = comp.read_events()[-20:]
        return jsonify([{
            "ts": e.ts, "trading_day": e.trading_day, "event": e.event,
            "v1_bought": e.v1.bought, "v2_bought": e.v2.bought,
            "agreement_top3": e.agreement_top3,
            "mirror_correlation": round(e.mirror_score_correlation, 3) if e.mirror_score_correlation == e.mirror_score_correlation else None,
        } for e in events])

    return app


PAGE = """\
<!doctype html>
<html><head><title>V2 Dashboard</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0e1116;color:#d4d4d4;margin:0;padding:24px;}
  h1{margin:0 0 16px;font-weight:500;}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;}
  .label{color:#8b949e;font-size:12px;text-transform:uppercase;letter-spacing:.05em;}
  .val{font-size:22px;margin-top:4px;font-variant-numeric:tabular-nums;}
  table{width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;overflow:hidden;}
  th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #30363d;font-size:13px;}
  th{background:#1c2128;color:#8b949e;font-weight:500;}
</style></head><body>
<h1>V2 — Multi-Agent RAG, side-by-side with V1</h1>
<div id="kpis" class="grid"></div>
<h2 style="font-weight:500">Pod</h2>
<table id="pod"><thead><tr>
  <th>Ticker</th><th>Shares</th><th>Entry</th><th>Exp move %</th><th>Thesis</th>
</tr></thead><tbody></tbody></table>
<h2 style="font-weight:500;margin-top:32px">Last 20 comparison events</h2>
<table id="cmp"><thead><tr>
  <th>Day</th><th>V1 bought</th><th>V2 bought</th><th>Top-3 agree</th><th>Mirror corr</th>
</tr></thead><tbody></tbody></table>
<script>
async function refresh(){
  const s = await fetch('/api/v2_state').then(r=>r.json());
  const k = document.getElementById('kpis');
  k.innerHTML = `
    <div class=card><div class=label>Settled cash</div><div class=val>$${s.settled_cash}</div></div>
    <div class=card><div class=label>Unsettled (T+1)</div><div class=val>$${s.unsettled}</div></div>
    <div class=card><div class=label>Pod cost</div><div class=val>$${s.pod_cost}</div></div>
    <div class=card><div class=label>Total vault</div><div class=val>$${s.total_vault}</div></div>`;
  const pt = document.querySelector('#pod tbody');
  pt.innerHTML = s.pod.map(p=>`<tr><td>${p.ticker}</td><td>${p.shares}</td><td>$${p.entry}</td><td>${p.expected_move_pct}%</td><td>${p.thesis}</td></tr>`).join('') || '<tr><td colspan=5>empty</td></tr>';

  const c = await fetch('/api/comparison').then(r=>r.json());
  document.querySelector('#cmp tbody').innerHTML = c.map(e=>`
    <tr><td>${e.trading_day}</td><td>${(e.v1_bought||[]).join(', ')}</td>
        <td>${(e.v2_bought||[]).join(', ')}</td>
        <td>${e.agreement_top3}/3</td>
        <td>${e.mirror_correlation ?? '—'}</td></tr>`).join('') || '<tr><td colspan=5>no events yet</td></tr>';
}
refresh(); setInterval(refresh, 5000);
</script></body></html>
"""


def main() -> None:
    app = create_app()
    port = int(os.getenv("V2_DASHBOARD_PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
