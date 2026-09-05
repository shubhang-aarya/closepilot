# CORE-004 — the ledger never asked the kernel

**Status:** FOUND → REPRODUCED → FIXED → REGRESSION TESTED → ADVERSARIAL ATTACK ADDED.

**Found by:** the same external red-team pass that produced CORE-003, on the
follow-up question: *CORE-003 closed the kernel — did anything route around it?*

---

## The defect

The README's architectural claim is one sentence:

> A proof is accepted only if the kernel accepts it.

At the ledger boundary that was false, because the ledger did not ask.

`ledger.post` gated on `Finding.postable`. `postable` answers four questions,
and CORE-001 and CORE-002 are both about getting those four right:

1. What search space was proved?
2. Which candidate universe was considered?
3. Which solver produced it?
4. Does the proof belong to that universe?

Every one of those is a question about **the search**. None of them is a
question about **the arithmetic**. So a `Finding` assembled anywhere other than
`pipeline.run` carried an unverified proof straight to the books — and
`pipeline.run` is the only caller that filters through `check` before building
the Finding:

```python
proofs = tuple(
    p for p in (_proof(s, [...]) for sol in sols)
    if check(p, s, by_id)          # <- the only reason the kernel was load-bearing
)
```

The kernel was doing its job by convention, not by construction. A boundary
that holds only because every caller remembers to hold it is not a boundary.

## The reproduction

Forge the arithmetic and leave the search provenance immaculate: real orders
from the real pool, a recorded `SearchSpace` with a universe and reductions, a
named layer. `postable` answers yes to all four of its questions and never
notices the sum is wrong.

Swept over seed 555001, subsets of size 2, one per settlement:

```
proofs the kernel rejects         : 245
of those, entries the LEDGER made : 131
```

131 balanced journal entries, against the wrong customers, from proofs the
independent verifier had already rejected. The entries balance because
double-entry balance is a property of the *lines*, not of the explanation.

## Why this is the same shape as CORE-001

CORE-001 was `postable` failing open when `space` was absent — a gate that
returned True because the evidence it would have judged was missing.

CORE-004 is `post` failing open when the *arithmetic* is wrong — a gate that
returns True because it only ever looked at the search. Same failure, one
layer up, and the same lesson: a gate has to be told what it is guarding
against, and "everything upstream already checked" is not a guard.

## The fix

Two lines in `attest/ledger.py::post`, which already receives `orders` for the
fee/tax split:

```python
if not check(finding.proofs[0], settlement, orders):
    return Refusal(settlement.settlement_id, settlement.net_paise,
                   "the independent kernel does not accept this proof; it "
                   "was not re-derivable from the source records")
```

**The kernel itself is unchanged.** `attest/verdict.py` is byte-identical to its
post-CORE-003 state. This report is about a caller that failed to consult it.

## What changed, measured

```
                                        before    after
kernel-rejected proofs reaching ledger     131        0
honest proofs still posting                 17       17   (seed 555001, Rs 250)
adversarial suite                        34/34    35/35
```

On a clean run this refuses nothing, and that is the point. It costs one call
per posting and removes an entire class of caller mistake.

## The regression

`tests/test_invariants.py::test_the_ledger_refuses_a_proof_the_kernel_rejects`
constructs exactly the shape above — sound provenance, wrong arithmetic — and
asserts `postable is True` while the ledger returns a `Refusal`. It fails
against the old behaviour before it passes against the new, which is the point
of asserting on `postable` as well: the test would still pass if someone
"fixed" this by tightening `postable`, and that would be a different fix to a
different defect.

Adversarial attack 35, `LEDGER / forged / a proof the kernel rejects, pushed
straight at the ledger`, carries the same case into the suite that runs on every
build. Its docstring records that it was found by a red-team review and not by
this suite, because a suite that quietly absorbs the attacks it missed teaches
nobody anything.
