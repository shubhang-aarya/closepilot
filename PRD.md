# ATTEST — settlement reconciliation as constrained optimization

**Razorpay AI Buildathon · Track 04, AI Finance Controller · 7-day solo build**

> A reconciliation engine that treats settlement matching as an exact
> combinatorial search instead of fuzzy matching. An LLM proposes hypotheses;
> a deterministic solver falsifies them. Nothing posts unless it is proven.

---

## 1. The problem

A merchant's bank statement shows one credit: **₹47,382.19**.

That single line is the net of some subset of the 400 orders they captured that
week — minus per-transaction fees, minus GST on those fees, offset by a refund,
shifted T+2 by the settlement calendar, and described by a bank narration
reading `NEFT-8871XXXXXX-RAZORPAY SOF`.

**Which orders?**

Nobody knows. It is resolved by hand, in Excel, daily, at essentially every
merchant in India. Attribution is not optional — it drives revenue recognition,
GST input credit, and any answer to "did we actually get paid for order #1841."

Razorpay's own framing for this track: *"verification capacity, not generation
speed, is the bottleneck. Reconciliation, settlement and forecasting are still
done by hand."*

---

## 2. Why this track, and why this problem

The decisive argument is not difficulty. It is **whether the numbers are
defensible**.

| Track | Why not |
|---|---|
| 01 Agentic Commerce | Most contested track; the bar ("explainable, bounded, gated") is qualitative, so clearing it cannot be demonstrated. |
| 02 Risk Manager | **Circular ground truth.** You invent the fraud patterns, then detect them. Precision/recall measures the author's imagination. |
| 03 Revenue Recovery | Same engine underneath — *"which invoices does this partial payment settle?"* is the identical subset problem — but "money recovered" needs an invented counterfactual. |
| 05 Open | Discards the free problem framing; pitches non-payments work to payments engineers. |
| **04 Finance Controller** | **Ground truth is constructible without circularity.** Orders are generated first; settlements are derived *from* them. The true mapping is known exactly, by construction. |

Every accuracy figure in this project is measured against a mapping that is
true by construction, not by assumption. No other track allows that claim.

---

## 3. The core insight

Fees make gross amounts disagree with bank credits, so reconciliation is
conventionally treated as **fuzzy matching**. That framing is what caps every
off-the-shelf tool around 70%.

But **where the fee rule is known**, fees are computable rather than fuzzy.
Normalising each order to its **expected net** first:

```
before:   credit ≈ Σ gross − unknown fees        (approximate search)
after:    credit = Σ net   ± rounding            (exact subset-sum)
```

The residual is not a tuned fudge factor. `fee_paise` and `tax_paise` each round
half-up independently, so one order carries at most 1 paisa of error, and a
k-order subset drifts by at most **k paise**:

```python
def tolerance_paise(subset_size: int) -> int:
    return subset_size
```

Derived, not tuned. A hand-picked constant is wrong in both directions at once:
too tight and large bundles never match; too loose and small subsets collide
inside the tolerance band.

Where the rule is *not* known — an unrecorded payment method, so the rate is
uncertain — the order contributes a small **set** of possible nets rather than
one, and L3 generalises to multi-choice subset-sum. The engine degrades to a
wider search rather than to guesswork.

**Consequence:** an approximate matching problem becomes an exact combinatorial
one — which is harder in complexity and far better behaved in practice, because
exact arithmetic can *falsify* a candidate. Fuzzy scores never can.

---

## 4. The algorithm

Matching one credit to N orders is **subset-sum** — NP-complete. When bundles
exist on both sides (orders split across settlements, chargebacks reversing
across periods), it becomes **set partitioning**, an integer program.

Most implementations do fuzzy string matching plus 1-to-1 amount comparison,
reach ~70%, and never diagnose that the residue is a different problem class.

```
L0  blocking / candidate generation      date-bucketed, O(n + m·w)      no AI
L1  bank credit → settlement             UTR regex + exact fallback     no AI
L2  settlement → single order            exact within 1 paisa           no AI
L3  settlement → subset of orders        meet-in-the-middle, interval   no AI   ◄ core
L4a 1:1 contention                       Hungarian assignment           no AI
L4b global selection                     CP-SAT set packing             no AI   ◄ global
L5  unstructured narration / names       LLM proposes, solver falsifies  AI
L6  calibration → auto-post threshold    isotonic + cost model          no AI
L7  exceptions, each with a reason       —                              no AI
```

