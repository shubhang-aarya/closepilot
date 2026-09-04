"""Synthetic portfolio generator.

The critical property: settlements are derived *from* orders, never invented
alongside them. That makes the order->settlement mapping known exactly rather
than approximately, which is the only reason any accuracy figure this project
reports can be trusted. It is also why Track 04 was chosen over the fraud track,
where ground truth would have been whatever patterns the author imagined.

Determinism is load-bearing: same seed, same bytes. The held-out split is drawn
from a separate seed and is intended to be executed once, at the end.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from attest.generate.taxonomy import DEFAULT_MIX, Case
from attest.model import BankCredit, Method, Order, Settlement, TrueMatch, net_paise

_FIRST_NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vihaan", "Isha"]
_LAST_NAMES = ["Sharma", "Iyer", "Nair", "Bose", "Reddy", "Gill", "Menon", "Rao"]


@dataclass
class Dataset:
    orders: list[Order] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    credits: list[BankCredit] = field(default_factory=list)
    truth: list[TrueMatch] = field(default_factory=list)

    def write(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        _dump(out / "orders.csv",
              ["order_id", "captured_on", "gross_paise", "method", "customer_name", "payment_id"],
              [(o.order_id, o.captured_on, o.gross_paise, o.method.value,
                o.customer_name, o.payment_id or "") for o in self.orders])
        _dump(out / "settlements.csv",
              ["settlement_id", "settled_on", "net_paise", "utr"],
              [(s.settlement_id, s.settled_on, s.net_paise, s.utr or "") for s in self.settlements])
        _dump(out / "bank.csv",
              ["txn_id", "value_date", "credit_paise", "narration"],
              [(c.txn_id, c.value_date, c.credit_paise, c.narration) for c in self.credits])
        _dump(out / "truth.csv",
              ["settlement_id", "case", "order_ids"],
              [(t.settlement_id, t.case, " ".join(t.order_ids)) for t in self.truth])


def _dump(path: Path, header: list[str], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _business_days_after(start: date, n: int) -> date:
    """Settlement lands T+n business days out. Weekends push it, which is what
    makes a fixed-width date window the wrong abstraction."""
    day, moved = start, 0
    while moved < n:
        day += timedelta(days=1)
        if day.weekday() < 5:
            moved += 1
    return day


class Generator:
    def __init__(self, seed: int, mix: dict[Case, float] | None = None) -> None:
        self.rng = random.Random(seed)
        self.mix = mix or DEFAULT_MIX
        self._n = 0

    # -- primitives --------------------------------------------------------

    def _oid(self) -> str:
        self._n += 1
        return f"ord_{self._n:06d}"

    def _name(self) -> str:
        return f"{self.rng.choice(_FIRST_NAMES)} {self.rng.choice(_LAST_NAMES)}"

    def _order(self, on: date, *, method: Method | None = None,
               gross: int | None = None, ref: bool = True) -> Order:
        m = method or self.rng.choices(
            [Method.UPI, Method.CARD, Method.NETBANKING, Method.WALLET],
            weights=[0.55, 0.25, 0.12, 0.08])[0]
        g = gross if gross is not None else self.rng.randrange(9_900, 4_500_00)
        oid = self._oid()
        return Order(oid, on, g, m, self._name(),
                     f"pay_{oid[4:]}" if ref else None)

    # -- hazard construction ----------------------------------------------

    def _bundle(self, case: Case, on: date) -> tuple[list[Order], list[Order], int]:
        """Return (bundle, extra_pool_orders, credit_paise) for one settlement.

        `extra_pool_orders` land in the order file but not in this settlement --
        they exist to create the ambiguity the matcher has to resolve.
        """
        rng = self.rng
        size = {
            Case.CLEAN: lambda: rng.randint(1, 6),
            Case.BUNDLE_LARGE: lambda: rng.randint(20, 40),
            Case.AMBIGUOUS_SUBSET: lambda: rng.randint(3, 5),
        }.get(case, lambda: rng.randint(3, 12))()

        if case is Case.MIXED_METHOD:
            methods = [Method.UPI, Method.CARD, Method.WALLET]
            bundle = [self._order(on, method=methods[i % 3]) for i in range(size)]
        elif case is Case.MISSING_REF:
            bundle = [self._order(on, ref=rng.random() > 0.6) for _ in range(size)]
        elif case is Case.DUPLICATE_AMOUNT:
            twin = rng.randrange(50_000, 200_000)
            bundle = [self._order(on, method=Method.UPI, gross=twin) for _ in range(2)]
            bundle += [self._order(on) for _ in range(size - 2)]
        else:
            bundle = [self._order(on) for _ in range(size)]

        credit = sum(o.net for o in bundle)
        extra: list[Order] = []

        if case is Case.REFUND_OFFSET:
            # A refund nets off inside the payout: the credit is *below* the sum
            # of its orders, so an upward-only search never finds it.
            credit -= rng.randrange(5_000, min(credit // 3, 150_000) or 5_000)
        elif case is Case.CHARGEBACK_REVERSAL:
            old = self._order(on - timedelta(days=rng.randint(14, 30)))
            extra.append(old)
            credit -= old.net
        elif case is Case.SPLIT_ORDER:
            # Half of one order's proceeds arrive here, half in a later payout.
            credit -= bundle[-1].net // 2
        elif case is Case.ORPHAN_SETTLEMENT:
            # An order the merchant never exported. Unsolvable on purpose.
            credit += net_paise(rng.randrange(20_000, 300_000), Method.CARD)
        elif case is Case.AMBIGUOUS_SUBSET:
            extra = self._collide(on, credit)

        return bundle, extra, credit

    def _collide(self, on: date, target: int) -> list[Order]:
        """Build a disjoint UPI-only set whose nets sum to exactly `target`.

        UPI is zero-MDR, so net == gross and the sum can be closed exactly. The
        result is a second arithmetically-perfect explanation for the same
        credit, which no amount of solver cleverness can rule out -- only a
        reference or a name can. This is what forces a posterior.
        """
        k = self.rng.randint(2, 4)
        parts: list[int] = []
        remaining = target
        for _ in range(k - 1):
            take = self.rng.randrange(remaining // (k + 1), remaining // 2)
            parts.append(take)
            remaining -= take
        parts.append(remaining)
        return [self._order(on, method=Method.UPI, gross=p) for p in parts if p > 0]

    # -- narration ---------------------------------------------------------

    def _narration(self, utr: str, case: Case) -> str:
        base = f"NEFT-{utr}-RAZORPAY SOFTWARE PVT LTD-SETTLEMENT"
        if case is not Case.NARRATION_GARBLE:
            return base
        style = self.rng.randint(0, 2)
        if style == 0:
            return base[: self.rng.randint(18, 26)]           # truncated mid-UTR
        if style == 1:
            return base.lower().replace("-", " ")             # delimiters gone
        return base.replace(utr, utr[:4] + "X" * (len(utr) - 4))  # masked

    # -- driver ------------------------------------------------------------

    def build(self, n_settlements: int, start: date = date(2026, 5, 1)) -> Dataset:
        ds = Dataset()
        cases, weights = zip(*self.mix.items())

        for i in range(n_settlements):
            case = self.rng.choices(cases, weights=weights)[0]
            captured = start + timedelta(days=self.rng.randrange(0, 90))
            if case is Case.MONTH_BOUNDARY:
                captured = captured.replace(day=28) + timedelta(days=self.rng.randint(0, 3))

            lag = 4 if case is Case.TIMING_GAP else 2
            settled = _business_days_after(captured, lag)

            bundle, extra, credit = self._bundle(case, captured)
            ds.orders.extend(bundle)
            ds.orders.extend(extra)

            if case is Case.ORPHAN_ORDER:
                # Captured but never settled. Correct behaviour is to leave it
                # alone, so this family measures restraint, not recall.
                ds.orders.append(self._order(captured))

            sid = f"setl_{i:06d}"
            utr = f"{self.rng.randrange(10**11, 10**12)}"
            ds.settlements.append(Settlement(sid, settled, credit, utr))
            ds.credits.append(BankCredit(f"bank_{i:06d}", settled, credit,
                                         self._narration(utr, case)))
            ds.truth.append(TrueMatch(sid, tuple(o.order_id for o in bundle), case.value))

        ds.orders.sort(key=lambda o: (o.captured_on, o.order_id))
        return ds


def build(n_settlements: int, seed: int) -> Dataset:
    return Generator(seed).build(n_settlements)
