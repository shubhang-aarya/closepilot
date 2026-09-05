"""Measure ATTEST against the baselines under identical conditions. §31.

The comparison existed in two markdown files and in no artifact anything could
read, which meant the Trust surface would have had to transcribe it — the exact
practice §6 forbids and the one that let D22's precision sit unchallenged for
six days. This runs all four methods over the SAME generated datasets and scores
every one of them through the SAME `evaluate`, so the conditions are identical
by construction rather than by assertion.

A baseline is not a strawman here. `exact_only` is what most reconciliation
tooling actually does; `greedy` is the obvious first idea for subset-sum and the
one a reviewer will ask why you did not use. Their numbers are reported whatever
they say.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from attest.eval.baselines import exact_only, fuzzy, greedy
from attest.eval.harness import evaluate
from attest.generate.generator import build
from attest.pipeline import run as attest_run

RESULTS = Path(__file__).resolve().parent.parent.parent / "benchmark" / "baselines.json"

#: The same seeds the main benchmark evaluates on, so the two artifacts describe
#: the same portfolios rather than two different ones that happen to agree.
SEEDS = (555001, 999983)


def measure(n: int = 250, seeds: tuple[int, ...] = SEEDS) -> dict[str, object]:
    methods: dict[str, dict[str, float | int]] = {}

    def acc(name: str, rep, seconds: float) -> None:
        m = methods.setdefault(name, {
            "settlements": 0, "exact_sets": 0, "wrong": 0, "declined": 0,
            "pair_tp": 0, "pair_fp": 0, "pair_fn": 0, "seconds": 0.0})
        m["settlements"] += rep.n_settlements
        m["exact_sets"] += rep.exact_sets
        m["wrong"] += rep.wrong
        m["declined"] += rep.declined
        m["pair_tp"] += rep.pair_tp
        m["pair_fp"] += rep.pair_fp
        m["pair_fn"] += rep.pair_fn
        m["seconds"] += seconds

    for seed in seeds:
        ds = build(n, seed=seed)

        t = time.time()
        preds, pools, _ = attest_run(ds.settlements, ds.orders, cores=True)
        acc("attest", evaluate(ds.settlements, ds.truth, preds, pools), time.time() - t)

        for name, fn in (("exact_only", exact_only), ("fuzzy", fuzzy),
                         ("greedy", greedy)):
            t = time.time()
            p = fn(ds.settlements, ds.orders)
            acc(name, evaluate(ds.settlements, ds.truth, p, pools), time.time() - t)

    for m in methods.values():
        decided = m["settlements"] - m["declined"]
        m["coverage"] = round(m["exact_sets"] / max(m["settlements"], 1), 4)
        m["decided"] = decided
        # Of the answers a method actually gave, how many were wrong. A method
        # that declines everything has no false proofs and no value, which is
        # why coverage is reported beside it rather than instead of it.
        m["false_proof_rate"] = round(m["wrong"] / max(decided, 1), 4)
        m["pair_precision"] = round(
            m["pair_tp"] / max(m["pair_tp"] + m["pair_fp"], 1), 4)
        m["seconds"] = round(m["seconds"], 2)

    return {
        "seeds": list(seeds), "settlements_per_seed": n,
        "settlements": n * len(seeds),
        "methods": methods,
        "note": ("Every method saw the same generated portfolios and was scored "
                 "by the same evaluator. Coverage and false-proof rate are "
                 "reported together because either alone is easy to win: "
                 "declining everything gives a perfect error rate."),
    }


def main() -> int:
    d = measure()
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    w = 74
    print("\nBASELINE PANEL · identical datasets, identical scoring")
    print("=" * w)
    print(f"  {'method':<14s}{'coverage':>10s}{'decided':>10s}{'wrong':>8s}"
          f"{'false proof':>14s}{'pair prec':>12s}")
    for name in ("attest", "exact_only", "fuzzy", "greedy"):
        m = d["methods"][name]
        print(f"  {name:<14s}{m['coverage'] * 100:>9.1f}%{m['decided']:>10}"
              f"{m['wrong']:>8}{m['false_proof_rate'] * 100:>13.1f}%"
              f"{m['pair_precision'] * 100:>11.1f}%")
    print("=" * w)
    print(f"  {d['settlements']} settlements over seeds {d['seeds']}")
    print(f"  written to {RESULTS}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
