"""Layers 1-2 -- the deterministic floor.

Neither layer uses a model, and both are exact: they either prove a match or
decline. Everything they resolve is removed from the search space before the
exponential work in layer 3 begins, which is why the cheap layers are worth
writing carefully rather than skipping straight to the interesting algorithm.
"""

from __future__ import annotations

import re

from attest.model import BankCredit, Order, Settlement, tolerance_paise

_UTR = re.compile(r"\b(\d{9,14})\b")


def match_credits_to_settlements(
    credits: list[BankCredit], settlements: list[Settlement]
) -> dict[str, str]:
    """Layer 1: bank credit -> settlement, by UTR recovered from free text.

    Falls back to (exact amount, exact value date), which is safe only because a
    duplicate on both keys is rare enough to be worth surfacing as an exception
    rather than guessing at. Returns txn_id -> settlement_id.
    """
    by_utr = {s.utr: s.settlement_id for s in settlements if s.utr}
    by_amount_date: dict[tuple[int, object], list[str]] = {}
    for s in settlements:
        by_amount_date.setdefault((s.net_paise, s.settled_on), []).append(s.settlement_id)

    out: dict[str, str] = {}
    for c in credits:
        hit = next((by_utr[m] for m in _UTR.findall(c.narration) if m in by_utr), None)
        if hit is None:
            same = by_amount_date.get((c.credit_paise, c.value_date), [])
            hit = same[0] if len(same) == 1 else None
        if hit is not None:
            out[c.txn_id] = hit
    return out


def match_single_order(
    settlement: Settlement, pool: list[Order]
) -> list[str] | None:
    """Layer 2: settlement -> exactly one order, within one order's rounding.

    Declines when two or more orders fit. Returning the first would score
    slightly better on average and be wrong in a way that moves money, so the
    ambiguity is handed to the solver instead.
    """
    tol = tolerance_paise(1)
    fits = [o for o in pool if abs(o.net - settlement.net_paise) <= tol]
    return [fits[0].order_id] if len(fits) == 1 else None
