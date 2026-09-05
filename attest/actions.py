"""What to do, ranked by what it unlocks. §31.

The exceptions screen groups settlements by why the engine stopped. That is the
right grouping for understanding and the wrong one for working, because it
implies a queue: 197 ambiguous settlements reads as 197 things to do.

It is one thing to do. Every one of those 197 is ambiguous because the
settlement report carries no order-level reference, and arithmetic cannot
distinguish disjoint sets that hit the same total — so the fix is a change to
what the report contains, applied once, and it resolves all of them. Ranking by
settlement count buries that under the noise of individually small items.

So this module ranks by **value unlocked per action taken**, and states which
kind of action each is:

    SYSTEMIC   one change at the source resolves the whole group. Highest
               leverage in the product, and the thing worth escalating.
    RERUN      no new data is needed. The engine already holds everything and
               was deliberately conservative; changing a parameter and running
               again is free.
    PER_ITEM   someone has to go and find a specific record. Real work, and it
               does not amortise.

The distinction is not cosmetic. A queue that mixes "ask the gateway to add a
column" with "find this ₹6,316 adjustment" and sorts both by amount will put a
week of individual work above a one-line change worth eighty times more.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from attest.exceptions import GUIDE, ReasonCode


class Kind(str, Enum):
    SYSTEMIC = "systemic"
    RERUN = "rerun"
    PER_ITEM = "per_item"


#: How each exception reason is worked, and what it costs to work it. The
#: classification is a claim about the world, not about the code, so it is
#: written down here where it can be argued with rather than inferred from
#: behaviour.
KINDS: dict[ReasonCode, tuple[Kind, str]] = {
    ReasonCode.MULTIPLE_VALID_ASSIGNMENTS: (
        Kind.SYSTEMIC,
        "One field on the settlement report resolves every settlement in this "
        "group at once. No solver can do it instead — several disjoint order "
        "sets hit the credit exactly, so the information required to choose "
        "between them is not present in the records."),
    ReasonCode.SEARCH_SPACE_UNCERTAIN: (
        Kind.RERUN,
        "Nothing new is needed. A unique explanation already exists; it is "
        "unique inside a window the engine narrowed for speed, and the engine "
        "refuses to call that global. Re-running wider either confirms it or "
        "does not, and both answers are worth having."),
    ReasonCode.TIMING_MISMATCH: (
        Kind.RERUN,
        "The payout calendar assumption did not hold for these. Confirming the "
        "merchant's actual calendar and re-running costs no new data."),
    ReasonCode.DUPLICATE_AMOUNT: (
        Kind.SYSTEMIC,
        "The candidates are indistinguishable by amount and date. The payment "
        "identifier breaks the tie and nothing else does, so this is a field on "
        "the export rather than a per-settlement investigation."),
    ReasonCode.MISSING_TRANSACTION: (
        Kind.SYSTEMIC,
        "The export is incomplete. Re-pulling the capture report for the window "
        "addresses every settlement affected by the same gap."),
    ReasonCode.DATA_QUALITY: (
        Kind.SYSTEMIC,
        "Malformed or truncated rows are a property of the export, not of any "
        "one settlement."),
    ReasonCode.INSUFFICIENT_EVIDENCE: (
        Kind.RERUN,
        "These were never examined — the amount or the pool exceeded what the "
        "solver will attempt. Raising the envelope is a configuration change."),
    ReasonCode.UNKNOWN_ADJUSTMENT: (
        Kind.PER_ITEM,
        "Each of these is a specific amount on a specific date with no matching "
        "record. Someone has to find it, and finding one does not help with the "
        "next."),
    ReasonCode.REFUND_MISMATCH: (
        Kind.PER_ITEM,
        "The shortfall is stated to the paisa, but the matching refund has to be "
        "located in the refund ledger one settlement at a time."),
    ReasonCode.CHARGEBACK: (
        Kind.PER_ITEM,
        "A reversal outside this window. Each needs checking against the "
        "chargebacks raised for that merchant."),
    ReasonCode.PARTIAL_SETTLEMENT: (
        Kind.PER_ITEM,
        "The gateway's split-settlement report has to be pulled per affected "
        "order."),
    ReasonCode.NO_VALID_ASSIGNMENT: (
        Kind.PER_ITEM,
        "Nothing in the candidate pool reaches the credit. Each is its own "
        "question about what is missing."),
}


@dataclass(frozen=True)
class Action:
    reason: ReasonCode
    kind: Kind
    what: str
    why: str
    rationale: str
    settlements: int
    value_paise: int
    unexplained_paise: int
    examples: tuple[str, ...]

    @property
    def steps(self) -> int:
        """How many separate pieces of work this is.

        One for a systemic change or a re-run; one per settlement otherwise.
        This is the denominator that makes the ranking honest.
        """
        return 1 if self.kind is not Kind.PER_ITEM else self.settlements

    @property
    def leverage_paise(self) -> int:
        """Value unlocked per piece of work."""
        return self.value_paise // max(self.steps, 1)

    def to_json(self) -> dict[str, object]:
        return {
            "reason": self.reason.value, "kind": self.kind.value,
            "what": self.what, "why": self.why, "rationale": self.rationale,
            "settlements": self.settlements, "value_paise": self.value_paise,
            "unexplained_paise": self.unexplained_paise,
            "steps": self.steps, "leverage_paise": self.leverage_paise,
            "examples": list(self.examples),
        }


def plan(exceptions: dict[str, object], amounts: dict[str, int]) -> list[Action]:
    """Rank the work by what each piece of it unlocks.

    `amounts` is settlement id -> the credit at stake, taken from the settlement
    rather than the exception, because the exception records the unexplained
    portion and the question here is how much value the action releases.
    """
    agg: dict[ReasonCode, dict[str, object]] = {}
    for sid, e in exceptions.items():
        code = e.reason  # type: ignore[attr-defined]
        a = agg.setdefault(code, {"n": 0, "value": 0, "unexplained": 0,
                                  "examples": []})
        a["n"] += 1                                        # type: ignore[operator]
        a["value"] += amounts.get(sid, 0)                  # type: ignore[operator]
        a["unexplained"] += e.unexplained_paise            # type: ignore[attr-defined,operator]
        if len(a["examples"]) < 6:                         # type: ignore[arg-type]
            a["examples"].append(sid)                      # type: ignore[attr-defined]

    out: list[Action] = []
    for code, a in agg.items():
        kind, rationale = KINDS.get(code, (Kind.PER_ITEM, ""))
        why, what = GUIDE.get(code, ("", ""))
        out.append(Action(
            reason=code, kind=kind, what=what, why=why, rationale=rationale,
            settlements=int(a["n"]), value_paise=int(a["value"]),
            unexplained_paise=int(a["unexplained"]),
            examples=tuple(a["examples"]),                  # type: ignore[arg-type]
        ))

    # By leverage, then by total value. A systemic change worth ₹47L outranks
    # fifty individual investigations worth ₹10k each, which is the ordering the
    # exceptions screen could not express.
    return sorted(out, key=lambda x: (-x.leverage_paise, -x.value_paise))
