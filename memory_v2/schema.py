"""
memory_v2.schema — record types produced by the migration.

A ``Document`` is the unit indexed in both FAISS and BM25. Each one carries
provenance back to V1's `semantic_memory.db` via ``(table, rowid)`` so we
can rebuild incrementally and so the Synthesizer can cite sources.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Document:
    doc_id: str          # f"{table}:{rowid}"
    ticker: str
    date: str            # YYYY-MM-DD
    table: str           # "memory" | "memory_monthly" | "memory_news"
    rowid: int
    prose: str           # the dossier-style text
