# Algorithms

## Normalise to net, and an approximate problem becomes exact

Fees make gross amounts disagree with bank credits, so reconciliation is
conventionally treated as fuzzy matching. That framing is what caps off-the-shelf
tools around 70%.

Where the fee rule is known, fees are computable:

```
before:   credit ≈ Σ gross − unknown fees        approximate search
after:    credit = Σ net   ± rounding            exact subset-sum
```

The residual is derived, not tuned. `fee` and `tax` each round half-up
independently, so one order carries at most 1 paisa of error and a k-order subset
at most k:

```python
def tolerance_paise(subset_size: int) -> int:
    return subset_size
```

A hand-picked constant is wrong in both directions at once — too tight and large
bundles never match, too loose and small subsets collide inside the band.

Where the rule is *not* known, an order contributes a **set** of possible nets and
L3 generalises to multi-choice subset-sum. The engine degrades to a wider search
rather than to guesswork.

## Why meet-in-the-middle was abandoned

Planned; measured; discarded on day 2. MITM splits the pool and enumerates
2^(n/2) partial sums per side — viable to roughly n=45. Measured pools:

```
candidate pool   p50 = 899   p90 = 1023   max = 1097
true bundle      p50 = 6     p90 = 27     max = 40
```

2^449 per side. Not slow — impossible. The estimate of "n under 40 after
blocking" was invented rather than measured, and wrong by a factor of twenty.

## The counting DP

Amounts are integers, so reachable sums are a dense array and each order is one
shifted add: **O(n·target)** rather than O(2^(n/2)).

The counter saturates at two, and that is the interesting part:

```
0 → CONTRADICTED   no subset explains this credit
1 → PROVEN         exactly one does
2 → AMBIGUOUS      at least two do; a human sees both, the engine posts neither
```

Two bits per reachable sum is all the verdict needs, because the question is never
*how many* explanations but *is the explanation unique*. That makes the three
states a computed property of the constraint system rather than a threshold on a
score.

## The Rust kernel

The DP is three ALU ops per cell and re-reads an array the width of the credit
once per order. It is bandwidth-bound, so the only optimisation that matters is
making the array smaller.

Two bits is the floor. Rather than interleaving 2-bit lanes — which forces
lane-masking on every shift — the counter splits into two **bitplanes** of one bit
per sum, mutually exclusive, each shifting with a plain bit-shift:

```
both  = (one | many) & (s_one | s_many)     // both sides non-zero ⇒ ≥ 2
many' = many | s_many | both
one'  = (one | s_one) & !both
```

```
credit        numpy      native    speedup
₹20,000      275.6 ms   17.11 ms     16.1×
₹80,000    1,342.8 ms   25.46 ms     52.7×
footprint at ₹200,000:  4.8 MB   (one byte per sum: 19.5 MB)
```

Verified **byte-identical** over 1,777 instances and 1.32 × 10¹¹ DP cells across
all fifteen hazard families — compared with `tobytes()`, not `array_equal`,
because `solve` sums a slice and a dtype difference would change the sum without
failing an equality test.

Not a benchmark flourish. The Python envelope was ₹30,000, which silently skipped
14.8% of the portfolio — *every* large bundle — before a single subset was
examined.

## Why greedy fails, and why Hungarian is not the fix

Greedy selection lets one confident-looking explanation consume an order another
needed, and both are lost. Measured: 226 false proofs in 250.

The natural next reach is minimum-cost bipartite assignment. **That is also
wrong.** Hungarian solves a one-to-one matching. After L3 each settlement carries
several candidate *subsets*, and two conflict when they share an order — a
vocabulary Hungarian does not have. Selecting at most one candidate per settlement
with pairwise-disjoint subsets is **set packing**: NP-hard, an integer program,
not an assignment problem.

CP-SAT set packing was implemented and benchmarked against the shipping engine.
`PoolIndex.consume` already *is* set packing, solved greedily and early, so the
question was never whether to pack:

```
                 exact      WRONG    precision
greedy cascade   18.48%      0.40%     0.9807
CP-SAT strict    19.12%      0.72%     0.9714
```

+0.64 pp of matches for +0.32 pp of false proofs. Rejected. The **unsat cores**
ship: infeasibility has to be asked for with one assumption literal per
settlement, and what comes back names which settlements cannot all be explained
and which orders they contest.

## Postability requires search-space provenance (CORE-001)

A PROVEN verdict is not sufficient to post. The finding must also be able to
answer what search space was proved, which candidate universe was considered,
which solver produced the proof, and whether the proof belongs to that universe
— and it fails closed on any of them.

`Finding.postable` previously returned `True` when no search space was recorded,
so a proof was postable *because* it omitted the evidence it would have been
judged on. Fixed; measured impact on legitimate proofs: none (52 postable before
and after, all six gates +0.0000). See `reports/CORE-001-postable-fails-open.md`.
