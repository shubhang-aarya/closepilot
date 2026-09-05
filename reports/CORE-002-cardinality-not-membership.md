# CORE-002 — condition 4 checked cardinality, not membership

**Status:** FOUND → REPRODUCED → FIXED → REGRESSION TESTED.

**Found by:** a single directed attack against the CORE-001 fix, asking whether
condition 4 established *actual membership* or merely *how many*.

---

## The defect

The CORE-001 fix added four conditions to `Finding.postable`. Condition 4 read:

```python
if not self.proofs or len(self.proofs[0].order_ids) > sp.candidates:
    return False
```

`SearchSpace` recorded `universe`, `reductions` and `known_loss` — all counts.
It never recorded *which* orders survived. So condition 4 could only compare
sizes, and a proof citing two invented order ids against a five-candidate space
satisfies `2 <= 5` while belonging to no search that ever happened.

Every other condition was satisfiable by construction: a real `SearchSpace`, a
positive universe, a recorded reduction, a non-empty solver layer.

## Reproduction

```python
sp = SearchSpace(universe=5)                     # candidates [A, B, C, D, E]
sp.reductions.append(Reduction("test", 0, True, "nothing removed"))

forged = Finding("s1", Verdict.PROVEN,
                 (Proof("s1", ("X", "Y"), 1000, 0, 0, 0, 1000, 0, 2),),
                 space=sp, layer="L3-dp/r0")

forged.postable   # True  — X and Y were never candidates
```

## The fix

Three files, one idea: record the members, then check against them.

**`attest/searchspace.py`** — a new field. Not protected core.

```python
members: frozenset[str] = frozenset()
```

**`attest/blocking.py`** — populated at the single construction site, from the
pool itself. Protected core.

```python
space = SearchSpace(universe=universe,
                    members=frozenset(o.order_id for o in pool))
```

**`attest/verdict.py`** — condition 4 becomes membership, and an unrecorded
membership set is no record of a search. Protected core.

```python
if not self.proofs or not sp.members:
    return False
if not set(self.proofs[0].order_ids) <= sp.members:
    return False
```

The four-question invariant from CORE-001 is preserved; only question 4's answer
became honest. A count is a fact *about* a search. A membership set *is* the
search.

## Measured blast radius

```
                     before    after
proven                   52       52
postable                 52       52
AUTO_POST                 1        1
REVIEW                  249      249
BLOCK                     0        0
false proof rate      0.0080   0.0080
proof precision       0.9524   0.9524
exact set recovery    0.1600   0.1600
value accounted for   0.6670   0.6670
```

All six gates at +0.0000. 187 tests pass.

Separately verified: **0 of 52 proven proofs cite an order outside their own
recorded membership.** Failing closed on membership is only safe if blocking
records it, and it does — at the one construction site, from the pool.

## Regression tests

| Test | Establishes |
|---|---|
| `test_core002_cited_orders_must_belong_to_the_candidate_universe` | the attack itself, and it asserts the cardinality check is satisfied so the test stays meaningful |
| `test_core002_a_single_foreign_order_is_enough_to_refuse` | membership is not a majority vote |
| `test_core002_a_space_recording_no_members_cannot_post` | a count without members is not a record |
| `test_core002_every_engine_proof_sits_inside_its_recorded_members` | blocking populates what the gate now demands |

## What this says about CORE-001

The CORE-001 fix was correct in structure and incomplete in one condition. That
is a normal outcome of fixing a security boundary — the shape was right, and the
attack that found the gap was the obvious next question to ask. It was asked
deliberately rather than discovered later, which is the part worth keeping.
