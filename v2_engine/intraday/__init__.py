"""Intraday risk loop: divergence, trailing stop, news watch, context filter.

Ported verbatim (logic-equivalent) from V1's executioner_v2.py so V2 enforces
the exact same protective rules. Constants come from v2_engine.config so they
can be mutated by Darwinian evolution in later generations.
"""
