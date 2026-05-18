# Trading Agent 2.0 — Project Memory

> **For any AI / future Claude session:** Read this first. This is the master log
> of everything substantive done in the V2 build, plus the goals that drive it.
> Last updated: **2026-05-17**

---

## 0. North Star

We are building **Trading Agent 2.0** as a *successor and competitor* to the
existing V1 trading bot in `C:\Projects\tradingap` (server path: `/opt/tradingap`,
Hetzner box `5.161.197.162`).

Three deliverables, in priority order:

1. **Database / architecture upgrade** — implement the *Dynamic Multi-Agent RAG*
   design from `uploads/ai.pdf` (Recursive Meta-Agents, Agent Distillation,
   LoRA swap, Pi-Serini lexical retrieval, DARE gating, Enterprise Discovery
   Agents, Darwinian model merging).
2. **Side-by-side paper trading** — V1 and V2 must trade the *same calendar
   day* on Alpaca paper, against the same market data, with independent ledgers.
   Comparison is by P&L, win rate, and decision-accuracy on a per-pick basis.
3. **Fitness function** — the function that selects "winners" in the Darwinian
   evolution must **first reproduce V1's current decision-making**, then
   improve from there. Concretely: V2's fitness ranking of V1's own trades
   must match V1's ranking of those same trades. Anything beyond that is upside.

---

## 1. V1 Snapshot (what we are mirroring)

Read once and locked into our fitness baseline.

**Engine:** monolithic `executioner_v2.py` (~1750 lines) +
`council_v2.py` (~480 lines).

**Council (4 LLMs):**
- Picker A — Llama 3.3 70B on Groq
- Picker B — Gemini 2.5 Flash (with Google Search grounding)
- Judge — Claude Opus 4.6
- News watch — Grok-3-mini (every ~12 min)
- Utility — Claude Haiku 4.5

**Decision pipeline:**
1. `semantic_memory.decision_universe(today)` → ~2000 tickers
2. `momentum_prefilter` → top 80
3. `build_dossier(ticker, today)` for each
4. Llama picks 3 (top 30 dossiers), Gemini picks 3 (all 80 + live search) — parallel
5. Opus judge → ranked queue of 12 with `expected_move_pct` + `conviction`
6. `intraday_context_filter` — skip picks that already realized ≥60% of expected move
7. Top 3 bought at 9:55 ET with **conviction weights [0.50, 0.30, 0.20]**

**Risk controls:**
- Divergence curve: 33 % by 11:30, 60 % by 13:00, 85 % by 14:30
- Swap trigger: `lag > 3 pp` OR `drawdown < -2 %`
- Grace: 30 min after entry; Cooldown: 60 min/position; max 1 swap/day/position
- Trailing stop: flat -2 % from peak
- Light news watch every 12 min → PANIC-SELL on regulatory/sector events
- Harvest 15:50 ET — no overnight holds
- Conviction gate: `conviction >= 0.70`

**Persistence:**
- `executioner_ledger.json` — settled cash, unsettled (T+1), pod, bench, day_start_vault
- `trade_log.jsonl` — append-only
- `semantic_memory.db` — 21 GB SQLite, 2 yrs × ~2000 tickers
- `memory/decisions/<date>/*.json` — council deliberations

**Infra:** Hetzner CCX13 (Ashburn VA), systemd `angela-trade-fund.service`,
Flask dashboard `app.py` on :5000, email reporter at 16:35 ET.

V1 ledger schema, fix log, and known gotchas: see
`C:\Projects\tradingap\AGENT_MEMORY.md` and `BOT_ARCHITECTURE.md`.

---

## 2. V2 Architecture (target — translating the PDF)

| PDF concept | V2 module | Status |
|---|---|---|
| Recursive Meta-Agent (Generator) | `v2_engine/agents/generator.py` | scaffolded |
| Agent Distillation (70B → student) | `v2_engine/distillation/cot_distill.py` | scaffolded |
| LoRA swap (single base + adapters) | `v2_engine/lora/adapter_swap.py` | scaffolded |
| Pi-Serini lexical retrieval (BM25 + LLM loop) | `v2_engine/retrieval/pi_serini.py` | scaffolded |
| DARE-Agent multi-objective gating | `v2_engine/retrieval/dare_gate.py` | scaffolded |
| Iterative self-correction router | `v2_engine/retrieval/self_correction.py` | scaffolded |
| Darwinian merging (SLERP + structural) | `v2_engine/evolution/{merge_slerp,merge_structural}.py` | scaffolded |
| Trading-specific fitness function | `v2_engine/evolution/fitness.py` | **implemented (V1-mirror floor)** |
| Enterprise Discovery Agent (broker probe) | `v2_engine/agents/eda.py` | scaffolded |

