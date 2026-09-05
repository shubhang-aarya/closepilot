# Contract: `baselines`

**Owns:** `eval/baselines.py` · **Priority: highest.** Nothing else converts the
engine's number into a claim.

## Why this exists

`PRD.md` currently says the engine reaches 20.0% exact-set match. On its own that
is unfalsifiable — a reviewer cannot tell whether 20% is good. Three reference
matchers on identical data turn it into a comparison, and a comparison is an
argument.

## What to build

Three matchers, each returning `list[Prediction]` (see `attest/eval/harness.py`):

1. **`exact_only`** — match a settlement to orders only via unambiguous
   identifier evidence. No amount reasoning. Establishes the floor.
2. **`fuzzy`** — the industry default. Amount within 1% of the credit, capture
   date inside the lookback window, first candidate wins. This is what most
   off-the-shelf tooling does and it is the number worth beating.
3. **`greedy`** — score candidates by amount closeness, take the best, consume
   its orders, repeat. Deliberately does no global reasoning, so the gap between
   this and the engine isolates the value of constraint propagation.

## Interface

```python
def fuzzy(settlements: list[Settlement], orders: list[Order]) -> list[Prediction]: ...
```

Use `attest.blocking.candidates(settlements, orders, rung=2)` for pools so every
matcher sees the same evidence. Differences must come from the algorithm, not
from one method being handed a better candidate set.

## Acceptance

- Runs at `seed=20260821`, `n=250`, via `attest.eval.harness.evaluate`
- Emits `eval/BASELINES.md`: one row per matcher with **exact-set %, precision,
  recall, WRONG %, wall clock**
- **`WRONG` is the column that matters.** A fuzzy matcher scoring higher on
  exact-set while posting 4% wrong entries is a worse system, and the table must
  make that visible rather than burying it
- Read-only outside `eval/`

## Report

The table, plus one paragraph: where does the engine win, where does a baseline
beat it, and on which hazard families. If a baseline wins somewhere, say so
plainly — that is the most useful sentence you can write.
