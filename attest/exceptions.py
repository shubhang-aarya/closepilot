"""Exceptions as first-class output. §18, §29, §31.

197 of 250 settlements come back AMBIGUOUS. That is honest and it is useless: a
finance team cannot action "we cannot tell you". An abstention is only worth
anything if it says what is missing, how much money it involves, and what to go
and look at.

So every unresolved settlement becomes an exception carrying four things a human
can act on:

    a reason code      — machine-readable, from a fixed taxonomy
    an amount          — the unexplained residual, in paise, not a percentage
    the evidence       — what the engine DID establish before it stopped
    a next step        — the specific record to go and find

**The residual is the useful part, and it comes from the model gap D10 named.**
When no subset sums to the credit, the engine can still report the closest subset
and the exact shortfall. "Six orders explain all but ₹680.74; look for a refund
in that amount on or before the value date" is a work item. "AMBIGUOUS" is not.

That reframing costs nothing in safety — a partial explanation is never posted,
never called PROVEN, and never enters the risk model. It only changes what the
engine says while refusing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from attest.model import Order, Settlement, tolerance_paise
from attest.money import rupees
from attest.searchspace import Integrity, SearchSpace
from attest.verdict import Finding, Verdict


class ReasonCode(str, Enum):
    """Why a settlement could not be proven.

    Derived from the fifteen frozen hazard families plus the engine's own
    failure modes, because those families are the ground truth about what
    actually goes wrong rather than a taxonomy invented at a whiteboard.
    """

    MULTIPLE_VALID_ASSIGNMENTS = "MULTIPLE_VALID_ASSIGNMENTS"
    NO_VALID_ASSIGNMENT = "NO_VALID_ASSIGNMENT"
    UNKNOWN_ADJUSTMENT = "UNKNOWN_ADJUSTMENT"
    REFUND_MISMATCH = "REFUND_MISMATCH"
    CHARGEBACK = "CHARGEBACK"
    PARTIAL_SETTLEMENT = "PARTIAL_SETTLEMENT"
    MISSING_TRANSACTION = "MISSING_TRANSACTION"
    DUPLICATE_AMOUNT = "DUPLICATE_AMOUNT"
    TIMING_MISMATCH = "TIMING_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    SEARCH_SPACE_UNCERTAIN = "SEARCH_SPACE_UNCERTAIN"
    DATA_QUALITY = "DATA_QUALITY"


#: What each code means and what to do about it. Every entry names a record to
#: go and find, because an exception whose next step is "investigate" has moved
#: the problem rather than described it.
GUIDE: dict[ReasonCode, tuple[str, str]] = {
    ReasonCode.MULTIPLE_VALID_ASSIGNMENTS: (
        "several disjoint sets of orders satisfy the amount exactly",
        "supply an order-level reference on the settlement report; arithmetic "
        "cannot distinguish these and no better solver will"),
    ReasonCode.NO_VALID_ASSIGNMENT: (
        "no subset of the candidate orders reaches the credit",
        "check whether an order settled outside the expected window, or whether "
        "an adjustment was applied that the merchant's export does not carry"),
    ReasonCode.UNKNOWN_ADJUSTMENT: (
        "the closest explanation leaves a residual with no matching record",
        "look for a fee correction, reversal or manual adjustment in that exact "
        "amount around the value date"),
    ReasonCode.REFUND_MISMATCH: (
        "the credit is smaller than its orders by an unevidenced amount",
        "reconcile the refund ledger for the settlement window; the shortfall is "
        "stated to the paisa"),
    ReasonCode.CHARGEBACK: (
        "the shortfall matches a reversal of an order outside this window",
        "check chargebacks raised in the preceding month against this merchant"),
    ReasonCode.PARTIAL_SETTLEMENT: (
        "an order appears to have been paid out across more than one settlement",
        "pull the gateway's split-settlement report for the affected order"),
    ReasonCode.MISSING_TRANSACTION: (
        "the credit exceeds everything available to explain it",
        "an order is missing from the export; re-pull the capture report for the "
        "window"),
    ReasonCode.DUPLICATE_AMOUNT: (
        "two or more candidate orders are indistinguishable by amount and date",
        "use the payment identifier to break the tie; nothing else can"),
    ReasonCode.TIMING_MISMATCH: (
        "explanation found only after widening the settlement window",
        "confirm the payout calendar for this merchant; the T+2 assumption did "
        "not hold here"),
    ReasonCode.INSUFFICIENT_EVIDENCE: (
        "the settlement was never examined",
        "the amount or the candidate pool exceeds what the solver will attempt; "
        "reduce the window or raise the envelope"),
    ReasonCode.SEARCH_SPACE_UNCERTAIN: (
        "a unique explanation exists, but only within a heuristically reduced space",
        "widen the window and re-run; if the explanation survives, uniqueness is "
        "global rather than local"),
    ReasonCode.DATA_QUALITY: (
        "the records do not support any determination",
        "check the export for truncation or malformed rows"),
}


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class Partial:
    """The closest the engine got. Never posted, never counted as a proof."""

    order_ids: tuple[str, ...]
    net_paise: int
    unexplained_paise: int


@dataclass(frozen=True)
class Settled:
    """The part of an ambiguous settlement that is NOT in dispute.

    Orders appearing in every surviving explanation belong to this settlement
    whichever explanation turns out to be right. The full set is unknown; that
    part of it is not, and saying so turns "we cannot tell you" into "we can tell
    you most of it, and here is exactly what is left".

    D4 tried to *act* on this and it was unsafe — consuming these orders let one
    false proof poison the whole population. Reporting them is a different act
    entirely: nothing is posted, nothing is consumed, no other settlement's pool
    changes. The certainty is stated, not spent.

    `certain` is True only when the enumeration was exhaustive. Otherwise these
    orders are merely common to the explanations that were found, which is a
    weaker claim and is labelled as one.
    """

    order_ids: tuple[str, ...]
    net_paise: int
    disputed_paise: int
    differing_orders: int
    certain: bool


@dataclass(frozen=True)
class Exception_:
    id: str
    settlement_id: str
    reason: ReasonCode
    severity: Severity
    amount_paise: int
    unexplained_paise: int
    established: tuple[str, ...]
    missing: str
    next_step: str
    partial: Partial | None
    settled: Settled | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id, "settlement_id": self.settlement_id,
            "reason": self.reason.value, "severity": self.severity.value,
            "amount_paise": self.amount_paise,
            "unexplained_paise": self.unexplained_paise,
            "established": list(self.established),
            "missing": self.missing, "next_step": self.next_step,
            "partial": None if self.partial is None else {
                "order_ids": list(self.partial.order_ids),
                "net_paise": self.partial.net_paise,
                "unexplained_paise": self.partial.unexplained_paise},
            "settled": None if self.settled is None else {
                "order_ids": list(self.settled.order_ids),
                "net_paise": self.settled.net_paise,
                "disputed_paise": self.settled.disputed_paise,
                "differing_orders": self.settled.differing_orders,
                "certain": self.settled.certain},
        }


def _severity(unexplained: int, amount: int, reason: ReasonCode) -> Severity:
    """Derived from money at stake and whether a human decision is required.

    Not a feeling. A settlement whose entire value is unexplained is a different
    problem from one missing eight rupees, and an ambiguity that a reference
    would settle is less urgent than a credit nothing can account for.
    """
    if reason is ReasonCode.MISSING_TRANSACTION or unexplained >= amount:
        return Severity.HIGH
    share = unexplained / max(amount, 1)
    if unexplained >= 1_00_000 or share > 0.25:
        return Severity.HIGH
    if unexplained >= 5_000 or share > 0.02:
        return Severity.MEDIUM
    return Severity.LOW


def best_partial(pool: list[Order], target: int,
                 exclude: frozenset[str] = frozenset()) -> Partial | None:
    """The subset that gets closest without exceeding the credit.

    Greedy descending. Greedy is the wrong tool for *deciding* a match — D-day
    baselines put that beyond doubt at 226 false proofs in 250 — but it is the
    right tool here, because nothing is being decided. The output is a lower
    bound on what is explainable and an upper bound on what is missing, and both
    are useful even when neither is optimal.
    """
    chosen: list[str] = []
    total = 0
    for o in sorted(pool, key=lambda o: -o.net):
        if o.order_id in exclude:
            continue
        if total + o.net <= target:
            chosen.append(o.order_id)
            total += o.net
    if not chosen:
        return None
    return Partial(tuple(chosen), total, target - total)


def _settled_part(f: Finding, pool: list[Order]) -> Settled | None:
    """Orders common to every surviving explanation, and the disputed remainder."""
    if not f.proofs:
        return None
    common = set(f.proofs[0].order_ids)
    union: set[str] = set()
    for p in f.proofs:
        common &= set(p.order_ids)
        union |= set(p.order_ids)
    net = {o.order_id: o.net for o in pool}
    return Settled(
        order_ids=tuple(sorted(common)),
        net_paise=sum(net.get(o, 0) for o in common),
        disputed_paise=sum(net.get(o, 0) for o in union - common),
        differing_orders=len(union - common),
        certain=f.exhaustive)


def classify(f: Finding, s: Settlement, pool: list[Order],
             seq: int) -> Exception_ | None:
    """Turn an unresolved settlement into a work item. Deterministic; no model."""
    if f.verdict is Verdict.PROVEN:
        space = f.space if isinstance(f.space, SearchSpace) else None
        if space is None or space.integrity is not Integrity.HEURISTIC:
            return None
        # Proven, but only locally. Not an error — a caveat worth surfacing so a
        # reviewer can decide whether local is good enough for this amount.
        return Exception_(
            id=f"EX-{seq:05d}", settlement_id=s.settlement_id,
            reason=ReasonCode.SEARCH_SPACE_UNCERTAIN,
            severity=Severity.LOW if s.net_paise < 1_00_000 else Severity.MEDIUM,
            amount_paise=s.net_paise, unexplained_paise=0,
            established=(f.uniqueness_claim,),
            missing=GUIDE[ReasonCode.SEARCH_SPACE_UNCERTAIN][0],
            next_step=GUIDE[ReasonCode.SEARCH_SPACE_UNCERTAIN][1],
            partial=None)

    established: list[str] = []
    partial: Partial | None = None
    settled: Settled | None = None

    if f.verdict is Verdict.INSUFFICIENT:
        reason = ReasonCode.INSUFFICIENT_EVIDENCE
        unexplained = s.net_paise

    elif f.verdict is Verdict.AMBIGUOUS:
        reason = ReasonCode.MULTIPLE_VALID_ASSIGNMENTS
        established.append(
            f"{len(f.proofs)} explanations satisfy the amount within "
            f"±{f.proofs[0].tolerance_paise} paise" if f.proofs
            else "several explanations survive")

        settled = _settled_part(f, pool)
        unexplained = settled.disputed_paise if settled else 0
        if settled and settled.order_ids:
            established.append(
                f"{len(settled.order_ids)} orders totalling {rupees(settled.net_paise)} "
                f"appear in {'every' if settled.certain else 'every known'} "
                f"explanation and are {'settled' if settled.certain else 'likely settled'}")
            established.append(
                f"the explanations differ over {settled.differing_orders} orders "
                f"worth {rupees(settled.disputed_paise)}")

    else:  # CONTRADICTED — the interesting case, and where the residual lives
        partial = best_partial(pool, s.net_paise)
        unexplained = partial.unexplained_paise if partial else s.net_paise
        if partial:
            established.append(
                f"{len(partial.order_ids)} orders explain "
                f"{rupees(partial.net_paise)} of {rupees(s.net_paise)}")
        pool_total = sum(o.net for o in pool)
        if pool_total < s.net_paise - tolerance_paise(len(pool) or 1):
            reason = ReasonCode.MISSING_TRANSACTION
            unexplained = s.net_paise - pool_total
            established.append(
                f"every candidate order together reaches only {rupees(pool_total)}")
        elif unexplained and unexplained < s.net_paise // 4:
            reason = ReasonCode.UNKNOWN_ADJUSTMENT
        else:
            reason = ReasonCode.NO_VALID_ASSIGNMENT

    missing, step = GUIDE[reason]
    if reason is ReasonCode.MULTIPLE_VALID_ASSIGNMENTS and settled and settled.order_ids:
        step = (f"only {settled.differing_orders} orders are actually in dispute; "
                f"a reference on any one of them settles the rest")

    return Exception_(
        id=f"EX-{seq:05d}", settlement_id=s.settlement_id, reason=reason,
        severity=_severity(unexplained, s.net_paise, reason),
        amount_paise=s.net_paise, unexplained_paise=unexplained,
        established=tuple(established), missing=missing, next_step=step,
        partial=partial, settled=settled)