DB upgrade: hybrid storage layer over the existing 21 GB SQLite:
- **Dense vector** index (FAISS) over dossiers, news, monthly summaries
- **Sparse lexical** index (BM25 / Pyserini) over the same text
- **Router** picks dense / sparse / hybrid per query, gated by DARE
- **No data loss** — `semantic_memory.db` is *the source of truth*; FAISS + BM25
  are derived caches rebuildable from it.

---

## 3. Side-by-side paper trading

- V1 stays on its current Alpaca paper key (server `/opt/tradingap`).
- V2 uses a **second Alpaca paper key** (config in `Trading Agent 2.0/.env`).
- Both run on the same trading-day clock; both call the same market-data feed.
- Every V1 decision is mirrored to V2's evaluator at the same minute so we can
  score V2's choice against V1's choice on identical conditions, even when
  Alpaca's two paper books drift apart due to fill latency.
- Comparison ledger: `paper_trade/comparison_ledger.jsonl` — one row per
  *decision event* with both engines' verdicts.

See `COMPARISON_PROTOCOL.md` for the daily routine.

---

## 4. Progress log (newest first)

### 2026-05-17

- Located V1: `C:\Projects\tradingap` (mirror of server `/opt/tradingap`).
- Read `BOT_ARCHITECTURE.md` (593 lines) + `AGENT_MEMORY.md` (266 lines) +
  surveyed `executioner_v2.py` (constants + function signatures).
- Locked V1 decision constants into `v2_engine/config.py` as `V1_BASELINE_*`.
- Wrote this `MEMORY.md`, the V2 architecture blueprint, the comparison
  protocol, and the fitness-function spec.
- Scaffolded the full `v2_engine/`, `shared/`, `paper_trade/`,
  `memory_v2/`, and `tests/` tree.
- Implemented the fitness function with a V1-mirror floor (see
  `v2_engine/evolution/fitness.py` and `FITNESS_FUNCTION.md`).
- Wrote a smoke test that asserts fitness on V1's own trades reproduces
  V1's ranking (`tests/test_fitness_mirrors_v1.py`).

