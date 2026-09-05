"""The Python-path benchmark: packed Rust kernel vs. the numpy reference.

Criterion measures the kernel; this measures what the engine would actually
feel, which is the kernel plus the PyO3 boundary. Both numbers are needed --
the boundary is what decides the crossover, and the crossover is what decides
whether wiring the extension in is worth anything on small pools.

Timings are per-instance wall clock over the real portfolio, not a synthetic
sweep, so the p50/p95 are the distribution the engine sees rather than the
distribution of a shape someone picked.

Run:  PYTHONPATH=<repo> native/.venv/bin/python native/bench/pybench.py
"""

from __future__ import annotations

import json
import statistics as stats
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import attest_fast
import attest_native
from attest.blocking import LAG_LADDER, candidates
from attest.generate.generator import build
from attest.subsetsum import MAX_POOL, MAX_TARGET_PAISE, _reachable

SEED_TRAIN = 20260821
N_SETTLEMENTS = 250

#: Bytes numpy holds live at the peak of one `_reachable` iteration: `counts`
#: and its `prev` copy at one byte per sum, plus the uint16 `head` temporary and
#: the uint16 result of `np.minimum`. Derived from the reference's five lines
#: rather than measured, because an allocator high-water mark on this machine is
#: not the number a reader can check against the source.
NUMPY_PEAK_MULTIPLIER = 6


@dataclass(frozen=True, slots=True)
class Case:
    family: str
    rung: int
    nets: list[int]
    target: int

    @property
    def cells(self) -> int:
        return len(self.nets) * (self.target + 1)


def _time(fn: object, nets: list[int], target: int, reps: int) -> float:
    """Best-of-`reps` seconds.

    Minimum, not mean: the thing being measured is a deterministic kernel, so
    every deviation above the floor is scheduler noise, and averaging it in
    would report this laptop rather than the code.
    """
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(nets, target)  # type: ignore[operator]
        best = min(best, time.perf_counter() - t0)
    return best


def _portfolio() -> list[Case]:
    ds = build(N_SETTLEMENTS, seed=SEED_TRAIN)
    case_of = {t.settlement_id: t.case for t in ds.truth}
    out: list[Case] = []
    for rung in range(len(LAG_LADDER)):
        pools = candidates(ds.settlements, ds.orders, rung)
        for s in ds.settlements:
            if s.net_paise > MAX_TARGET_PAISE:
                continue  # `solve` raises OutOfEnvelope before reaching the DP
            nets = [o.net for o in pools[s.settlement_id] if 0 < o.net <= s.net_paise]
            out.append(Case(case_of[s.settlement_id], rung, nets, s.net_paise))
    return out


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def _report_portfolio(cases: list[Case]) -> dict[str, object]:
    print(f"## Portfolio timings  ({len(cases)} in-envelope instances, "
          f"{len(LAG_LADDER)} rungs, seed {SEED_TRAIN})\n")
    rows: list[tuple[str, list[float], list[float]]] = []
    for rung in range(len(LAG_LADDER)):
        sub = [c for c in cases if c.rung == rung]
        npy = [_time(_reachable, c.nets, c.target, 3) for c in sub]
        rs = [_time(attest_fast.reachable, c.nets, c.target, 3) for c in sub]
        rows.append((f"rung {rung}", npy, rs))
    allnpy = [t for _, n, _ in rows for t in n]
    allrs = [t for _, _, r in rows for t in r]
    rows.append(("all rungs", allnpy, allrs))

    print(f"| {'slice':<10} | {'n':>4} | numpy p50 | numpy p95 | rust p50 | rust p95 | "
          f"p50 x | p95 x | total numpy | total rust |")
    print("|" + "|".join(["-" * 12, "-" * 6] + ["-" * 11] * 4 + ["-" * 7] * 2 + ["-" * 13] * 2)
          + "|")
    for name, npy, rs in rows:
        print(f"| {name:<10} | {len(npy):>4} | {_pct(npy, .5) * 1e3:>8.3f}ms | "
              f"{_pct(npy, .95) * 1e3:>8.3f}ms | {_pct(rs, .5) * 1e3:>7.3f}ms | "
              f"{_pct(rs, .95) * 1e3:>7.3f}ms | {_pct(npy, .5) / _pct(rs, .5):>6.1f} | "
              f"{_pct(npy, .95) / _pct(rs, .95):>6.1f} | {sum(npy):>10.3f}s  | "
              f"{sum(rs):>10.3f}s  |")

    print("\n### By hazard family (all rungs pooled)\n")
    print(f"| {'family':<22} | {'n':>4} | numpy p50 | rust p50 | p50 x |")
    print("|" + "|".join(["-" * 24, "-" * 6, "-" * 11, "-" * 10, "-" * 7]) + "|")
    fam_rows = []
    for fam in sorted({c.family for c in cases}):
        sub = [c for c in cases if c.family == fam]
        npy = [_time(_reachable, c.nets, c.target, 3) for c in sub]
        rs = [_time(attest_fast.reachable, c.nets, c.target, 3) for c in sub]
        print(f"| {fam:<22} | {len(sub):>4} | {_pct(npy, .5) * 1e3:>8.3f}ms | "
              f"{_pct(rs, .5) * 1e3:>7.3f}ms | {_pct(npy, .5) / _pct(rs, .5):>6.1f} |")
        fam_rows.append((fam, len(sub), _pct(npy, .5), _pct(rs, .5)))

    return {
        "numpy_total_s": sum(allnpy),
        "rust_total_s": sum(allrs),
        "p50_speedup": _pct(allnpy, .5) / _pct(allrs, .5),
        "families": fam_rows,
    }


