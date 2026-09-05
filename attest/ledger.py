"""The accounting entry a proof implies. §21.

A verdict is not the deliverable. A finance controller's output is a journal
entry, and everything upstream of that — the pool, the subset-sum, the kernel,
the risk pricing — exists to earn the right to write one. This module is that
last step, and it is deliberately the dullest code in the repository: it does no
searching, makes no decision, and cannot rescue a weak proof. It composes.

The entry for a settlement is fixed by the fee model and nothing else:

    Dr  Bank                    net           the money that actually arrived
    Dr  Payment gateway fees    fee           the gateway's cut, as expense
    Dr  Input GST               tax           recoverable, so an asset
        Cr  Trade receivables       gross     what the customer owed, discharged

which balances because `net = gross - fee - tax` is the identity the whole
engine is built on. That is the point of posting it this way: the balance check
is the fee model restated, so an entry that does not balance is a rule set that
disagrees with the records rather than a bookkeeping slip.

Three refusals, all of them structural:

  * Only PROVEN produces an entry. An ambiguous settlement has several valid
    order sets, and they debit receivables against DIFFERENT customers. There
    is no "mostly right" journal entry — posting the wrong one moves money in
    the books against a customer who does not owe it.

  * Only an AUTO_POST judgement produces an entry. Proven means the arithmetic
    is unique; posting is a question about what a mistake would cost, and that
    is the policy's to answer.

  * A proof over a compromised search space produces nothing, whatever its
    verdict. Uniqueness inside a space that excluded the truth is not
    uniqueness.

Nothing here writes to an external system. `post` returns a record; who applies
it, and under what approval, is not this module's business and deliberately not
any agent's — see `agents.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attest.model import Order, Settlement
from attest.searchspace import why_not_postable
from attest.rules import DEFAULT, RuleSet
from attest.policy import Decision, Judgement
from attest.verdict import Finding, Verdict, check


class Unbalanced(Exception):
    """Debits did not equal credits.

    Raised at construction, not discovered at review time. An unbalanced entry
    is never a thing to hold and inspect — it means the fee model and the
    records disagree, and the correct response is to refuse to produce it.
    """


#: Account names. Deliberately the ordinary ones rather than invented codes: a
#: controller reading this screen should recognise their own chart of accounts,
#: and an entry they cannot name is an entry they cannot check.
BANK = "Bank"
RECEIVABLES = "Trade receivables"
FEES = "Payment gateway fees"
GST = "Input GST (recoverable)"


@dataclass(frozen=True)
class Line:
    account: str
    debit_paise: int = 0
    credit_paise: int = 0
    memo: str = ""

    def __post_init__(self) -> None:
        if self.debit_paise and self.credit_paise:
            raise Unbalanced(f"{self.account}: a line is a debit or a credit, "
                             f"never both")
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise Unbalanced(f"{self.account}: negative amounts are the other "
                             f"side of the entry, not a sign")

    def to_json(self) -> dict[str, object]:
        return {"account": self.account, "debit_paise": self.debit_paise,
                "credit_paise": self.credit_paise, "memo": self.memo}


@dataclass(frozen=True)
class JournalEntry:
    settlement_id: str
    value_date: str
    utr: str
    lines: tuple[Line, ...]
    order_ids: tuple[str, ...]
    provenance: str
    proof_residual_paise: int
    proof_tolerance_paise: int

    def __post_init__(self) -> None:
        d = sum(x.debit_paise for x in self.lines)
        c = sum(x.credit_paise for x in self.lines)
        if d != c:
            raise Unbalanced(
                f"{self.settlement_id}: debits {d} != credits {c}. This is not "
                f"a bookkeeping slip — the entry is derived from the fee model, "
                f"so a difference means the rules disagree with the records.")

    @property
    def total_paise(self) -> int:
        return sum(x.debit_paise for x in self.lines)

    def to_json(self) -> dict[str, object]:
        return {
            "settlement_id": self.settlement_id, "value_date": self.value_date,
            "utr": self.utr, "lines": [x.to_json() for x in self.lines],
            "order_ids": list(self.order_ids), "provenance": self.provenance,
            "total_paise": self.total_paise,
            "orders": len(self.order_ids),
            "residual_paise": self.proof_residual_paise,
            "tolerance_paise": self.proof_tolerance_paise,
        }


@dataclass(frozen=True)
class Refusal:
    settlement_id: str
    amount_paise: int
    reason: str

    def to_json(self) -> dict[str, object]:
        return {"settlement_id": self.settlement_id,
                "amount_paise": self.amount_paise, "reason": self.reason}


def post(finding: Finding, settlement: Settlement, judgement: Judgement,
         orders: dict[str, Order], rules: RuleSet = DEFAULT,
         provenance: str = "") -> "JournalEntry | Refusal":
    """The entry this finding implies, or a stated reason there is none.

    Gross and the combined charge come from the proof, as the solver
    established them. The split between the gateway's fee and the tax on it
    comes from the rule set — the same one the proof was built under — because
    the pipeline carries the two as a single number and a merchant needs them
    apart: input GST is recoverable and the fee is not, so posting the whole
    charge as expense overstates cost and loses a credit.

    The split is not an estimate. It is checked to sum back to the figure the
    proof carries, and a difference means the rule set on screen is not the one
    that produced the proof — which is a provenance failure worth stopping for,
    not a rounding difference worth absorbing.

    Returns a `Refusal` rather than None so the absence of an entry carries its
    reason. A queue of unexplained gaps is how a reconciliation becomes an
    argument.
    """
    if finding.verdict is not Verdict.PROVEN:
        return Refusal(settlement.settlement_id, settlement.net_paise,
                       f"verdict is {finding.verdict.value} — the candidate "
                       f"order sets discharge receivables against different "
                       f"customers, and there is no partially correct entry")
    if not getattr(finding, "postable", False):
        return Refusal(settlement.settlement_id, settlement.net_paise,
                       why_not_postable(finding))

    # CORE-004. `postable` answers four questions about the SEARCH -- which
    # space, which universe, which solver, whose members -- and none about the
    # ARITHMETIC. So this gate was open: a Finding assembled outside
    # `pipeline.run` carried an unverified proof straight to the books, and the
    # README's claim that "a proof is accepted only if the kernel accepts it"
    # was false precisely here, because the ledger never asked. Measured before
    # the fix: 245 proofs the kernel rejects, 131 of them posted.
    #
    # The pipeline already filters through `check`, so on a clean run this
    # refuses nothing. That is the point -- a boundary that only holds because
    # every caller remembers to hold it is not a boundary.
    if not check(finding.proofs[0], settlement, orders):
        return Refusal(settlement.settlement_id, settlement.net_paise,
                       "the independent kernel does not accept this proof; it "
                       "was not re-derivable from the source records")
    if judgement.decision is not Decision.AUTO_POST:
        return Refusal(settlement.settlement_id, settlement.net_paise,
                       (judgement.reasons or ("policy withheld it",))[-1])

    p = finding.proofs[0]
    n = len(p.order_ids)
    plural = "" if n == 1 else "s"

    fee_only = tax_only = 0
    for oid in p.order_ids:
        o = orders[oid]
        f_ = rules.fee_paise(o.gross_paise, o.method)
        fee_only += f_
        tax_only += rules.tax_paise(f_)
    if fee_only + tax_only != p.fee_paise:
        raise Unbalanced(
            f"{settlement.settlement_id}: the rule set splits the charge into "
            f"{fee_only} fee + {tax_only} tax = {fee_only + tax_only}, but the "
            f"proof carries {p.fee_paise}. These rules did not produce this "
            f"proof.")

    # The credit that actually arrived, not the modelled net. Where they differ
    # it is by the proof's residual — at most one paise per order, from two
    # independent half-up roundings — and that difference is a fee-model
    # artefact, so it belongs on the fee line rather than left to unbalance the
    # entry or silently adjust what the bank is said to have paid.
    drift = settlement.net_paise - p.net_paise
    fee = fee_only - drift

    lines = [
        Line(BANK, debit_paise=settlement.net_paise, memo=f"UTR {settlement.utr}"),
        Line(FEES, debit_paise=fee,
             memo=f"gateway fees on {n} order{plural}"
                  + (f" ({drift:+d} paise rounding)" if drift else "")),
        Line(GST, debit_paise=tax_only, memo="tax on fees, recoverable"),
        Line(RECEIVABLES, credit_paise=p.gross_paise + p.adjustment_paise,
             memo=f"{n} order{plural} discharged"
                  + (f", {p.adjustment_paise:+d} paise adjustment"
                     if p.adjustment_paise else "")),
    ]

    return JournalEntry(
        settlement_id=settlement.settlement_id,
        value_date=str(settlement.settled_on),
        utr=settlement.utr,
        lines=tuple(lines),
        order_ids=tuple(p.order_ids),
        provenance=provenance,
        proof_residual_paise=p.residual_paise,
        proof_tolerance_paise=p.tolerance_paise,
    )


@dataclass
class Journal:
    entries: list[JournalEntry] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)

    @property
    def posted_paise(self) -> int:
        return sum(e.lines[0].debit_paise for e in self.entries)

    @property
    def refused_paise(self) -> int:
        return sum(r.amount_paise for r in self.refusals)

    def balances(self) -> bool:
        """Every entry balances, and so does the journal as a whole."""
        d = sum(x.debit_paise for e in self.entries for x in e.lines)
        c = sum(x.credit_paise for e in self.entries for x in e.lines)
        return d == c
