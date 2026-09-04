"""Core domain model.

Money is an integer number of paise, everywhere, without exception. A float
would make the tolerance derivation in `tolerance_paise` meaningless: that
bound is a statement about integer rounding error, and it only holds if no
amount has ever been through a binary float.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

# --------------------------------------------------------------------------
# Fee model
# --------------------------------------------------------------------------


class Method(str, Enum):
    """Payment method.

    Present in the domain model only because it determines the fee rate. Two
    orders of identical gross value settle for different net amounts if they
    were paid by different methods, which is the single reason naive
    amount-matching fails on real settlement data.
    """

    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


#: Gateway fee in basis points of gross, by method. UPI is zero-MDR in India.
FEE_BPS: dict[Method, int] = {
    Method.UPI: 0,
    Method.CARD: 200,
    Method.NETBANKING: 150,
    Method.WALLET: 250,
}

#: GST is charged on the fee, never on the gross.
GST_BPS = 1800


def _round_half_up(numerator: int, denominator: int) -> int:
    """Divide, rounding halves away from zero.

    Neither builtin does this: `round` is banker's rounding (ties to even) and
    `int` truncates toward zero. A gateway rounds fees half-up, and a one-paisa
    disagreement here compounds across a 40-order bundle into a mismatch.
    """
    return (numerator + denominator // 2) // denominator


def fee_paise(gross_paise: int, method: Method) -> int:
    """Gateway fee on a single order."""
    return _round_half_up(gross_paise * FEE_BPS[method], 10_000)


def tax_paise(fee: int) -> int:
    """GST on a fee."""
    return _round_half_up(fee * GST_BPS, 10_000)


def net_paise(gross_paise: int, method: Method) -> int:
    """What one order actually contributes to a bank credit.

    This function is the hinge of the whole engine. Fees are deterministic, so
    normalising every order to its net *before* matching converts

        settlement ~= sum(gross) - unknown fees        (approximate search)

    into

        settlement  = sum(net) +/- rounding            (exact subset-sum)

    Everything downstream -- meet-in-the-middle, the CP-SAT model, the
    confidence scores -- depends on that being an equality.
    """
    f = fee_paise(gross_paise, method)
    return gross_paise - f - tax_paise(f)


def tolerance_paise(subset_size: int) -> int:
    """Largest |sum(net) - credit| still consistent with a genuine match.

    `fee_paise` and `tax_paise` each round independently, so a single order
    carries at most one paisa of error in either direction. Rounding errors do
    not cancel systematically, so a k-order subset can drift by at most k.

    Derived, not tuned. A hand-picked constant is wrong in both directions at
    once: too tight and large bundles never match, too loose and small subsets
    collide with each other inside the tolerance band.
    """
    return subset_size


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Order:
    """A captured payment, as the merchant's own system recorded it."""

    order_id: str
    captured_on: date
    gross_paise: int
    method: Method
    customer_name: str
    payment_id: str | None
    """Gateway reference. Absent or malformed on a minority of rows -- those
    are precisely the rows that fall through to amount-based matching."""

    @property
    def net(self) -> int:
        return net_paise(self.gross_paise, self.method)


@dataclass(frozen=True, slots=True)
class Settlement:
    """A payout the gateway says it made."""

    settlement_id: str
    settled_on: date
    net_paise: int
    utr: str | None


@dataclass(frozen=True, slots=True)
class BankCredit:
    """A credit line on the merchant's bank statement."""

    txn_id: str
    value_date: date
    credit_paise: int
    narration: str
    """Free text. The only field in the system an LLM has any business reading."""


@dataclass(frozen=True, slots=True)
class TrueMatch:
    """Ground truth: which orders actually composed a settlement.

    Known by construction because the generator derives settlements *from*
    orders rather than inventing both and hoping. Every accuracy number the
    engine reports is measured against this.
    """

    settlement_id: str
    order_ids: tuple[str, ...]
    case: str
    """The adversarial family this row was generated to exercise, so failures
    can be attributed to a cause rather than to a percentage."""
