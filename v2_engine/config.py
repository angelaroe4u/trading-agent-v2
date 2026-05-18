"""
v2_engine.config — Configuration for Trading Agent V2.
"""
from __future__ import annotations
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MORNING_DEPLOY_AT = (9, 55)
HARVEST_AT        = (15, 50)
NIGHT_GUARD_CUTOFF = (16, 15)
NIGHT_GUARD_WAKE   = (9, 20)

V1_BASELINE_POD_SIZE                 = 3
V1_BASELINE_MORNING_DEPLOY_PCT       = 1.0
V1_BASELINE_POSITION_WEIGHTS         = [0.50, 0.30, 0.20]
V1_BASELINE_CONVICTION_GATE          = 0.70
V1_BASELINE_HORIZON_DAYS             = 5
V1_BASELINE_TRAILING_STOP_PCT        = 2.0   # fallback when ADR unavailable
V2_TRAILING_STOP_ADR_MULT            = 1.5   # primary: stop band = mult * ADR_14d (%)
V1_BASELINE_DIVERGENCE_CURVE         = [(11, 30, 0.33), (13, 0, 0.60), (14, 30, 0.85)]
V1_BASELINE_DIVERGENCE_LAG_PP        = 3.0
V1_BASELINE_DIVERGENCE_DRAWDOWN_PCT  = -2.0
V1_BASELINE_DIVERGENCE_COOLDOWN_MIN  = 60
V1_BASELINE_DIVERGENCE_GRACE_MIN     = 30
V1_BASELINE_DIVERGENCE_CHECK_INT_MIN = 5
V1_BASELINE_INTRADAY_SKIP_THRESHOLD  = 0.60
V1_BASELINE_INTRADAY_MIN_REMAIN_PP   = 1.0
V1_BASELINE_CANDIDATE_POOL           = 80
V1_BASELINE_EACH_PICKS               = 3
V1_BASELINE_QUEUE_SIZE               = 12
V1_BASELINE_BENCH_DEPTH              = 12
V1_BASELINE_LIGHT_NEWS_INTERVAL_MIN  = 12
V1_BASELINE_VIX_PANIC_PCT            = 0.10
V1_BASELINE_SPY_PANIC_PCT            = -0.01

V1_BASELINE_COUNCIL_MODELS = {
    "picker_a": os.getenv("LLAMA_MODEL",  "llama-3.3-70b-versatile"),
    "picker_b": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "judge":    os.getenv("JUDGE_MODEL",  "claude-opus-4-6"),
    "haiku":    os.getenv("HAIKU_MODEL",  "claude-haiku-4-5-20251001"),
    "news":     os.getenv("GROK_LIGHT_MODEL", "grok-3-mini"),
}

V2_CLIENT_ORDER_ID_PREFIX = os.getenv("V2_CLIENT_ORDER_ID_PREFIX", "v2_")
V1_CLIENT_ORDER_ID_PREFIX = os.getenv("V1_CLIENT_ORDER_ID_PREFIX", "v1_")
V2_TRADE_BUDGET_USD       = float(os.getenv("V2_TRADE_BUDGET_USD", "2000"))

V2_POPULATION_SIZE     = int(os.getenv("V2_POPULATION_SIZE", "8"))
V2_FITNESS_LAMBDA      = float(os.getenv("V2_FITNESS_LAMBDA", "0.0"))
V2_LAMBDA_SCHEDULE     = {0: 0.0, 1: 0.1, 2: 0.3, 3: 0.5, 4: 1.0}
V2_BASE_MODEL          = os.getenv("V2_BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
V2_JUDGE_MODEL         = os.getenv("V2_JUDGE_MODEL", "claude-opus-4-6")
V2_PERSONA_MODEL       = os.getenv("V2_PERSONA_MODEL", "claude-haiku-4-5-20251001")
V2_EMBEDDING_MODEL     = os.getenv("V2_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
V2_DARE_MIN_ACCURACY   = 0.80
V2_DARE_MAX_TOKENS     = 12_000
V2_DARE_MIN_PRECISION  = 0.70
V2_PI_SERINI_MAX_ITERS = 4

V1_REPO_PATH          = os.getenv("V1_REPO_PATH", r"C:\Projects\tradingap")
V1_TRADE_LOG          = os.getenv("V1_TRADE_LOG",          os.path.join(V1_REPO_PATH, "trade_log.jsonl"))
V1_LEDGER             = os.getenv("V1_LEDGER",             os.path.join(V1_REPO_PATH, "executioner_ledger.json"))
V1_SEMANTIC_MEMORY_DB = os.getenv("V1_SEMANTIC_MEMORY_DB", os.path.join(V1_REPO_PATH, "semantic_memory.db"))

V2_REPO_PATH         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_LEDGER            = os.path.join(V2_REPO_PATH, "v2_ledger.json")
V2_TRADE_LOG         = os.path.join(V2_REPO_PATH, "v2_trade_log.jsonl")
V2_COMPARISON_LEDGER = os.path.join(V2_REPO_PATH, "comparison_ledger.jsonl")
V2_FAISS_INDEX       = os.getenv("V2_FAISS_INDEX", os.path.join(V2_REPO_PATH, "memory_v2", "indexes", "dense.faiss"))
V2_BM25_INDEX        = os.getenv("V2_BM25_INDEX",  os.path.join(V2_REPO_PATH, "memory_v2", "indexes", "bm25.pkl"))
