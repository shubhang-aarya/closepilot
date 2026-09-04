"""L0 -- candidate generation.

Two ideas, and the second matters more than any solver optimisation.

**Invert the settlement calendar.** A payout on Thursday is not a sweep of the
preceding week; it is the orders captured a fixed number of business days
earlier. Inverting that map replaces a wide date sweep with the two or three
dates that can actually settle on this one. Measured on this portfolio it moves the median pool from ~899 to
under 150, and the counting DP is linear in pool size, so that is a ~6x cut to
the dominant cost of the whole engine.

**Widen only on failure.** The tight window is right for most settlements and
wrong for the ones distorted by holidays or adjustments. Rather than paying the
wide window everywhere, the engine starts tight and escalates only where the
verdict comes back CONTRADICTED -- which is exactly the signal that the true
explanation was pruned. Cost is paid where the difficulty actually is, and the
window that succeeded is recorded on the finding, so escalation is visible in
the audit trail rather than hidden in a constant.

An order discarded here is unreachable by every later layer, so `blocking_recall`
in the harness reports the ceiling this file imposes. Any accuracy figure is
read against it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from attest.model import Order, Settlement

#: Business-day lags to try, tightest first. 2 is the nominal cycle; 3 and 4
#: absorb bank holidays and delayed batches. Escalation stops here: beyond 4 the
#: pool grows faster than recall, which `eval/blocking_study.py` quantifies.
LAG_LADDER: tuple[int, ...] = (2, 3, 4)


def _capture_dates_for(settled_on: date, lag: int, span: int = 12) -> set[date]:
    """Capture dates c with business_days_after(c, lag) == settled_on.

    Built by running the *forward* function over a window and inverting the
    result, rather than reimplementing the arithmetic backwards. Those are not
    the same operation: the forward map is many-to-one, because an order captured
    on Saturday and one captured on the following Monday both settle on the same
    business day. A hand-written inverse returns one date and silently discards
    the weekend -- which is 2/7 of all captures.
    """
    out: set[date] = set()
    for back in range(span + 1):
        c = settled_on - timedelta(days=back)
        day, moved = c, 0
        while moved < lag:
            day += timedelta(days=1)
            if day.weekday() < 5:
                moved += 1
        if day == settled_on:
            out.add(c)
    return out


class PoolIndex:
    """Date-bucketed orders, with global consumption.

    `consume` is the constraint-propagation half of the engine: an order proven
    to belong to one settlement cannot belong to another, so proving an easy
    settlement shrinks every remaining pool. Solving easiest-first therefore
    cascades, and the hard cases are attempted against a materially smaller
    search space than they would have faced in isolation.
    """

    def __init__(self, orders: list[Order]) -> None:
        self._by_day: dict[date, list[Order]] = defaultdict(list)
        for o in orders:
            self._by_day[o.captured_on].append(o)
        self._spent: set[str] = set()

    def consume(self, order_ids: tuple[str, ...] | list[str]) -> None:
        self._spent.update(order_ids)

    @property
    def spent(self) -> int:
        return len(self._spent)

    def audited_pool(self, s: Settlement, rung: int = 0):
        """The pool, plus an account of everything excluded to produce it.

        A solver result is not a claim about the world until you also know what
        was removed before solving and on whose authority — see
        attest/searchspace.py and FAILURES.md D8.
        """
        from attest.searchspace import (SearchSpace, amount_ceiling, consumption,
                                        date_window)
        days = set()
        for lag in LAG_LADDER[: rung + 1]:
            days |= _capture_dates_for(s.settled_on, lag)

        in_window = [o for d in days for o in self._by_day.get(d, ())]
        universe = sum(len(v) for v in self._by_day.values())
        unspent = [o for o in in_window if o.order_id not in self._spent]
        pool = [o for o in unspent if 0 < o.net <= s.net_paise]

        space = SearchSpace(
            universe=universe,
            # CORE-002. The pool IS the candidate universe, so record it rather
            # than its size. Membership is what a proof has to be checkable
            # against; a count cannot distinguish a real order from an invented
            # one.
            members=frozenset(o.order_id for o in pool))
        space.reductions.append(date_window(
            universe - len(in_window), rung, LAG_LADDER[: rung + 1]))
        space.reductions.append(consumption(len(in_window) - len(unspent)))
        space.reductions.append(amount_ceiling(len(unspent) - len(pool), s.net_paise))
        return pool, space

    def pool(self, s: Settlement, rung: int = 0) -> list[Order]:
        """Candidates for `s` at ladder position `rung` (0 = tightest).

        Each rung adds the next lag rather than replacing it, so escalation is
        monotone: a wider window can only add candidates, never lose one that a
        tighter window already offered.
        """
        days: set[date] = set()
        for lag in LAG_LADDER[: rung + 1]:
            days |= _capture_dates_for(s.settled_on, lag)
        out: list[Order] = []
        for d in days:
            for o in self._by_day.get(d, ()):
                if o.order_id not in self._spent and 0 < o.net <= s.net_paise:
                    out.append(o)
        return out


def candidates(settlements: list[Settlement], orders: list[Order],
               rung: int = 0) -> dict[str, list[Order]]:
    """Static pools at a fixed rung. Used by the harness and the baselines;
    the engine itself escalates per settlement via `PoolIndex`."""
    idx = PoolIndex(orders)
    return {s.settlement_id: idx.pool(s, rung) for s in settlements}
