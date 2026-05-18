# memory_v2 — V2's hybrid retrieval layer

The DB upgrade per PDF §3. **Non-destructive:** V1's
`semantic_memory.db` is the source of truth and is never modified.

## What gets built

- `indexes/dense.faiss` — FAISS index over MiniLM embeddings of dossier prose
- `indexes/dense.meta.pkl` — pickle of `(tickers, dossiers)` aligned with the FAISS rows
- `indexes/bm25.pkl` — `(bm25_obj, tickers, dossiers, tokenizer)`

## How to (re)build

```bash
python -m memory_v2.migration_from_v1 --rebuild
```

Reads `semantic_memory.db` row by row from the tables:

- `memory`         (daily prose summaries — primary corpus)
- `memory_monthly` (monthly arc summaries)
- `memory_news`    (news events)

Each row becomes ONE document in both the dense and sparse indexes,
keyed by `ticker` + `date`. Incremental mode (`--since YYYY-MM-DD`) only
adds rows newer than the timestamp.

## Cost / time

On a CCX13 (8 GB RAM, 2 vCPU):

- ~2,000 tickers × 500 trading days ≈ 1 M docs
- MiniLM embedding ≈ 8 hours single-pass; index file ≈ 1.5 GB
- BM25 build ≈ 30 min; index file ≈ 700 MB

Run overnight; the bot only needs the indexes during morning deploy.
