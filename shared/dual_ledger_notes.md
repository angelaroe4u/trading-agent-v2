# Single Alpaca account, two engines

V1 and V2 share **one Alpaca paper account**. Isolation is enforced *only* at
the client_order_id layer and at the ledger layer — Alpaca itself aggregates
positions per symbol.

## Rules

1. **Every V2 order gets `client_order_id = v2_<unix>_<ticker>_<6hex>`.**
   Set in `shared/alpaca_paper.py::_client_order_id()`.
2. **Every V1 order should similarly be tagged `v1_*`.** V1 currently does
   not set client_order_id; the executioner port adds it on the v2 deploy
   pass (see `deploy/install_v2_on_hetzner.sh §patch_v1_client_order_id`).
3. **V2's reconcile only considers orders matching its prefix.** See
   `list_v2_orders()`.
4. **Each ledger is the source of truth for its own pod, cash, and unsettled.**
   `executioner_ledger.json` is V1's; `v2_ledger.json` is V2's. They never
   reference each other.
5. **Position view is *combined* on Alpaca's side.** If V1 holds 1 share AAPL
   and V2 holds 2, Alpaca reports 3 shares AAPL. That's fine for fills/PnL
   tracking because each engine reads its own ledger to know what it bought.
6. **Budget partition is hard.** V1 trades $2k, V2 trades $2k. Neither engine
   touches the other's slice. Total $4k of the $100k paper balance in play.
7. **The "ghost dust" rule still applies.** Tiny fractional positions from
   prior sessions are ignored by both engines — they aren't in either pod.

## What can still go wrong

- **Same ticker, same minute, both engines buy.** Alpaca will fill both as
  separate orders. Position table shows summed shares; each ledger correctly
  records its own. *Not a bug; not interference.*
- **Same ticker, V2 sells, V1 still holds.** Alpaca processes V2's sell against
  V2's qty; V1's ledger pod is untouched. The only risk is V2's `alp_sell`
  attempting more shares than V2 actually holds — guard already in place
  (V2 sells `pos.shares` from V2 ledger only).
- **Reconcile against Alpaca-side positions.** Don't. Each engine reconciles
  only against orders matching its prefix. The combined positions table is
  for human-readable sanity only.
