# CORE-001 — `Finding.postable` fails open when no search space is recorded

**Status:** FOUND → REPRODUCED → **FIXED** → REGRESSION TESTED.

Reported first without a patch: `attest/verdict.py` is protected by
`.githooks/pre-commit` and the guard says report with a reproduction rather
than edit. The fix was subsequently authorised as a human-owned change and
committed with `ATTEST_CORE=1`. The original report below is unchanged — the
reproduction and the pre-fix behaviour are the record.

**Found by:** hardening phase 8.13, writing the AI-boundary check as an attack
rather than as an assertion.

---

## The defect

```python
# attest/verdict.py, Finding.postable
if self.verdict is not Verdict.PROVEN:
    return False
from attest.searchspace import Integrity, SearchSpace
if isinstance(self.space, SearchSpace):
    return self.space.integrity is not Integrity.COMPROMISED
return True          # <-- a finding with NO search space is postable
```

A `Finding` carrying no search-space record at all returns `postable = True`.
The property exists to encode D8 — *uniqueness inside a space that excluded the
truth is not uniqueness* — and it currently trusts a proof whose candidate
universe is unrecorded. It fails **open** where §8.11 of the hardening brief
requires that "a proof without search-space provenance is incomplete".

## Reproduction

```python
from attest.verdict import Finding, Proof, Verdict

naked = Finding("s1", Verdict.PROVEN,
                (Proof("s1", ("o1",), 1, 0, 0, 0, 1, 0, 1),))
assert naked.space is None
assert naked.postable is True        # currently passes; should not
```

Reached through the ledger, the forged proof is refused — but by
`Unbalanced` in `ledger.post`, i.e. by arithmetic rather than by the integrity
gate:

```python
from attest.ledger import post
out = post(naked, settlement, permissive_judgement, orders)
# raises Unbalanced, rather than returning a Refusal citing the search space
```

Defence in depth caught it. The gate that was supposed to did not.

## Blast radius

**None observed in the engine.** `attest/pipeline.py` attaches a `SearchSpace`
to every finding it produces, so no run reaches this branch:

```
250-settlement run: 52 postable before, 52 after a local fix
all six regression gates: +0.0000 on every metric
```

The exposure is to any `Finding` assembled outside the pipeline — a test
fixture, an adapter, a future caller, or an attacker who omits the field
precisely because it is the field being judged.

## Suggested fix

Invert the default so the absent case is disqualifying:

```python
if not isinstance(self.space, SearchSpace):
    return False
return self.space.integrity is not Integrity.COMPROMISED
```

## Suggested tests to land with it

```python
def test_a_proof_without_search_space_provenance_cannot_post():
    naked = Finding("s1", Verdict.PROVEN,
                    (Proof("s1", ("o1",), 1, 0, 0, 0, 1, 0, 1),))
    assert not naked.postable

def test_the_engine_still_attaches_a_search_space_to_every_proof():
    r = api.execute(250, 20260821)
    for f in r.findings:
        if f.verdict is Verdict.PROVEN:
            assert isinstance(f.space, SearchSpace) and f.space.reductions
```

The second matters as much as the first: failing closed is only safe if the
engine actually records what it is being asked for. It does, verified on the
250-settlement panel.


---

# Resolution

## The invariant, as landed

A PROVEN finding may only become postable if the system can answer four
questions about it. Each condition in the fix is one question, and the property
fails closed on any of them:

| # | Question | Condition |
|---|---|---|
| 1 | What search space was proved? | `isinstance(space, SearchSpace)` |
| 2 | Which candidate universe was considered? | `universe > 0` and at least one recorded reduction |
| 3 | Which solver produced the proof? | `layer` is non-empty |
| 4 | Does the proof belong to that universe? | `len(order_ids) <= space.candidates` |

Then, as before, a COMPROMISED space is disqualifying.

Condition 4 is the one that makes the check unfakeable by construction: a proof
citing more orders than the space ever contained cannot have come out of it, so
satisfying the gate by attaching *any* SearchSpace does not work.

## Pre-fix behaviour

```
forged = Finding("setl_forged", Verdict.PROVEN,
                 (Proof("setl_forged", ("ord_x",), 1000, 0, 0, 0, 1000, 0, 1),))
forged.space     -> None
forged.postable  -> True          # the defect
ledger.post(...) -> raises Unbalanced   # caught by arithmetic, not by the gate
```

## Post-fix behaviour

```
forged.postable  -> False
ledger.post(...) -> Refusal("the search space is compromised; uniqueness inside
                             a space that excluded the truth is not uniqueness")
```

The refusal now names the search space rather than the sum.

## Measured blast radius

Verified against every legitimate proof on the 250-settlement panel *before*
the change, so the fix was known not to close on the truth:

```
proven findings                          52
failing condition 1 (no space)            0
failing condition 2 (no universe/reds)    0
failing condition 3 (no layer)            0
failing condition 4 (proof > candidates)  0
```

After:

```
                     before    after
proven                   52       52
postable                 52       52
AUTO_POST                 1        1
REVIEW                  249      249
BLOCK                     0        0
wrongly auto-posted      ₹0       ₹0
false proof rate      0.0080   0.0080
proof precision       0.9524   0.9524
exact set recovery    0.1600   0.1600
value accounted for   0.6670   0.6670
```

All six gates at +0.0000. 183 tests pass.

## What this does and does not say

The reproduced exploit produced **no financial impact in the current engine
evaluation**, because the downstream ledger balance check rejected it. The
integrity boundary was nevertheless incorrect: the gate that exists to encode
D8 trusted a proof whose candidate universe was unrecorded, and it was defence
in depth rather than the gate that stopped the attack.

That 52 findings are postable either way does not make the defect unimportant.
The objective was the correctness of the invariant, not the preservation of a
benchmark number.

## Regression tests

`tests/test_invariants.py`

| Test | Removes |
|---|---|
| `test_core001_a_proof_without_search_space_provenance_cannot_post` | the space entirely (the original exploit) |
| `test_core001_a_legitimate_proof_still_posts` | nothing — the control |
| `test_core001_a_fabricated_space_that_is_not_a_record_cannot_post` | a real record, keeping a plausible-looking value |
| `test_core001_a_space_recording_no_universe_cannot_post` | the universe and the reductions |
| `test_core001_a_proof_with_no_solver_provenance_cannot_post` | the solver identity |
| `test_core001_a_proof_larger_than_its_candidate_universe_cannot_post` | the correspondence between proof and space |
| `test_core001_a_compromised_space_still_cannot_post` | nothing — D8's original condition must survive |
| `test_the_engine_still_attaches_a_search_space_to_every_proof` | nothing — failing closed is only safe if the engine records what it is judged on |

The strict `xfail` is gone. These are ordinary regression tests now.
