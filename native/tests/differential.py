"""Differential test: the packed kernel against the numpy reference.

Byte-identical is the acceptance bar, so the comparison is on raw bytes rather
than on values -- `np.array_equal` would pass on two arrays that differ in dtype
and therefore in what `counts[lo:hi+1].sum()` returns in `solve`.

Two populations, because random instances and real ones fail differently. The
random sweep is where word-boundary carries and degenerate inputs live; the
harvested sweep is where the actual net magnitudes, pool compositions and
duplicate structures of each hazard family live, and those are what an
optimisation like the reachability bound is tuned by.

Run:  PYTHONPATH=<repo> native/.venv/bin/python native/tests/differential.py
"""

from __future__ import annotations

import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from attest.blocking import LAG_LADDER, candidates
from attest.generate.generator import build
from attest.subsetsum import MAX_POOL, MAX_TARGET_PAISE, _reachable

import attest_fast

#: Same seed the engine trains on. The held-out seed is reserved for D7 and is
#: never touched here.
SEED_TRAIN = 20260821
N_SETTLEMENTS = 250
N_RANDOM = 1_000


@dataclass(frozen=True, slots=True)
class Instance:
    label: str
    nets: list[int]
    target: int

    @property
    def cells(self) -> int:
        return len(self.nets) * (self.target + 1)


def _edge_cases() -> list[Instance]:
    """Inputs chosen to break a packed implementation specifically.

    Nets at multiples of 64 exercise the whole-word shift path; nets at 63/65
    exercise the cross-word carry; nets equal to and one past `target` exercise
    the skip that mirrors the reference.
    """
    out: list[Instance] = []
    for net in (1, 2, 63, 64, 65, 127, 128, 129, 191, 192, 255, 256, 257):
        out.append(Instance(f"edge/word{net}", [net, net, net, 1, 64], 1_000))
    out += [
        Instance("edge/empty", [], 0),
        Instance("edge/empty-wide", [], 100_000),
        Instance("edge/zeros", [0, 0, 0], 500),
        Instance("edge/all-oversized", [10_000, 20_000], 999),
        Instance("edge/net-eq-target", [777], 777),
        Instance("edge/net-past-target", [778], 777),
        Instance("edge/target-0", [1, 2, 3], 0),
        Instance("edge/target-1", [1, 1, 1], 1),
        Instance("edge/target-63", [1] * 8, 63),
        Instance("edge/target-64", [1] * 8, 64),
        Instance("edge/target-65", [1] * 8, 65),
        Instance("edge/saturate-everywhere", [1] * 64, 2_000),
        Instance("edge/max-target-tiny-pool", [MAX_TARGET_PAISE], MAX_TARGET_PAISE),
        Instance("edge/max-target-max-pool",
                 [MAX_TARGET_PAISE // MAX_POOL] * MAX_POOL, MAX_TARGET_PAISE),
    ]
    return out


def _random_instances(n: int, seed: int) -> list[Instance]:
    """Log-uniform in both axes.

    Uniform would concentrate every draw near the maximum and never test a
    900-order pool against a 5,000-paise credit, which is exactly the shape
    where the reachability bound changes which words get touched.
    """
    rng = random.Random(seed)
    out: list[Instance] = []
    for i in range(n):
        target = int(round(MAX_TARGET_PAISE ** rng.random()))
        size = int(round(MAX_POOL ** rng.random()))
        # A quarter of the draws use nets far below target so the DP front
        # advances slowly; the rest span the full range and saturate at once.
        top = target // 8 if i % 4 == 0 else target + target // 8
        nets = [rng.randint(0, max(top, 1)) for _ in range(size)]
        out.append(Instance(f"random/{i}", nets, target))
    return out


def _harvested() -> tuple[list[Instance], dict[str, dict[str, int]]]:
    """Real (pool, target) pairs from the seed-20260821 portfolio, by family.

    Every rung of `LAG_LADDER` is harvested, not just rung 0: escalation is what
    produces the large pools, and a kernel that is correct on 45 orders and
    wrong on 217 is wrong where it matters.

    Settlements above `MAX_TARGET_PAISE` are outside what the contract asks the
    port to match, but dropping them silently would leave whole families
    untested -- `bundle_large` is entirely above the ceiling. Those are re-emitted
    with `target` clamped to the ceiling, which keeps the family's real pool
    composition while staying inside the envelope, and counted separately.
    """
    ds = build(N_SETTLEMENTS, seed=SEED_TRAIN)
    case_of = {t.settlement_id: t.case for t in ds.truth}

    out: list[Instance] = []
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"natural": 0, "clamped": 0})

    for rung in range(len(LAG_LADDER)):
        pools = candidates(ds.settlements, ds.orders, rung)
        for s in ds.settlements:
            fam = case_of[s.settlement_id]
            clamped = s.net_paise > MAX_TARGET_PAISE
            target = MAX_TARGET_PAISE if clamped else s.net_paise
            # Mirrors the `usable` filter in `solve`, so these are the exact
            # arrays `_reachable` is called with in production.
            nets = [o.net for o in pools[s.settlement_id] if 0 < o.net <= target]
            kind = "clamped" if clamped else "natural"
            stats[fam][kind] += 1
            out.append(Instance(f"{fam}/r{rung}/{s.settlement_id}/{kind}", nets, target))

    return out, dict(stats)


