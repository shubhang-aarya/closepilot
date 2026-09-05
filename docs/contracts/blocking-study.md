# Contract: `blocking-study`

**Owns:** `eval/blocking_study.py` · Do **not** edit `attest/blocking.py`.

## Why this exists

Blocking sets a hard ceiling on everything downstream, and D3 proved the failure
is not merely lost recall: when the true explanation is pruned, a *different*
subset can match uniquely, and the engine then proves something internally
consistent and factually wrong. Blocking errors manufacture false proofs.

The lag ladder `(2, 3, 4)` in `attest/blocking.py` was chosen by argument, not
measurement. Measure it.

## What to build

A sweep reporting, for each configuration: **p50 / p90 / max pool size** and
**blocking recall**, over

- lag ladders: every subset of `(1,2,3,4,5,6)` worth testing
- with and without the `net <= credit` amount filter
- with and without global consumption enabled

Plus a per-hazard breakdown of *which families lose pairs at each setting* —
`CHARGEBACK_REVERSAL` reaches 14–30 days back and is expected to fail; confirm
that and quantify what widening enough to catch it costs everyone else.

## Acceptance

- Emits `eval/BLOCKING.md` with the tradeoff curve (pool size vs. ceiling)
- Recommends a ladder, with the numbers that justify it
- Recommendation goes to the inbox. **You do not apply it.**

## Report

The curve, the recommendation, and the cost of the recommendation — stated as
"this ladder costs X% ceiling to save Y% pool size."