**Verification (run in session):**
- `pytest tests/test_fitness_mirrors_v1.py tests/test_dare_gate.py
  tests/test_evolution.py` → **15 passed, 1 skipped** (the skip is the
  full historical replay, which needs `C:\Projects\tradingap\memory\decisions\`
  to be populated with V1 deploy snapshots — V1 needs at least one
  live trading day with the new snapshot writer enabled).
- Comparison-ledger JSONL roundtrip smoke test → **passed**
  (`v1↔v2 agreement_top3=1/3, mirror_correlation=1.0`).
- All 24 V2 modules import cleanly without pulling in torch / peft /
  faiss (lazy-loaded), so the scaffold runs on a stock Python 3.10+
  with only `pytest python-dotenv tiktoken` installed.

### Next session checklist

- [ ] Generate a second Alpaca paper API key and drop into
      `Trading Agent 2.0/.env` as `V2_ALPACA_API_KEY` / `V2_ALPACA_SECRET_KEY`.
- [ ] Run `tests/test_fitness_mirrors_v1.py` against a real slice of
      `trade_log.jsonl` (need at least 10 trading days of V1 history).
- [ ] Build the FAISS index from `semantic_memory.db` —
      `memory_v2/build_indexes.py` (not yet written).
- [ ] Wire `paper_trade/side_by_side_runner.py` to call both engines and
      log to `comparison_ledger.jsonl`.
- [ ] Pick a small open-source quant base model for the first
      Darwinian generation (suggestions in `ARCHITECTURE_V2.md`).

---

## 5. Repo layout (within `Trading Agent 2.0/`)

```
Trading Agent 2.0/
├── MEMORY.md                          ← you are here
├── README.md
├── ARCHITECTURE_V2.md                 ← PDF → blueprint
├── FITNESS_FUNCTION.md                ← V1-mirror spec + evolution roadmap
├── COMPARISON_PROTOCOL.md             ← side-by-side rules
├── pyproject.toml
├── .env.example
│
├── shared/                            ← used by both V1-evaluator and V2
│   ├── ledger_schema.py
│   ├── comparison_ledger.py
│   └── alpaca_paper.py
│
├── v2_engine/
│   ├── config.py                      ← mirrors V1 constants verbatim
│   ├── orchestrator.py                ← replaces V1's run_day()
│   ├── agents/{generator,planner,extractor,qa,quant,synthesizer,persona,eda}.py
│   ├── retrieval/{pi_serini,dare_gate,self_correction,vector_store,lexical_index}.py
│   ├── evolution/{population,merge_slerp,merge_structural,mutate,tournament,lineage,fitness}.py
│   ├── lora/adapter_swap.py
│   └── distillation/cot_distill.py
│
├── paper_trade/
│   ├── side_by_side_runner.py
│   ├── shadow_alpaca.py
│   └── compare_report.py
│
├── memory_v2/
│   ├── schema.py
│   ├── migration_from_v1.py
│   └── README.md
│
└── tests/
    ├── test_fitness_mirrors_v1.py     ← critical
    ├── test_dare_gate.py
    ├── test_evolution.py
    └── test_side_by_side_smoke.py
```

---

## 6. Hard rules carried over from V1

(Never re-introduce these bugs — see `AGENT_MEMORY.md` Fix Log.)

- **Never sync to Alpaca's $100 k paper balance.** V2 tracks its own ledger,
  exactly like V1 does. Reading `account.cash` for budget = bug.
- **Floor-round share quantities on sell.** `math.floor(qty * 1e6) / 1e6`.
- **`safe_buy` must NOT deduct cash on a 0-fill.** Return early.
- **Restart guard:** `last_deploy_date == today_str` → abort morning deploy.
- **Night guard** in the orchestrator's main loop — without it the watchdog
  spins all night.
- **Cash-account T+1** — sells settle next trading day; mid-day swaps don't
  free same-day buying power.

---

## 7. Open questions for Angela

These need her input before V2 goes live with real capital:

- A second Alpaca paper API key (she'll generate from the Alpaca console).
- Where V2 runs — same Hetzner box, a sibling box, or her laptop for now?
- Whether V2's first Darwinian generation should start from a *clone of the
  V1 council ensemble* (safe) or from a fresh quant-finetune model (risky
  but more variance).
- Conviction-weighted sizing [0.50, 0.30, 0.20] — keep verbatim, or let
  V2 mutate it as a hyperparameter? (Default: keep for the mirror baseline,
  open it up to evolution after a generation passes the fitness floor.)

### 2026-05-17 (second session — actual implementation pass)

What I previously called "scaffold + verified" was *also* a real-code mix —
this session filled in the gaps the user called out:

- **Single-account dual-ledger.** Both engines share the existing Alpaca
  paper account. Every V2 order is tagged `client_order_id = v2_<unix>_<ticker>_<6hex>`.
  V2's `list_v2_orders()` filters by prefix; V1's reconcile only sees its
  own orders. Two `$2k` slices of the $100k paper balance.
- **Intraday risk loop is no longer a stub.** Ported divergence_check,
  trailing_stop_check, light_news_watch, intraday_context_filter into
  `v2_engine/intraday/*.py`. Constants pulled from `config.py`'s
  `V1_BASELINE_*` so the rule is binary-identical to V1.
- **Real V2 council.** Quant agent now actually invokes `council_v2.run_council`
  for Gen 0. Synthesizer applies hard EDA constraints. Persona writes
  user-facing copy via Haiku 4.5.
- **Migration script is resumable.** `--limit` for smoke runs, persistent
  `_progress.json` so the full 21 GB ingest can be killed and restarted.
- **Hetzner deploy artifacts.** Two systemd unit files
  (`angela-trade-fund-v2.service`, `angela-ui-v2.service`), an idempotent
  `install_v2_on_hetzner.sh`, a one-shot `install_v2_on_hetzner.bat`,
  a minimal Flask dashboard on port 5001, and `DEPLOY.md`.
- **Tests now exercise the new behavior.** 27 passed, 1 skipped (historical
  replay — needs V1's `memory/decisions/<date>/*.json` populated).
- **Bytecode issue.** Windows-mounted `__pycache__` is read-only from this
  sandbox; surfaced via stale .pyc shadowing fresh .py edits. Workaround
  for testing here: copy to `/tmp/v2` and run pytest there. On Hetzner
  this is a non-issue — local filesystem.

**Next-session priorities**

- [ ] Populate `C:\Projects\tradingap\memory\decisions\<date>\council_queue.json`
      + `bought.json` on V1's next deploy so the full historical-replay test
      (`tests/test_fitness_mirrors_v1.py::test_historical_replay_mirror_floor`)
      flips from skipped to passing.
- [ ] Run `python -m memory_v2.migration_from_v1 --limit 1000` once on Hetzner
      to validate the FAISS+BM25 pipeline against the real DB before the
      full overnight run.
- [ ] Wire `paper_trade/side_by_side_runner.py` into V1's morning_deploy so
      V1's queue is written to `comparison_ledger.jsonl` at the same moment
      V2's is. (Currently V2 writes its half; V1's half stays empty until the
      next runner pass.)
- [ ] Add a V1↔V2 appendix to `email_reporter.py`.
