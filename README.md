# Trading Agent 2.0

A Dynamic Multi-Agent RAG successor to the V1 monolithic council in
`C:\Projects\tradingap`. Trades **side-by-side** with V1 on Alpaca paper so
we can measure the upgrade's accuracy delta in real time.

**Status:** scaffold + V1-mirror fitness function complete. See
[`MEMORY.md`](./MEMORY.md) for full progress log.

## Quick read order

1. [`MEMORY.md`](./MEMORY.md) — project memory; what's done, what's next.
2. [`ARCHITECTURE_V2.md`](./ARCHITECTURE_V2.md) — translation of the PDF spec
   into our module layout.
3. [`FITNESS_FUNCTION.md`](./FITNESS_FUNCTION.md) — how the V1 decision logic
   was extracted and how Darwinian offspring will be judged.
4. [`COMPARISON_PROTOCOL.md`](./COMPARISON_PROTOCOL.md) — how V1 and V2 trade
   the same day without contaminating each other.

## Run

```bash
# Side-by-side daily runner (once V1's ledger + V2's .env are configured)
python -m paper_trade.side_by_side_runner

# Verify fitness still mirrors V1 (run before merging any evolution change)
pytest tests/test_fitness_mirrors_v1.py -v
```

## V1 lives where?

- Local mirror: `C:\Projects\tradingap` (parent of this folder)
- Server: `angela@5.161.197.162:/opt/tradingap`
