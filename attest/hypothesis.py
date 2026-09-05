"""L5 — the hypothesis loop. §22–23.

The engine's failure mode is not error, it is abstention: 197 of 250 settlements
come back AMBIGUOUS because several disjoint subsets satisfy the amount
constraint *exactly*. More search cannot fix that. Arithmetic has said everything
it can say, and the tie has to be broken by evidence of a different kind.

That evidence is semantic — a bank narration, a counterparty name, a capture
batch — and it lives in fields no solver can reason about. Which is precisely the
work a model is good at, and precisely the work it must not be allowed to
conclude from.

So the division is strict and it is the whole architecture:

    the solver ENUMERATES              — every subset that satisfies the amount
                                          constraint over the FULL candidate pool
    the model proposes an ANCHOR       — "these orders belong together, because
                                          the narration names this batch"
    the anchor SELECTS among them      — and only among them
    the kernel VERIFIES the survivor   — recomputed from source records

The order matters more than anything else in this file, and the first version got
it wrong. See FAILURES.md D8: anchoring *before* the search — subtracting the
anchor and solving the remainder — resolved 92 abstentions and got 32 of them
wrong, precision 0.652. The mechanism is subtle and worth stating plainly:

    uniqueness inside a restricted space is not uniqueness.

Restricting the search to subsets containing the anchor changes which problem is
being solved. If the true explanation does not contain the anchor, the restricted
problem can have exactly one solution — a wrong one — and it arrives wearing
every mark of a proof: it balances, it clears the bound, the kernel accepts it,
because it IS internally consistent. It is simply not true.

So an anchor may only ever break a tie between explanations arithmetic has
ALREADY found valid over the whole pool. It can never create uniqueness, only
recognise it. That constraint costs recall and it is not negotiable.

**The model never sees an amount.** `Evidence` carries narration, names, dates and
identifiers; the numbers are withheld deliberately rather than merely unused. A
proposer that could see the target could pattern-match its way to a plausible sum,
and a plausible sum is exactly what this project exists to refuse.

**A refutation is not "no".** It carries a structured residual — how much is
unexplained, which constraint failed, which cited orders do not exist — so the
next proposal is informed rather than a retry. That makes this
counterexample-guided refinement, not a chatbot in a loop.

An anchor is a *restriction* on the search, never an addition to the answer: the
narrowed problem is still solved exactly, and if the narrowed problem is still
ambiguous the engine still abstains. The model can only ever make the engine look
harder in a smaller place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from attest.model import BankCredit, Order, Settlement, tolerance_paise
from attest.verdict import Finding, Proof, Verdict, check


@dataclass(frozen=True)
class Evidence:
    """What a proposer is allowed to see.

    Contains no amount, and that is the point. The omission is load-bearing, not
    an oversight: give a proposer the target and it will find something that adds
    up, which is the failure this whole engine is built to prevent.
    """

    settlement_id: str
    value_date: date
    utr: str | None
    narration: str
    candidates: tuple[tuple[str, str, date], ...]
    """(order_id, customer_name, captured_on) — never a net or a gross."""

    residual_hint: int | None = None
    """Set only on a refinement round. Its magnitude is a fact about the SEARCH,
    not about any candidate, so it cannot leak an individual order's value."""

    rejected: tuple[str, ...] = ()

    tried: tuple[tuple[str, ...], ...] = ()
    """Anchors already proposed and refuted, so a proposer does not offer the
    same one again.

    Without this the loop had no feedback channel for a *uniqueness* refutation
    — that refutation names no rejected orders, because the anchor was wrong by
    being contained in every explanation rather than by containing a bad one —
    so `rejected` stayed empty, the proposer saw an unchanged Evidence and
    returned the identical hypothesis, and all three rounds went on refuting one
    idea. The measurement in D8 was taken under that loop."""


@dataclass(frozen=True)
class Hypothesis:
    order_ids: tuple[str, ...]
    lens: str
    reasoning: str
    admits_missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Refutation:
    """Why a hypothesis died, in a form the next round can act on."""

    lens: str
    constraint: str
    unexplained_paise: int
    rejected: tuple[str, ...]
    hint: str


