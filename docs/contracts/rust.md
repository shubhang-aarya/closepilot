# Contract: `rust`

**Owns:** `native/**` · Load-bearing, not a flourish.

## Why this exists

`attest/subsetsum.py::_reachable` is a counting DP over the amount axis,
O(n·target). At production scale that is ~4.3e9 cell updates per settlement.
numpy cannot carry it: 250 settlements currently take ~12s, and the target is
5,000. The engine's headline throughput number does not exist without this port.

## What to build

Port `_reachable` to Rust, exposed through PyO3.

- Counters saturate at 2. The verdict only needs to distinguish
  **none / exactly one / more than one**, so two bits per reachable sum is
  sufficient — pack them. Do not store `u8` per sum out of convenience; the
  memory-bandwidth win is the entire point of the port.
- 0/1 knapsack semantics: each order spent at most once. Update order matters.
- Signature mirrors the Python: `nets: &[u64], target: u64 -> counts`.

## Acceptance

- **Byte-identical output to the numpy reference** on every instance inside
  `MAX_TARGET_PAISE`, verified by a differential test over ≥1,000 random
  instances plus every hazard family. Not "close" — identical.
- A criterion benchmark reporting p50/p95 against the Python path
- Builds via `maturin develop` with the steps written into `native/README.md`
- Python falls back to numpy automatically if the extension is absent. The repo
  must clone-and-run without a Rust toolchain.

## Report

The benchmark table, the crossover point where Rust starts winning, and the
memory footprint at p50 and p90 pool sizes. If packing to 2 bits turned out
slower than bytes, report that — it is a real result about cache behaviour.