### L3 — meet-in-the-middle with interval search

Brute force over 40 candidates is 2⁴⁰ ≈ 10¹². Split into halves, enumerate
2²⁰ ≈ 10⁶ partial sums per side, sort one side, binary-search the other.

**O(2^(n/2)·n)** time, **O(2^(n/2))** space.

The non-textbook part: classic meet-in-the-middle searches for an *exact* value.
Tolerance makes this a **range query** — `bisect_left`/`bisect_right` against
both bounds of `[target − k, target + k]`, where k is itself a function of the
subset size being tested.

Blocking is what keeps n under ~40. **The pruning is the engineering; the
algorithm is the easy half.**

### L4 — why greedy is wrong, and why Hungarian is not the fix

Greedy selection (take the highest-scoring candidate, remove its orders, repeat)
is the obvious approach and it is incorrect: one confident-looking explanation
consumes an order another explanation needed, and both are lost.

The natural next reach is minimum-cost bipartite assignment
(`linear_sum_assignment`, Hungarian/JV, O(n³)). **That is also wrong here**, and
the reason is worth stating precisely.

Hungarian solves a *one-to-one* matching between two sets. After L3, each
settlement carries several candidate **subsets**, and two candidates conflict
when they share an order. Hungarian has no way to express *"candidate A for S1 is
incompatible with candidate B for S2 because both claim order #17."*

Selecting at most one candidate per settlement such that the chosen subsets are
pairwise disjoint is **set packing** — NP-hard, and expressible as an integer
program but not as an assignment problem.

So the layer splits:

* **L4a — Hungarian**, on the genuinely 1:1 sub-problem: several settlements
  whose only candidate is the *same* single order. Cheap, exact, correct here.
* **L4b — CP-SAT set packing**, on everything else. Disjointness as a hard
  constraint, confidence as the objective, decomposed by connected component so
  each program stays small.

**Headline experiment:** greedy vs. globally optimal, identical data, identical
scores. Plus published baselines — exact-only, fuzzy, and greedy — run on the
same hazards, so the claim is comparative rather than self-reported.

### L5 — the only place a model belongs

An LLM reads exactly one thing: `BankCredit.narration`, plus counterparty names.
Free text is the only genuinely unstructured field in the system.

It **proposes** candidate subsets. The solver **falsifies** them by exact
arithmetic. A proposal that does not sum is discarded regardless of how
confident the model sounded.

This is also why a multi-agent ensemble is principled here rather than
decorative: if generation is cheap and verification is exact, more diverse
proposers is strictly better — no voting, no consensus, no debate. Everything
that survives arithmetic is kept.

---

## 5. Why the output is a posterior, not a boolean

The hazard set deliberately includes `AMBIGUOUS_SUBSET`: two **disjoint** subsets
of the candidate pool whose nets sum to the same value within tolerance.
Constructed using UPI orders, which are zero-MDR in India, so net == gross and
the collision can be made exact.

Exactly one is correct. **Arithmetic cannot say which.**

A matcher returning a single answer here is not more accurate than one returning
two ranked answers — it is the same accuracy, dishonestly reported. So:

```
₹47,382.19
  → {#1841, #1847, #1852, … 23 orders}   94.1%   ✓ auto-post
  → {#1841, #1847, #1863, … 23 orders}    5.2%   → review
  → unexplained                            0.7%
```

Auto-post fires above a threshold **derived from an explicit cost model**: a
wrong auto-post costs far more than an escalation, so the threshold falls out of
that asymmetry rather than being chosen by feel. Calibrated with isotonic
regression so the probabilities mean something.

---

## 6. Evaluation

Ground truth is exact. Hazards are enumerated in `attest/generate/taxonomy.py`,
**frozen on D1**, and every ground-truth row is labelled with the family that
produced it — so misses are attributed to a named cause, not to a percentage.

Reported metrics:

- **exact set match** — the predicted order set equals the true set
- **declined** — routed to a human. A first-class outcome, not a failure
- **wrong** — matched, incorrectly. The number that actually moves money
- **pair precision / recall** — over (settlement, order) pairs
- **blocking recall** — the ceiling layer 0 imposes. Any later recall must be
  read against it; a matcher reporting 94% under a blocker that discarded 5% of
  true pairs is really reporting 89%. Almost nobody measures this
- **rupee coverage** — a settlement is not worth its row count
- **per-hazard accuracy**, ablation table, p50/p95/p99 latency, cost per 1k
- **published baselines** — exact-only, fuzzy, and greedy matchers implemented in
  `eval/baselines.py` and run on identical data, so every claim is comparative

### Every claim is pooled across a fixed seed panel

A single seed is an anecdote. `python -m attest 250 --sweep` runs five fixed
seeds and reports the pooled figure plus the worst seed. Current:
**18.5% exact, 5 false proofs across 1,250 settlements, pooled precision 0.981**,
worst seed 555001 at 2. The earlier "precision 1.000" was seed 20260821 alone
and did not survive the panel.

### D1 measured baseline — deterministic floor, no search, no model

```
settlements              1,200
exact set match            4.8%
declined (to human)       95.2%
WRONG (moved money)        0.0%     ← precision 1.000; declines instead of guessing
blocking recall            0.999    ← ceiling; layer 0 discards nothing
wall clock                 0.34s
```

Every subsequent claim is a delta against this line.

---

## 7. Plan

| Day | Deliverable |
|---|---|
| **1 ✅** | Hazard taxonomy (15 families), generator with exact ground truth, eval harness, layers 0–2. **Baseline: 4.8%, 0 wrong.** |
| 2 | L3 meet-in-the-middle subset-sum with interval search |
| 3 | L4 global assignment. **Greedy vs. optimal chart** |
| 4 | L5 hypothesis ensemble + solver falsification; 1-vs-4 proposer ablation |
| 5 | CP-SAT set partitioning; isotonic calibration; cost-derived threshold |
| 6 | Profile, then port the L3 hot loop to Rust via PyO3. Benchmark table |
| 7 | Full ablations, held-out run (executed once), README, 5-minute video |

D5 is designed so both outcomes are wins: if CP-SAT beats Hungarian, the heavier
formulation ships; if it adds 0.8% for 40× the runtime, that measurement is the
result and Hungarian ships.

---

## 8. Risks, and what is done about them

| Risk | Mitigation |
|---|---|
| Generator is unconsciously tuned to suit the matcher | Written and **frozen on D1**, before any search code exists. Held-out seed run once, at the end |
| Beautiful algorithm that does not move the number | Baseline exists on day 1; every layer must justify itself in the ablation table or be reported as a null result |
| Non-determinism from the LLM layer | All inference cached and committed; full run replayable offline |
| Swarm-generated code reads as generated | Solver core (~400 lines) hand-written in one voice; agents own generators, tests, harness, docs |
| Rust port consumes D6 with nothing to show | Port happens only after profiling proves the hot loop dominates; Python path stays correct and shippable |

---

## 9. Non-goals

No UI beyond a CLI and matplotlib — reviewers read repositories. No multi-currency.
No streaming/incremental reconciliation. No real bank integrations. Nothing not
listed in §7.

---

## 10. Repository

```
attest/
├── model.py            fee model, tolerance derivation, records     ← hand-written
├── blocking.py         L0 candidate generation                      ← hand-written
├── layers.py           L1–L2 deterministic floor                    ← hand-written
├── subsetsum.py        L3 meet-in-the-middle                 D2     ← hand-written
├── assign.py           L4 Hungarian                          D3     ← hand-written
├── partition.py        L4b CP-SAT                            D5     ← hand-written
├── hypotheses/         L5 proposers                          D4     ← agents
├── calibrate.py        L6                                    D5     ← hand-written
├── generate/           taxonomy + generator                         ← frozen D1
└── eval/               harness, ablations, plots                    ← agents
native/                 Rust MITM + PyO3                      D6
FAILURES.md             kept daily, from hour one
```