@dataclass
class Trail:
    """Every proposal, every refutation, in order.

    `AI proposed X → verifier REJECTED, residual ₹1,299 → AI proposed Y →
    verifier ACCEPTED` must be reconstructible after the fact, because an
    engine that lets a model influence a posting owes an account of how.
    """

    events: list[dict[str, object]] = field(default_factory=list)

    def say(self, actor: str, act: str, detail: str, **kw: object) -> None:
        self.events.append({"actor": actor, "act": act, "detail": detail, **kw})


Proposer = Callable[[Evidence], list[Hypothesis]]

#: OFF by default. D8 disabled it on a hand-taken 0.521; the re-measurement in
#: `attest/eval/anchoring.py` came back at 27 correct of 63 resolved — worse than
#: a coin flip, so the decision held and the earlier figure is superseded. The
#: current number is read from `benchmark/anchoring.json`, never written here.
#: The cause is unchanged: the generator emits no order-level reference for an
#: anchor to key on,
#: so every anchor is a guess and selecting among four explanations with a guess
#: lands where guesses land. Enabling it would take the engine from 5 false
#: proofs per 1,250 to roughly 40. See FAILURES.md D8.
ENABLED_BY_DEFAULT = False

#: Refinement rounds before the engine gives up and abstains. Small on purpose:
#: if three informed attempts cannot anchor the settlement, the evidence is not
#: there, and more rounds would only be the model guessing more elaborately.
MAX_ROUNDS = 3


# --------------------------------------------------------------------------
# Falsification
# --------------------------------------------------------------------------


def falsify(h: Hypothesis, settlement: Settlement, orders: dict[str, Order],
            competing: tuple[Proof, ...]) -> tuple[Proof | None, Refutation | None]:
    """Select among explanations arithmetic already validated. Never beyond them.

    `competing` is the set the solver found over the FULL candidate pool. The
    anchor is admitted only when it is a subset of exactly one of them: then the
    tie was broken by evidence, and uniqueness was still established by
    arithmetic. Every other outcome is a refutation.
    """
    ghosts = tuple(o for o in h.order_ids if o not in orders)
    if ghosts:
        return None, Refutation(h.lens, "existence", settlement.net_paise, ghosts,
                                f"{len(ghosts)} cited order(s) do not exist")

    anchor = set(h.order_ids)
    consistent = [p for p in competing if anchor <= set(p.order_ids)]

    if not consistent:
        return None, Refutation(
            h.lens, "consistency", 0, tuple(sorted(anchor)),
            f"no valid explanation contains this anchor; all {len(competing)} "
            f"exclude at least one of its orders")

    if len(consistent) > 1:
        return None, Refutation(
            h.lens, "uniqueness", 0, (),
            f"{len(consistent)} of {len(competing)} valid explanations contain "
            f"this anchor; it does not distinguish between them")

    p = consistent[0]
    if not check(p, settlement, orders):
        return None, Refutation(h.lens, "kernel", p.residual_paise, (),
                                "selected explanation rejected by the kernel")
    return p, None


