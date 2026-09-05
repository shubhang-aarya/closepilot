# Proposal: wire `attest_fast` into `attest/subsetsum.py`

**Not applied.** `attest/subsetsum.py` is frozen under `AGENTS.md`, and the
frozen list is enforced by `.githooks/pre-commit`. This is the diff for whoever
owns that file to apply, reject, or rewrite.

Everything the diff depends on is built and verified: see `native/BENCH.md`.

## The diff

```diff
--- a/attest/subsetsum.py
+++ b/attest/subsetsum.py
@@
 import numpy as np
 
+from attest_fast import reachable as _fast_reachable
 from attest.model import Order, tolerance_paise
 from attest.verdict import Verdict
@@ def solve(pool: list[Order], target: int) -> tuple[Verdict, list[Solution]]:
-    counts = _reachable([n for _, n in usable], target)
+    counts = _fast_reachable([n for _, n in usable], target)
```

Two lines, one of which is an import. `_reachable` itself is untouched and stays
the reference — `attest_fast` calls it directly on the fallback path, so there is
exactly one implementation of the recurrence in Python and it cannot drift.

## What the caller has to accept

**`native/` must be on `sys.path`.** The shim is not installed into the
repository's `.venv`. Either `PYTHONPATH=$PWD:$PWD/native`, or add
`native` to the repo's own packaging, or move `attest_fast/` up a level. The
third is cleanest and is not mine to do.

**Behaviour is unchanged when the extension is absent.** `attest_fast` imports
successfully with no Rust toolchain and returns `_reachable`'s own output.
Verified across three interpreters in `native/tests/fallback.py`, including the
repository's own `.venv`, which has no extension in it.

**Output is byte-identical, not equivalent.** 1,777 instances / 1.32e11 DP cells,
including real `(pool, target)` pairs from all fifteen hazard families at every
rung of `LAG_LADDER`. `counts.tobytes()` compared, not `np.array_equal`, because
`solve` sums a slice of this array and a dtype difference would change the sum.

## Two things worth deciding at the same time

**1. `MAX_TARGET_PAISE` is now the binding constraint, not the DP.**
At seed 20260821, n=250, **37 of 250 settlements exceed `MAX_TARGET_PAISE`** and
never reach the DP at all — including **all 34 `bundle_large` settlements**, the
family the taxonomy calls "the core hard case". They are answered
`AMBIGUOUS / L3-skipped` by `pipeline.run` without a subset ever being counted.

The docstring in `subsetsum.py` says the ceiling exists because "the numpy
reference exhausts memory bandwidth". At `MAX_POOL=900` and a target of 1e7
paise the packed kernel needs 2.5 MiB of state and, measured, well under a
second. Raising the ceiling is now a policy question about latency, not a
capability limit — but it is a change to a frozen file with real accuracy
consequences, so it is flagged, not made.

**2. `solve` never needs the expanded array.** It uses `counts` for exactly one
thing:

```python
total = int(counts[lo : hi + 1].sum())
```

and then only tests `total == 0`. Expanding two bitplanes into `target + 1`
bytes purely so numpy can sum a slice of it is the single largest remaining cost
in the Rust path at large targets. `attest_native.band_total(nets, target, lo,
hi)` already answers that question directly from the bitplanes. Wiring *that*
in instead would be a larger diff — `solve`'s body changes shape — which is why
the drop-in above is what is proposed.
