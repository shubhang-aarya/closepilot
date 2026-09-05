"""Search-space integrity. §12, §28.

D8 cost 32 wrong answers out of 92 and bought one sentence:

    a correct verifier can verify the wrong question.

Every one of those 32 balanced exactly, cleared its rounding bound, and was
accepted by the independent kernel. The arithmetic was right. What was wrong was
that the search had been narrowed before it ran, so uniqueness was established
over a space that did not contain the truth. The kernel could not catch it —
the kernel checks arithmetic, and the arithmetic was correct.

So a solver result is not a claim about the world until you also know what was
excluded before solving, and on what authority. This module makes that explicit
and carries it onto the proof.

**Deterministic vs heuristic is the whole distinction.** An order whose net
exceeds the credit cannot possibly belong to it — dropping it removes nothing
true, so uniqueness survives. A date window is a different animal: T+2 is a
convention, real settlements slip, and an order pruned by the ladder might have
belonged. Uniqueness after that reduction is a fact about the *window*, not about
the portfolio.

The engine is therefore only ever permitted to say one of two things:

    unique                          — every exclusion was deterministic
    unique within the candidate     — at least one was not
    space, which is heuristic

Never the first when it has only earned the second. That is the signature
decision of this product and it is the direct descendant of D8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from attest.money import rupees


class Integrity(str, Enum):
    VALIDATED = "validated"
    """Every exclusion was deterministic. Uniqueness found here is global."""

    HEURISTIC = "heuristic"
    """At least one exclusion rested on a convention that can be wrong.
    Uniqueness found here is local to the candidate space and must be reported
    that way."""

    COMPROMISED = "compromised"
    """A reduction is known to have removed something that belonged. Nothing
    found here may post; the space is not merely unproven, it is wrong."""


class Scope(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


@dataclass(frozen=True)
class Reduction:
    """One narrowing step, and the authority it rests on."""

    name: str
    removed: int
    deterministic: bool
    justification: str

    @property
    def safe(self) -> bool:
        return self.deterministic


@dataclass
class SearchSpace:
    """What the solver was allowed to look at, and what it never saw."""

    universe: int
    reductions: list[Reduction] = field(default_factory=list)
    known_loss: int = 0
    """Candidates a reduction is known to have wrongly removed. Non-zero only
    when the engine can detect it — see `note_known_loss`."""

    members: frozenset[str] = frozenset()
    """WHICH candidates survived, not merely how many.

    CORE-002. Recording only a count let a forged proof cite orders that were
    never in the pool and satisfy the postability gate on cardinality alone —
    two ids against five candidates passes `len(order_ids) <= candidates` while
    belonging to no search that happened. A count is a fact about a search; a
    membership set is the search."""

    @property
    def candidates(self) -> int:
        return max(self.universe - sum(r.removed for r in self.reductions), 0)

    @property
    def integrity(self) -> Integrity:
        if self.known_loss:
            return Integrity.COMPROMISED
        return (Integrity.VALIDATED if all(r.deterministic for r in self.reductions)
                else Integrity.HEURISTIC)

    @property
    def scope(self) -> Scope:
        return Scope.GLOBAL if self.integrity is Integrity.VALIDATED else Scope.LOCAL

    @property
    def heuristic_steps(self) -> list[Reduction]:
        return [r for r in self.reductions if not r.deterministic]

    def uniqueness_claim(self) -> str:
        """Exactly what the engine has earned the right to say."""
        if self.integrity is Integrity.COMPROMISED:
            return "uniqueness not provable — a reduction removed a valid candidate"
        if self.integrity is Integrity.VALIDATED:
            return "unique — every exclusion was deterministic"
        why = ", ".join(r.name for r in self.heuristic_steps)
        return (f"unique within the validated candidate space; the space itself "
                f"rests on {why}, which is a convention rather than a proof")

    def note_known_loss(self, n: int) -> None:
        self.known_loss += n

    def to_json(self) -> dict[str, object]:
        return {
            "universe": self.universe,
            "candidates": self.candidates,
            "integrity": self.integrity.value,
            "scope": self.scope.value,
            "claim": self.uniqueness_claim(),
            "reductions": [{"name": r.name, "removed": r.removed,
                            "deterministic": r.deterministic,
                            "justification": r.justification} for r in self.reductions],
        }


# --------------------------------------------------------------------------
# The reductions the engine actually performs
# --------------------------------------------------------------------------


def amount_ceiling(removed: int, credit_paise: int) -> Reduction:
    """Deterministic: an order larger than the whole credit cannot be inside it.

    No assumption about calendars, batching or gateway behaviour. Arithmetic
    alone, so nothing true is lost and uniqueness survives.
    """
    return Reduction(
        "amount ceiling", removed, True,
        f"net exceeds the credit of {rupees(credit_paise)}, so the order cannot "
        f"be a member of any subset summing to it")


def date_window(removed: int, rung: int, days: tuple[int, ...]) -> Reduction:
    """Heuristic, and the honest label matters more than the saving.

    T+2 is a settlement convention. Holidays, batch delays and manual
    interventions all break it, and D3 recorded a real case where the true
    explanation was pruned by exactly this step and a *different* subset then
    matched uniquely. Every proof standing on this reduction is local.
    """
    return Reduction(
        f"settlement calendar (rung {rung})", removed, False,
        f"orders outside the T+{'/'.join(map(str, days))} capture window for "
        f"this value date; the window is a convention, not a guarantee")


def consumption(removed: int) -> Reduction:
    """Conditionally deterministic, therefore reported as heuristic.

    An order belongs to exactly one settlement, so removing orders already
    proven elsewhere is sound *if those proofs are sound*. D4 showed how badly
    that conditional can fail: one false proof consumed orders it did not own
    and manufactured eight more. A step whose safety depends on earlier answers
    is not deterministic, and calling it so would repeat the D8 mistake in a
    different place.
    """
    return Reduction(
        "already claimed", removed, False,
        "orders consumed by settlements proven earlier in this run; sound only "
        "if those proofs are, which is exactly what D4 showed can fail")


def why_not_postable(finding: object) -> str:
    """Which of `postable`'s conditions this finding fails, in its own words.

    `Finding.postable` is a single boolean guarding six distinct conditions, and
    this refusal used to report every one of them as "the search space is
    compromised". A refusal that names the wrong cause is worse than a vague
    one: it sends whoever reads it to inspect a search space that is fine, while
    the actual defect — a proof citing an order that belongs to no candidate
    universe — goes unexamined. Found by the adversarial pass.

    This does not decide anything. `postable` decides; this explains. The order
    below mirrors `Finding.postable` exactly, and
    `test_every_unpostable_reason_is_named_not_guessed` fails if a condition is
    added there without a sentence here.
    """
    sp = getattr(finding, "space", None)
    if not isinstance(sp, SearchSpace):
        return ("no search space was recorded, so there is nothing to say which "
                "candidates were considered — a proof that omits the evidence it "
                "would be judged on cannot be posted on the strength of it")
    if sp.universe <= 0 or not sp.reductions:
        return ("the search space records no candidate universe, so the "
                "uniqueness it claims is uniqueness among nothing")
    if not finding.layer:
        return ("the proof names no solver, so there is no way to re-derive it "
                "or to say which layer's assumptions it inherited")
    if not finding.proofs or not sp.members:
        return ("the search space records no members, so membership of the "
                "cited orders cannot be established — only their count, and "
                "counting is not belonging")
    foreign = sorted(set(finding.proofs[0].order_ids) - sp.members)
    if foreign:
        return (f"the proof cites {len(foreign)} order(s) that are not in the "
                f"candidate universe it was proved against: "
                f"{', '.join(foreign[:4])}. An explanation made of orders the "
                f"search never considered is not an explanation of this credit")
    if sp.integrity is Integrity.COMPROMISED:
        return ("the search space is compromised; uniqueness inside a space "
                "that excluded the truth is not uniqueness")
    return ("the finding is not postable and no condition explains why, which "
            "means postable() gained a condition this refusal has not been "
            "taught to state")
