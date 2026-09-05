# Baselines

Three reference matchers on identical data, through the identical harness.
250 settlements, seed 20260821, candidate pools from `blocking.candidates(rung=2)`
so every matcher sees the same evidence — differences come from the algorithm,
never from one method being handed a better candidate set.

```
matcher        exact    declined      WRONG       precision     time
--------------------------------------------------------------------
exact-only      4.0%       96.0%     0   0.0%       1.000      0.03s
fuzzy           3.2%       92.4%    11   4.4%       0.421      0.04s
greedy          4.4%        5.2%   226  90.4%       0.166      0.03s
ATTEST         20.8%       79.2%     0   0.0%       1.000      0.91s
```

## Read the WRONG column, not the exact column

**greedy** is the result worth staring at. It declines 5.2% of the time and is
wrong 90.4% of the time. It reaches a marginally higher exact-set score than
`exact-only` and it is by far the most dangerous system in the table: 226 of 250
settlements would post accounting entries against orders that did not produce
them.

That is what "the tool matched them for you" looks like when the tool has no way
to abstain.

**fuzzy** is the industry default — amount within 1%, date inside the window,
first candidate wins. It scores *lower* on exact-set match than doing nothing
clever at all, and buys that with 11 false proofs. When several orders fit it
takes one, and that single decision is where nearly all of its errors come from.

**exact-only** is honest and nearly useless: no tolerance, no search, so it
recovers only the settlements that were never hard.

## Why greedy fails structurally

Taking the largest order that still fits is a local decision, and **subset-sum
has no greedy-choice property**. One early take consumes an order a correct
explanation needed, and there is no way back — the algorithm cannot reconsider,
so it reports whatever it happened to reach. This is not a tuning problem. No
threshold fixes it.

## The comparison that matters

ATTEST reaches **5× the exact-set match of the best baseline while posting zero
false proofs**, and it declines 79.2% of the time — loudly, with a reason
attached to each one.

A high decline rate is the cost of the guarantee, and it is the right trade for
finance: a decline routes to a human, a false proof moves money. The engine is
built so the second number can be zero, and here it is.