def _proof(s: Settlement, members: list[Order]) -> Proof:
    gross = sum(o.gross_paise for o in members)
    net = sum(o.net for o in members)
    return Proof(
        settlement_id=s.settlement_id,
        order_ids=tuple(o.order_id for o in members),
        gross_paise=gross, fee_paise=gross - net, tax_paise=0,
        adjustment_paise=0, net_paise=net,
        residual_paise=s.net_paise - net,
        tolerance_paise=tolerance_paise(len(members)),
        constraints={"amount": True, "window": True, "uniqueness": True,
                     "anchored": True},
    )


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def investigate(finding: Finding, settlement: Settlement, credit: BankCredit,
                pool: list[Order], propose: Proposer,
                max_rounds: int = MAX_ROUNDS) -> tuple[Finding, Trail]:
    """Try to resolve an abstention with semantic evidence.

    Only ever called on AMBIGUOUS: a PROVEN settlement needs no help and a
    CONTRADICTED one is missing records, which no amount of reading narration
    will conjure. Returns the original finding unchanged when the evidence does
    not settle it — abstention is the correct outcome and this loop is not
    permitted to talk the engine out of it.
    """
    trail = Trail()
    if finding.verdict is not Verdict.AMBIGUOUS:
        trail.say("engine", "skip", f"verdict is {finding.verdict.value}")
        return finding, trail

    orders = {o.order_id: o for o in pool}
    ev = Evidence(
        settlement_id=settlement.settlement_id,
        value_date=settlement.settled_on, utr=settlement.utr,
        narration=credit.narration,
        candidates=tuple((o.order_id, o.customer_name, o.captured_on) for o in pool),
    )

    for rnd in range(1, max_rounds + 1):
        hypotheses = propose(ev)
        if not hypotheses:
            trail.say("model", "exhausted", f"round {rnd}: no further hypothesis")
            break

        worst: Refutation | None = None
        fresh = False
        for h in hypotheses:
            if tuple(h.order_ids) in ev.tried:
                continue
            fresh = True
            trail.say("model", "propose",
                      f"{len(h.order_ids)} orders — {h.reasoning}", lens=h.lens)
            proof, refutation = falsify(h, settlement, orders, finding.proofs)

            if proof is not None:
                trail.say("solver", "accept",
                          f"anchor is contained in exactly 1 of "
                          f"{len(finding.proofs)} valid explanations; "
                          f"residual {proof.residual_paise} paise within "
                          f"±{proof.tolerance_paise}", lens=h.lens)
                trail.say("kernel", "verify", "re-derived from source records")
                return Finding(settlement.settlement_id, Verdict.PROVEN, (proof,),
                               exhaustive=finding.exhaustive,
                               layer=finding.layer + f"+anchor/{h.lens}"), trail

            assert refutation is not None
            trail.say("solver", "refute",
                      f"{refutation.constraint}: {refutation.hint}",
                      lens=h.lens, unexplained_paise=refutation.unexplained_paise)
            worst = refutation

        if not fresh:
            trail.say("model", "exhausted",
                      f"round {rnd}: every hypothesis has already been refuted")
            break
        if worst is None:
            break
        ev = Evidence(
            settlement_id=ev.settlement_id, value_date=ev.value_date, utr=ev.utr,
            narration=ev.narration, candidates=ev.candidates,
            residual_hint=worst.unexplained_paise,
            rejected=ev.rejected + worst.rejected,
            tried=ev.tried + tuple(tuple(h.order_ids) for h in hypotheses),
        )

    trail.say("engine", "abstain",
              "no anchor resolved the ambiguity; the verdict stands")
    return finding, trail


# --------------------------------------------------------------------------
# Offline proposer
# --------------------------------------------------------------------------


def batch_proposer(ev: Evidence) -> list[Hypothesis]:
    """A deterministic stand-in for a model, using only what a model would see.

    Real settlements are batches: the orders in one were captured together, often
    within hours. So the largest same-day cluster is a defensible anchor, and it
    is defensible for a reason a human would give — not because it adds up, which
    this function has no way of knowing.

    Its purpose is that the loop can be tested and benchmarked with no network,
    no key and no non-determinism. A language model replaces it by implementing
    the same signature; nothing downstream changes, because nothing downstream
    trusts it.
    """
    if ev.rejected:
        return []
    by_day: dict[date, list[str]] = {}
    for oid, _name, day in ev.candidates:
        by_day.setdefault(day, []).append(oid)
    if not by_day:
        return []

    # Walk every day, densest first, and skip anchors already refuted. Taking
    # only the top two meant a refuted pair left nothing to offer on the next
    # round, which is how the loop ended up repeating itself.
    days = sorted(by_day, key=lambda d: (-len(by_day[d]), d))
    out: list[Hypothesis] = []
    for day in days:
        ids = sorted(by_day[day])
        if len(ids) < 2:
            continue
        anchor = tuple(ids[:3])
        if anchor in ev.tried:
            continue
        if len(out) >= 2:
            break
        out.append(Hypothesis(
            order_ids=anchor,
            lens="capture-batch",
            reasoning=f"three orders captured together on {day}, the densest "
                      f"batch in the window ({len(ids)} orders)",
            admits_missing=("no reference links these to the credit",),
        ))
    return out
