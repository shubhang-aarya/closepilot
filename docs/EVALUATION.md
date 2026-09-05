# Evaluation

## Ground truth by construction

Orders are generated first; settlements are derived **from** them. The mapping is
known exactly rather than approximately, and that is the single reason any figure
here can be defended.

It is also why Track 04 was the only tenable choice. Fraud detection would have
meant inventing the patterns and then detecting them — precision measuring the
author's imagination. Reconciliation has no such circularity.

## Fifteen hazard families

Frozen in `attest/generate/taxonomy.py` **before the matcher existed**, so the
benchmark cannot be tuned to flatter the engine. Every ground-truth row is
labelled with the family that produced it, so a miss is attributed to a named
cause rather than absorbed into a rate.

The one that decides the product's shape is `AMBIGUOUS_SUBSET`: two disjoint
subsets whose nets sum to the same value within tolerance, built from zero-MDR
UPI orders so the collision is exact. Arithmetic cannot say which is correct. A
matcher returning a single answer there is not more accurate than one returning
two ranked answers — it is the same accuracy, dishonestly reported.

Four families are **structurally unreachable** by an exact solver, because the
credit does not equal the sum of the true orders: `SPLIT_ORDER`,
`REFUND_OFFSET`, `CHARGEBACK_REVERSAL`, `ORPHAN_SETTLEMENT`. Those are model
gaps, not search failures, and widening the search cannot fix them (D10).

## One number cannot describe this engine

```
18.5% exact set recovery  +  98.1% proof precision
  is NOT
"98.1% accurate reconciliation"
```

The first is how often the complete truth is recovered. The second is how often
the engine is right *when it claims to be sure*. Blending them sells the second
while doing the work of the first.

| metric | what it measures |
|---|---|
| exact set recovery | complete ground-truth set recovered |
| **false proof rate** | **a claim of proof that was wrong — the number that moves money** |
| proof precision | right when it claims to be sure |
| coverage | resolved at all |
| ambiguity rate | correctly refused. A feature |
| blocking recall | the **ceiling** L0 imposes; any recall is read against it |
| accounted for | proven, or agreed by every surviving explanation |
| financial error rate | share of auto-posted **value** posted wrongly |
| safe resolution rate | resolved without a human, and allowed to be |

## Read `accounted for`, not `exact set recovery`

16% complete recovery reads like an engine that fails five times out of six. That
reading is wrong.

When several explanations survive, the orders in **every** one of them belong to
that settlement whichever is right. So the engine states that part as settled and
names the exact remainder in dispute. **77.5% of ambiguous value turns out not to
be in dispute at all**, and 67.3% of all processed value is accounted for.

A real case from the held-out seed: `setl_000200`, ₹92,666.62, with four surviving
explanations. Twenty-three orders worth ₹91,599.60 appear in all four. Only
₹3,435.87 across eleven orders is
contested, and the next step is not "investigate" — it is *a reference on any one
of those twelve settles the rest*.

## The seed panel

A single seed is an anecdote. The engine reported precision 1.000 for six days on
the strength of seed 20260821 alone; four other seeds produce 0, 1, 2 and 2 false
proofs (D7).

Every claim is pooled across a fixed five-seed panel, and the worst seed is
reported beside the aggregate. Pooling counts **pairs**, not per-seed precisions:
a mean weights a 250-settlement run identically to a 1,200-settlement one and
flatters whichever was small.

Calibration and evaluation seeds are **disjoint**. Fitting the risk model on the
portfolios it then judges reports its memory as its accuracy.

## Coverage is not a constant

```
250 settlements/seed   coverage 16.8%   false proof rate 0.80%
600 settlements/seed   coverage  8.5%   false proof rate 0.08%
```

Denser portfolios mean larger pools and more subsets landing within tolerance.
The engine is not worse on the bigger portfolio — the bigger portfolio is a harder
question, and the false-proof rate falls with it because the engine refuses more.
Any coverage figure quoted without its portfolio density is meaningless.

## Baselines

Same data, same candidate pools, so differences come from the algorithm.

```
matcher        exact    declined      WRONG       precision
exact-only      4.0%       96.0%     0   0.0%       1.000
fuzzy           3.2%       92.4%    11   4.4%       0.421
greedy          4.4%        5.2%   226  90.4%       0.166
ATTEST         20.8%       79.2%     0   0.0%       1.000
```

**Read the WRONG column.** Greedy declines 5% of the time and is wrong 90% of the
time — 226 of 250 settlements posted against orders that did not produce them.
That is what a matcher with no way to abstain does. Fuzzy, the industry default,
scores *below* doing nothing clever and buys it with 11 false proofs.

## Every false proof is attributed

```
5 across 1,250 settlements
  model gap       3    the truth is not expressible under the constraints
  search space    2    the truth was pruned before solving
  unattributed    0
```

Zero unattributed is the number that matters. A property test fails the build if
any false proof becomes unattributable, because an unexplained wrong answer is a
defect nothing currently accounts for.

## The property the engine actually has

Not *"ATTEST never produces a false PROVEN"* — it produces them at roughly 0.8%,
and asserting otherwise is what D7 cost. The true property is conditional:

> when the truth was in the candidate pool **and expressible under the
> constraints**, a PROVEN result is correct

Writing the condition down is what surfaced the model-gap failure class nobody
had named.

## Gates

The build fails on safety, never on accuracy. Money wrongly auto-posted and the
false-proof rate carry no tolerance; coverage metrics are advisory and may fall.
A symmetric gate would have argued for shipping D4, D8 and D12 — all three of
which correctly traded coverage for safety.

## Coverage falls as portfolio density rises

Coverage is not a constant of the engine. It is a function of how many orders
share a window, and it falls as that number grows. Measured on held-out seed
555001, native kernel, one run per size:

```
settlements   proven   coverage   ambiguous   exact set   false proofs
        250       39      15.6%       84.0%       0.148              2
        600       49       8.2%       91.7%       0.082              0
      1,200       71       5.9%       94.0%       0.058              1
```

`benchmark/results.json` records the same shape independently in its own note:
16.8% coverage at 250 settlements/seed against 8.5% at 600, with the false-proof
rate falling from 0.80% to 0.08% across the same change.

**This is an ambiguity characteristic, not a resource limit.** The solver is not
running out of envelope — `INSUFFICIENT` stays at zero across all three sizes.
More settlements over the same 90-day window means larger candidate pools, which
means more disjoint subsets land inside tolerance, which means more settlements
have genuinely more than one arithmetic explanation. The engine reports them as
AMBIGUOUS because they are.

Two things are worth reading off the table together. The **rate** falls, and the
**absolute number of proofs rises** — 39, 49, 71. The engine is not finding less;
the question is getting harder faster than the engine gets bigger. And the
false-proof count does not rise with density, which is the property that matters:
the additional ambiguity is absorbed as refusal, not as guessing.

That is the trade this project is built around, and it is worth stating as a
limitation rather than a feature: **on a dense portfolio, ATTEST will hand a
person most of the book.** A matcher willing to pick one of several valid
explanations would report far higher coverage on exactly these inputs, and would
be wrong more often — `greedy` in the baseline panel decides 462 of 500 and is
wrong 439 times. We would rather return less and be able to say which part is
safe.

No claim is made about behaviour beyond 1,200 settlements in a 90-day window;
nothing in this repository measures it.