def _compare(instances: list[Instance], fast: object) -> tuple[int, list[str]]:
    bad: list[str] = []
    for inst in instances:
        ref = _reachable(inst.nets, inst.target)
        got = fast(inst.nets, inst.target)  # type: ignore[operator]
        if got.dtype != np.uint8 or got.shape != ref.shape or got.tobytes() != ref.tobytes():
            where = np.flatnonzero(np.asarray(got, dtype=np.int16) != ref.astype(np.int16))
            bad.append(f"{inst.label}: n={len(inst.nets)} target={inst.target} "
                       f"dtype={got.dtype} shape={got.shape} first_diff="
                       f"{where[0] if where.size else 'dtype/shape only'}")
    return len(instances), bad


def main() -> int:
    if attest_fast.BACKEND != "rust":
        print("FAIL: attest_fast.BACKEND is 'numpy'; the extension is not importable.")
        print("      Comparing numpy against itself proves nothing. Run `maturin develop`.")
        return 1

    edges = _edge_cases()
    randoms = _random_instances(N_RANDOM, SEED_TRAIN)
    harvest, stats = _harvested()

    print(f"backend={attest_fast.BACKEND}  numpy={np.__version__}")
    print(f"instances: {len(edges)} edge + {len(randoms)} random + {len(harvest)} harvested "
          f"= {len(edges) + len(randoms) + len(harvest)}")
    cells = sum(i.cells for i in edges + randoms + harvest)
    print(f"DP cells compared: {cells:.3e}\n")

    print(f"{'hazard family':<22} {'natural':>8} {'clamped':>8}")
    for fam in sorted(stats):
        print(f"{fam:<22} {stats[fam]['natural']:>8} {stats[fam]['clamped']:>8}")
    missing = [f for f, c in stats.items() if c["natural"] + c["clamped"] == 0]
    print(f"families covered: {len(stats) - len(missing)}/{len(stats)}\n")

    failures = 0
    t0 = time.perf_counter()
    for group, insts in (("edge", edges), ("random", randoms), ("harvested", harvest)):
        n, bad = _compare(insts, attest_fast.reachable)
        failures += len(bad)
        print(f"[{'OK ' if not bad else 'BAD'}] {group:<10} {n:>5} instances, "
              f"{len(bad)} mismatches")
        for line in bad[:10]:
            print(f"        {line}")
    print(f"      elapsed {time.perf_counter() - t0:.1f}s")

    print()
    if failures:
        print(f"RESULT: {failures} mismatches -- NOT byte-identical.")
        return 1
    print(f"RESULT: byte-identical on {len(edges) + len(randoms) + len(harvest)} instances "
          f"({cells:.3e} DP cells), all {len(stats)} hazard families.")
    return 0


if __name__ == "__main__":
    if os.environ.get("ATTEST_NATIVE") == "0":
        print("ATTEST_NATIVE=0 forces the numpy path; this test needs the extension.")
        raise SystemExit(1)
    raise SystemExit(main())
