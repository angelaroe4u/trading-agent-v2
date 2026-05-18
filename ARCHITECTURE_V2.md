# V2 Architecture — Dynamic Multi-Agent RAG for Algorithmic Trading

> Translation of `uploads/ai.pdf` ("Architecture Update Proposal: Dynamic
> Multi-Agent RAG System for Algorithmic Trading", May 17 2026) into the
> concrete modules of this repo.

## 1. Where V1 falls short

V1 is a **monolithic 4-LLM council** that runs the same prompt path every day:
all candidates → all analysts → judge → buy top 3. Three issues:

- **Latency** — Llama+Gemini+Opus serial pipeline takes ~90 s; that's most of
  V1's "9:50 → 9:55" window. Adds noise to entry pricing.
- **No adaptation** — the prompt structure never changes. When the market
  regime shifts, V1's universe of dossiers shifts but the *judgment policy*
  is frozen. (This is the "non-stationarity" problem the PDF calls out.)
- **No introspection** — V1 can't tell the difference between "Opus had the
  right thesis but the divergence trigger fired too early" and "Opus's
  thesis was wrong". Every loss looks the same.

## 2. V2 in one paragraph

A small **base LLM** (single ~7-13 B model held in VRAM) wears different
LoRA adapters to play different roles. A **Generator agent** spawns the
exact sub-graph of agents the day's market state requires — sometimes just
{Extractor, Quant, Synthesizer}, sometimes the full stack. Retrieval is
hybrid (dense + BM25 / Pi-Serini) with a **DARE** gate that balances
accuracy / citation precision / token cost. An **Enterprise Discovery
Agent** probes the live Alpaca API before every trade to inject *current*
constraints. Each generation, an evolutionary loop **merges and mutates**
quant adapters; survivors are picked by the fitness function in
`FITNESS_FUNCTION.md`.

## 3. Module map

```
                       ┌──────────────────────┐
            user/      │     orchestrator     │     market trigger
            cron ────▶ │   (replaces V1's     │ ◀──── (price gap,
                       │     run_day)         │       VIX spike, news)
                       └──────────┬───────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  generator.py   │  recursive meta-agent
                         │  decides which  │  spawns only what's needed
                         │  sub-graph to   │
                         │  spawn          │
                         └────────┬────────┘
                                  │
        ┌──────────────┬──────────┼──────────┬─────────────┐
        ▼              ▼          ▼          ▼             ▼
   ┌─────────┐  ┌─────────┐  ┌────────┐ ┌─────────┐  ┌──────────┐
   │ eda.py  │  │ planner │  │extractr│ │ quant   │  │synthesizr│
   │ probe   │  │ decomp- │  │ pulls  │ │ Darwin- │  │ merges   │
   │ Alpaca  │  │ ose Q   │  │ from   │ │ evolved │  │ + EDA    │
   │ + risk  │  │         │  │ DBs    │ │ adapter │  │ constr.  │
   └────┬────┘  └─────────┘  └───┬────┘ └─────────┘  └────┬─────┘
        │ live constraints       │                         │
        │ (margin, PDT, halt)    │ Pi-Serini/DARE/         │ binary
        ▼                        ▼ self-correction         ▼ trade
        ┌──────────────────────────────────────────────────┐
        │ retrieval/  pi_serini.py  dare_gate.py           │
        │             self_correction.py  vector_store.py  │
        └──────────────────────────────────────────────────┘
```

## 4. The DB upgrade (concrete plan)

V1's storage is **one 21 GB SQLite file** (`semantic_memory.db`) with four
tables: `memory` (daily prose), `memory_30min`, `memory_monthly`,
`memory_news`. The PDF requires a **hybrid retrieval layer** sitting in
front of it.

| Layer | Tech | Purpose |
|---|---|---|
| Source of truth | existing SQLite (unchanged) | dossier prose + OHLCV + news rows |
| Dense vector | FAISS (CPU `IndexFlatIP` to start; can swap for `IndexIVFPQ`) | semantic similarity over dossier prose |
| Sparse lexical | BM25 via Pyserini *(or `rank_bm25` if Java JVM is too heavy on Hetzner)* | exact-keyword + phrase queries; "Pi-Serini" loop in PDF |
| Router | `retrieval/self_correction.py` | LLM picks dense / sparse / hybrid per sub-query, re-issues if relevance < threshold |
| Gate | `retrieval/dare_gate.py` | "propose-and-clip" multi-objective; clamps retrieval size by accuracy × precision × token-cost |

**No destructive migration.** We never drop the original tables. We *derive*
the indexes from them: `memory_v2/migration_from_v1.py` reads each row,
emits one FAISS embedding + one BM25 document, and persists IDs that map
back to the original `(table, rowid)`. Rebuilds in a few hours overnight.

## 5. The Darwinian "Intelligence Factory"

We do not train a quant model from scratch. We **breed** existing ones.

- **Population** — start with N = 8 candidate quant models. Generation 0
  is seeded from a single base (e.g. `Qwen2.5-7B-Instruct` or
  `Llama-3.1-8B-Instruct`) wearing 8 different LoRA adapters chosen for
  variety (finance-sentiment, math-reasoning, code-reasoning, general
  instruct, etc.).
- **Variation** — each generation:
  - **SLERP merge** (`evolution/merge_slerp.py`) — spherical interpolation
    between two parent adapter weight tensors.
  - **Structural crossover** (`evolution/merge_structural.py`) — swap
    whole transformer-layer blocks between parents.
  - **Mutation** (`evolution/mutate.py`) — small Gaussian noise on a
    random subset of adapter weights.
- **Selection** (`evolution/tournament.py`) — fitness ranks offspring;
  top-K survive into the next generation. Lineage tracked in
  `evolution/lineage.py` so we can re-run any model.
- **Fitness** (`evolution/fitness.py`) — see `FITNESS_FUNCTION.md`. The
  floor is *exact* reproduction of V1's pick ranking on historical days;
  the ceiling is improved Sharpe / hit-rate / drawdown over the same
  evaluation window.

## 6. LoRA swap & distillation

Heavy lifters are run once, distilled, then swapped per request:

- **Distillation** (`distillation/cot_distill.py`) — a 70B teacher
  (Llama 3.3 70B) generates chain-of-thought traces; a 7B student is
  fine-tuned on those traces. Same pipeline V1's Llama+Opus pair could
  feed into.
- **LoRA swap** (`lora/adapter_swap.py`) — `peft.PeftModel.set_adapter()`
  flips between {`quant`, `persona`, `extractor`, ...} in <100 ms on the
  loaded base. Keeps VRAM flat across personas.

## 7. Enterprise Discovery Agent (EDA)

Per PDF section 5. Runs *before* the Synthesizer makes its binary
trade decision. Probes:

- Alpaca `/v2/account` for `pattern_day_trader`, `multiplier`, `cash`,
  `regt_buying_power`, `daytrade_count`.
- Alpaca `/v2/assets/{symbol}` for `tradable`, `marginable`, `shortable`,
  `easy_to_borrow`, `fractionable`.
- Alpaca `/v2/clock` for market `is_open` and `next_close`.
- A small set of inferred constraints: T+1 settlement runway, position-cap
  per ticker, blacklist date.

Injects all of the above as **hard constraints** (`hard_constraints` field
in the Synthesizer context). The Synthesizer cannot return a trade that
violates them, *regardless* of how the Quant agent ranked the idea.

## 8. Execution flow (per PDF section 6)

1. **Trigger** — market-open clock OR detected anomaly (gap, VIX spike,
   ticker halt).
2. **Discovery** — EDA probes Alpaca + vector-index health.
3. **Recursion** — Generator spawns a bespoke sub-graph for this trigger.
4. **Extraction** — Distilled Extractor pulls precise rows via Pi-Serini
   + DARE-gated FAISS lookup.
5. **Analysis** — Darwinian-evolved Quant adapter scores the candidates.
6. **Synthesis** — Synthesizer applies EDA constraints and emits a binary
   `(side, ticker, dollars)` decision plus a thesis.
7. **User output** — Persona adapter rewrites the thesis in plain
   English for the dashboard + daily email.

## 9. Roll-out plan

| Phase | Gate to pass | Risk |
|---|---|---|
| 0 — scaffold | this commit | none |
| 1 — DB upgrade | `migration_from_v1.py` builds indexes; round-trip query against `semantic_memory.db` returns equivalent rows | Low; non-destructive |
| 2 — Quant Gen-0 | Gen-0 adapters loaded; fitness on V1's last 60 trading days ≥ V1's own fitness on same days (mirror floor) | Med; LLM cost |
| 3 — Side-by-side paper | V1 and V2 both deploy at 9:55 ET against separate paper accounts for 4 weeks | Med; no real $ |
| 4 — Promote to primary | V2 beats V1 on weighted-Sharpe AND has positive return over a 4-week window | High; real $ off-ramp |

## 10. Open architecture decisions

- **BM25 lib** — Pyserini (Java/JVM, more accurate) vs `rank_bm25` (pure
  Python, lighter). Hetzner CCX13 has 8 GB RAM and is already at ~70 %
  with the V1 council loaded. → **Default to `rank_bm25`** for now;
  upgrade to Pyserini if precision lags.
- **Base model for distillation** — Qwen2.5-7B vs Llama-3.1-8B. Qwen is
  stronger on numeric reasoning; Llama has better long-context. → **TBD**;
  start with Qwen, fall back to Llama if eval Sharpe lags.
- **Vector store** — FAISS in-process vs Chroma server. We're single-node;
  FAISS in-process wins on latency. → **FAISS in-process**.
- **Where V2 runs** — Hetzner side-by-side with V1, or a sibling box?
  V2's distilled quant + 7B base needs ~16 GB RAM. CCX13 won't fit.
  → **TBD** — likely a CCX23 ($43/mo) sibling for V2 until proven.
