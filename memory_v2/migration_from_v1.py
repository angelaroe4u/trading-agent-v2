"""Resumable FAISS + BM25 build from V1's semantic_memory.db. Read-only."""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sqlite3
import time
from pathlib import Path
from typing import Iterator

from v2_engine import config as cfg
from memory_v2.schema import Document

PROGRESS_NAME = "_progress.json"


def iter_documents(db_path, since=None):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [t for t, in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('memory','memory_monthly','memory_news')"
        ).fetchall()]
        for table in tables:
            cols = {c["name"] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            ticker_col = "ticker" if "ticker" in cols else ("symbol" if "symbol" in cols else None)
            date_col = ("date" if "date" in cols else
                        "month" if "month" in cols else
                        "ts" if "ts" in cols else None)
            text_col = ("prose" if "prose" in cols else
                        "summary" if "summary" in cols else
                        "body" if "body" in cols else
                        "text" if "text" in cols else None)
            if not (ticker_col and date_col and text_col):
                continue
            q = f"SELECT rowid, {ticker_col} as t, {date_col} as d, {text_col} as p FROM {table}"
            args = ()
            if since:
                q += f" WHERE {date_col} >= ?"
                args = (since,)
            q += " ORDER BY rowid ASC"
            for row in conn.execute(q, args):
                yield Document(
                    doc_id=f"{table}:{row['rowid']}",
                    ticker=str(row["t"]),
                    date=str(row["d"]),
                    table=table,
                    rowid=int(row["rowid"]),
                    prose=str(row["p"] or ""),
                )
    finally:
        conn.close()


def _load_progress(out_dir):
    p = Path(out_dir) / PROGRESS_NAME
    if not p.exists():
        return {"processed_doc_ids": [], "completed": False, "started_at": time.time()}
    return json.loads(p.read_text())


def _save_progress(out_dir, progress):
    (Path(out_dir) / PROGRESS_NAME).write_text(json.dumps(progress, indent=2))


def build_indexes(db_path, out_dir, since=None, limit=None, rebuild=False, batch=256):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if rebuild:
        for f in out.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
        progress = {"processed_doc_ids": [], "completed": False, "started_at": time.time()}
    else:
        progress = _load_progress(out)
    seen = set(progress.get("processed_doc_ids", []))

    docs = []
    for d in iter_documents(db_path, since=since):
        if d.doc_id in seen:
            continue
        if d.prose.strip():
            docs.append(d)
        if limit is not None and len(docs) >= limit:
            break
    if not docs:
        progress["completed"] = True
        _save_progress(out, progress)
        return {"docs": 0, "dense": 0, "sparse": 0, "already_built": True}

    tickers = [d.ticker for d in docs]
    dossiers = [d.prose for d in docs]

    dense_n = 0
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(cfg.V2_EMBEDDING_MODEL)
        all_emb = []
        for i in range(0, len(dossiers), batch):
            chunk = dossiers[i:i + batch]
            emb = m.encode(chunk, batch_size=batch, show_progress_bar=False,
                           normalize_embeddings=True).astype("float32")
            all_emb.append(emb)
            for d in docs[i:i + batch]:
                progress["processed_doc_ids"].append(d.doc_id)
            _save_progress(out, progress)
        emb = np.concatenate(all_emb, axis=0) if all_emb else None
        if emb is not None:
            idx_path = out / "dense.faiss"
            meta_path = out / "dense.meta.pkl"
            if idx_path.exists() and not rebuild:
                idx = faiss.read_index(str(idx_path))
                idx.add(emb)
                with meta_path.open("rb") as f:
                    old_t, old_d = pickle.load(f)
                tickers = old_t + tickers
                dossiers = old_d + dossiers
            else:
                idx = faiss.IndexFlatIP(emb.shape[1])
                idx.add(emb)
            faiss.write_index(idx, str(idx_path))
            with meta_path.open("wb") as f:
                pickle.dump((tickers, dossiers), f)
            dense_n = len(dossiers)
    except Exception as e:
        print(f"migration: dense skipped ({e})")

    sparse_n = 0
    try:
        from rank_bm25 import BM25Okapi
        def tokenizer(s):
            return s.lower().split()
        corpus = [tokenizer(s) for s in dossiers]
        bm25 = BM25Okapi(corpus)
        with (out / "bm25.pkl").open("wb") as f:
            pickle.dump((bm25, tickers, dossiers, tokenizer), f)
        sparse_n = len(dossiers)
    except Exception as e:
        print(f"migration: sparse skipped ({e})")

    progress["completed"] = (limit is None and not since)
    _save_progress(out, progress)
    return {"docs": len(docs), "dense": dense_n, "sparse": sparse_n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=cfg.V1_SEMANTIC_MEMORY_DB)
    ap.add_argument("--out", default=os.path.dirname(cfg.V2_FAISS_INDEX))
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--since", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()
    stats = build_indexes(args.db, args.out, since=args.since,
                          limit=args.limit, rebuild=args.rebuild, batch=args.batch)
    print(f"migration: {stats}")


if __name__ == "__main__":
    main()