def _report_crossover() -> dict[str, object]:
    """Smallest instance at which the extension is worth calling.

    Below some size the PyO3 boundary -- extracting a Python list into a Vec and
    building an ndarray on the way out -- costs more than the DP saves. That
    floor is the only reason not to wire the extension in unconditionally, so it
    is measured rather than assumed away.
    """
    print("\n## Crossover\n")
    print(f"| {'n':>5} | {'target':>9} | {'cells':>9} | numpy | rust | ratio |")
    print("|" + "|".join(["-" * 7, "-" * 11, "-" * 11, "-" * 10, "-" * 10, "-" * 8]) + "|")
    rng = np.random.default_rng(SEED_TRAIN)
    crossings: list[tuple[int, int, int]] = []
    for n in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, MAX_POOL):
        prev_ratio = 0.0
        for target in (100, 1_000, 10_000, 100_000, 1_000_000, MAX_TARGET_PAISE):
            nets = [int(x) for x in rng.integers(1, target + 1, size=n)]
            reps = 200 if n * target < 1_000_000 else 5
            npy = _time(_reachable, nets, target, reps)
            rs = _time(attest_fast.reachable, nets, target, reps)
            ratio = npy / rs
            print(f"| {n:>5} | {target:>9,} | {n * (target + 1):>9.2e} | {npy * 1e6:>7.1f}us | "
                  f"{rs * 1e6:>7.1f}us | {ratio:>6.2f} |")
            if prev_ratio < 1.0 <= ratio:
                crossings.append((n, target, n * (target + 1)))
            prev_ratio = ratio
    return {"crossings": crossings}


def _report_memory(cases: list[Case]) -> dict[str, object]:
    """Footprint at the p50 and p90 *pool* sizes the contract asks for.

    Pool size does not set the array length -- `target` does -- so the row is
    keyed on the settlement that sits at that pool percentile and reports its
    own credit. Reporting a footprint against a pool size alone would be a
    number with no instance behind it.
    """
    print("\n## Memory footprint\n")
    print(f"| {'slice':<18} | {'pool':>5} | {'target paise':>12} | packed 2-bit | "
          f"numpy live | numpy peak | saving |")
    print("|" + "|".join(["-" * 20, "-" * 7, "-" * 14, "-" * 14, "-" * 12, "-" * 12, "-" * 8])
          + "|")
    out: list[dict[str, object]] = []
    for rung in range(len(LAG_LADDER)):
        sub = sorted([c for c in cases if c.rung == rung], key=lambda c: len(c.nets))
        for tag, q in (("p50 pool", 0.50), ("p90 pool", 0.90)):
            c = sub[min(len(sub) - 1, int(q * len(sub)))]
            packed = attest_native.footprint_bytes(c.target)
            live = c.target + 1
            peak = NUMPY_PEAK_MULTIPLIER * (c.target + 1)
            print(f"| rung {rung} {tag:<11} | {len(c.nets):>5} | {c.target:>12,} | "
                  f"{packed / 1024:>10.1f} KiB | {live / 1024:>7.1f} KiB | "
                  f"{peak / 1024:>7.1f} KiB | {peak / packed:>5.1f}x |")
            out.append({"rung": rung, "tag": tag, "pool": len(c.nets), "target": c.target,
                        "packed": packed, "numpy_peak": peak})
    ceiling_packed = attest_native.footprint_bytes(MAX_TARGET_PAISE)
    ceiling_peak = NUMPY_PEAK_MULTIPLIER * (MAX_TARGET_PAISE + 1)
    print(f"| {'MAX_TARGET_PAISE':<18} | {MAX_POOL:>5} | {MAX_TARGET_PAISE:>12,} | "
          f"{ceiling_packed / 1024:>10.1f} KiB | {(MAX_TARGET_PAISE + 1) / 1024:>7.1f} KiB | "
          f"{ceiling_peak / 1024:>7.1f} KiB | {ceiling_peak / ceiling_packed:>5.1f}x |")
    return {"rows": out, "ceiling_packed": ceiling_packed, "ceiling_peak": ceiling_peak}


def main() -> int:
    if attest_fast.BACKEND != "rust":
        print("attest_fast.BACKEND is 'numpy'; nothing to compare. Run `maturin develop`.")
        return 1
    print(f"backend={attest_fast.BACKEND}  numpy={np.__version__}\n")
    cases = _portfolio()
    result = {
        "portfolio": _report_portfolio(cases),
        "crossover": _report_crossover(),
        "memory": _report_memory(cases),
    }
    Path(__file__).with_name("pybench.json").write_text(json.dumps(result, indent=1, default=str))
    print("\nwrote native/bench/pybench.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
