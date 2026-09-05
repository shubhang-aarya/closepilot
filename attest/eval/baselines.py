"""Reference matchers, so the engine's number is a comparison rather than a claim.

"20.8% exact-set match" is unfalsifiable on its own: a reader cannot tell whether
that is good, and the honest answer is that it depends entirely on what it cost.
These three run on identical data through the identical harness, and the column
that matters is not accuracy. It is **WRONG** -- entries posted against orders
that did not produce them.

A fuzzy matcher scoring higher on exact-set match while posting false proofs is a
worse system, and the table has to make that visible rather than bury it under a
headline percentage.
"""

from __future__ import annotations

from attest.blocking import candidates
from attest.eval.harness import Prediction
from attest.model import Order, Settlement

#: What a spreadsheet or an off-the-shelf tool treats as "close enough". Not
#: derived from anything -- that is the point. Compare with `tolerance_paise`,
#: which falls out of the rounding behaviour of the fee model.
FUZZY_TOLERANCE = 0.01


def exact_only(settlements: list[Settlement], orders: list[Order]) -> list[Prediction]:
    """Match only where a single order's net equals the credit exactly.

    No tolerance, no search, no accumulation. The floor: what is recoverable
    without reasoning about amounts at all.
    """
    pools = candidates(settlements, orders, rung=2)
    out: list[Prediction] = []
    for s in settlements:
        hits = [o for o in pools[s.settlement_id] if o.net == s.net_paise]
        out.append(Prediction(s.settlement_id,
                              [hits[0].order_id] if len(hits) == 1 else None,
                              "baseline-exact"))
    return out


def fuzzy(settlements: list[Settlement], orders: list[Order]) -> list[Prediction]:
    """Amount within 1%, date inside the window, first candidate wins.

    The industry default, and the number actually worth beating. Note what it
    does when several orders fit: it takes one. That single decision is where
    almost all of its false proofs come from.
    """
    pools = candidates(settlements, orders, rung=2)
    out: list[Prediction] = []
    for s in settlements:
        band = s.net_paise * FUZZY_TOLERANCE
        hits = [o for o in pools[s.settlement_id] if abs(o.net - s.net_paise) <= band]
        out.append(Prediction(s.settlement_id,
                              [hits[0].order_id] if hits else None,
                              "baseline-fuzzy"))
    return out


def greedy(settlements: list[Settlement], orders: list[Order]) -> list[Prediction]:
    """Accumulate the largest orders that still fit, accept if the total lands close.

    The obvious way to handle bundles, and it is wrong for a structural reason
    rather than a tuning one: taking the largest order that fits is a local
    decision, and subset-sum has no greedy-choice property. One early take
    consumes an order a correct explanation needed, and there is no way back --
    the algorithm cannot reconsider, so it reports whatever it happened to reach.

    It also never abstains. Anything within the band is posted, which is exactly
    the behaviour the engine exists to refuse.
    """
    pools = candidates(settlements, orders, rung=2)
    out: list[Prediction] = []
    for s in settlements:
        remaining = s.net_paise
        picked: list[str] = []
        for o in sorted(pools[s.settlement_id], key=lambda o: -o.net):
            if o.net <= remaining:
                picked.append(o.order_id)
                remaining -= o.net
        close = abs(remaining) <= s.net_paise * FUZZY_TOLERANCE
        out.append(Prediction(s.settlement_id, picked if picked and close else None,
                              "baseline-greedy"))
    return out


MATCHERS = {"exact-only": exact_only, "fuzzy": fuzzy, "greedy": greedy}
