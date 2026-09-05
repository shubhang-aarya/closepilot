"""L4 -- constraint propagation across settlements.

D3 ended with 198 of 250 verdicts AMBIGUOUS, and the diagnosis matters: that is
not a weak solver. With a 185-order pool and paise-level tolerance, genuinely
many distinct subsets satisfy the amount constraint exactly. Arithmetic alone
cannot choose between them, and the engine is right to refuse.

So the answer is not a better search. It is **more constraints** -- and there is
one available for free that no single-settlement solver can see:

    an order belongs to exactly one settlement.

That is a global fact, and it makes settlements evidence about each other. Two
inferences follow, both exact:

**Forced membership.** If every surviving explanation for a settlement contains
order X, then X belongs to that settlement regardless of which explanation is
ultimately correct. The engine does not yet know the answer, but it already knows
that part of the answer -- and X can be struck from every other settlement's
pool. (Sudoku players know this move; the uncertainty is over the full set, never
over the intersection.)

**Forced exclusion.** Once an order is consumed, every candidate elsewhere that
cited it dies. Which can leave a settlement with exactly one survivor -- and a
settlement that was AMBIGUOUS becomes PROVEN without a single new search.

Both are deductions, not heuristics. Nothing here is scored, weighted or ranked,
so nothing here can turn an honest AMBIGUOUS into a confident guess: the
propagation only removes possibilities that were already impossible. Applied to a
fixed point, the population of settlements resolves itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from attest.verdict import Finding, Verdict


@dataclass
class Propagation:
    """What one round of deduction established."""

    forced: dict[str, str]
    """order_id -> settlement_id, for orders present in every surviving
    explanation of that settlement."""

    killed: int
    """Candidate explanations eliminated because they cited a consumed order."""

    promoted: int
    """Settlements that reached a unique explanation without further search."""

    @property
    def changed(self) -> bool:
        return bool(self.forced) or self.killed > 0


def forced_members(finding: Finding) -> frozenset[str]:
    """Orders common to every surviving explanation.

    For PROVEN this is the whole set. For AMBIGUOUS it is the part of the answer
    already determined. For CONTRADICTED it is empty -- nothing survives, so
    nothing is implied.
    """
    if not finding.proofs:
        return frozenset()
    if not finding.exhaustive:
        # The enumerator stopped at its cap, so `proofs` is a sample of the
        # explanations rather than all of them. "Present in every explanation"
        # is then a claim about the sample, and an order absent from some
        # unenumerated candidate would be forced onto the wrong settlement --
        # poisoning every other pool it was struck from. Deduce nothing.
        return frozenset()
    common = set(finding.proofs[0].order_ids)
    for p in finding.proofs[1:]:
        common &= set(p.order_ids)
    return frozenset(common)


def propagate(findings: list[Finding], claimed: dict[str, str]) -> Propagation:
    """One round of deduction over the whole population.

    `claimed` maps order_id -> settlement_id and is updated in place. A conflict
    -- two settlements forcing the same order -- is a genuine contradiction in
    the evidence and is left for the caller rather than resolved by preference.
    """
    forced: dict[str, str] = {}
    for f in findings:
        for oid in forced_members(f):
            owner = claimed.get(oid)
            if owner is None:
                forced[oid] = f.settlement_id
            elif owner != f.settlement_id:
                continue  # contested; neither claim is privileged
    claimed.update(forced)

    killed = promoted = 0
    for i, f in enumerate(findings):
        if f.verdict is not Verdict.AMBIGUOUS or not f.proofs:
            continue
        survivors = tuple(
            p for p in f.proofs
            if all(claimed.get(o, f.settlement_id) == f.settlement_id
                   for o in p.order_ids)
        )
        if len(survivors) == len(f.proofs):
            continue
        killed += len(f.proofs) - len(survivors)

        if len(survivors) == 1:
            findings[i] = Finding(f.settlement_id, Verdict.PROVEN, survivors,
                                  exhaustive=f.exhaustive, layer=f.layer + "+prop")
            promoted += 1
        elif not survivors:
            findings[i] = Finding(
                f.settlement_id, Verdict.CONTRADICTED, (),
                unsat_core=("every explanation cited an order owned by another "
                            "settlement",),
                layer=f.layer + "+prop")
        else:
            findings[i] = Finding(f.settlement_id, Verdict.AMBIGUOUS, survivors,
                                  exhaustive=f.exhaustive, layer=f.layer + "+prop")

    return Propagation(forced, killed, promoted)


def to_fixed_point(findings: list[Finding], max_rounds: int = 8) -> list[Propagation]:
    """Propagate until nothing further can be deduced.

    Monotone -- every round only removes candidates -- so it terminates. The
    bound is a guard against a bug, not an expected outcome; the round log is
    returned so a run that hits it is visible rather than silent.
    """
    claimed: dict[str, str] = {}
    for f in findings:
        if f.verdict is Verdict.PROVEN and f.proofs:
            for oid in f.proofs[0].order_ids:
                claimed[oid] = f.settlement_id

    rounds: list[Propagation] = []
    for _ in range(max_rounds):
        step = propagate(findings, claimed)
        rounds.append(step)
        if not step.changed:
            break
    return rounds
