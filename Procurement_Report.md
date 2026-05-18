# Procurement Report

**Hard cap:** $25 USD (Section 2.2 of the executive directive).
**Actual spend this build:** $0.00.
**Result:** Frugality override held. No paid SaaS or APIs were subscribed to.

## Justification by category

| Need | Free option used | Paid option considered | Why free won |
|---|---|---|---|
| Vector index | faiss-cpu | Pinecone / Weaviate Cloud | In-process, no network hop, fits on CCX23 |
| Sparse index | rank_bm25 | Pyserini (free but JVM-heavy) | RAM budget tight (8 GB shared with V1) |
| Embedding model | sentence-transformers/all-MiniLM-L6-v2 | OpenAI text-embedding-3-small | MiniLM runs CPU-only, no per-call cost |
| Model merging | arcee-ai/mergekit (Apache-2) | None (no SaaS equivalent) | Free OSS solves it |
| Agent DAG | langchain-ai/langgraph (MIT) | LangSmith / LangFlow paid | Free SDK is what we need |
| Distillation trainer | unslothai/unsloth (Apache-2) | Modal / RunPod GPU rental | Defer until Gen-1 actually trains; only then pay for GPU hours |
| LLM API | reuse existing Anthropic + Groq + Gemini + xAI keys | New OpenAI key | V1 already paid; no marginal cost |
| Broker | reuse existing Alpaca paper account | New paper account | Single-account dual-ledger via client_order_id prefix |

## Subscriptions opened: NONE.

If Gen-1 evolution requires GPU hours for adapter merging / distillation,
the next session will need to revisit this and budget for a few hours of
RunPod or Modal time — at current pricing roughly $0.50-2.00/hour for an
A100. That would be the first time a real charge is incurred and would
require a separate procurement decision against the $25 cap.
