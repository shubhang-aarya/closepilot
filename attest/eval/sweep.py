"""Multi-seed evaluation.

A single seed is an anecdote. The engine was reported at precision 1.000 for six
days on the strength of seed 20260821 alone, and an adversarial sweep found that
four other seeds produce 0, 1, 2 and 2 false proofs — so the headline was a
property of one portfolio, not of the engine.

Every claim about the engine is now made across a seed panel, and the aggregate
is POOLED rather than averaged: a mean of per-seed precisions weights a
250-settlement run identically to a 1,200-settlement one and quietly flatters
whichever happened to be small. Pooling counts pairs.

The panel is fixed. Adding a seed because the numbers came out badly is the same
mistake in a different costume.
"""

from __future__ import annotations

from dataclasses import dataclass

from attest.eval.harness import Report, Timer, evaluate
from attest.generate.generator import build
from attest.pipeline import run

#: Fixed panel. The first is the development seed; the rest were chosen before
#: any of them was run, and none has been swapped since.
PANEL: tuple[int, ...] = (20260821, 314159, 271828, 555001, 999983)


@dataclass
class Sweep:
    per_seed: dict[int, Report]

    @property
    def settlements(self) -> int:
        return sum(r.n_settlements for r in self.per_seed.values())

    @property
    def wrong(self) -> int:
        return sum(r.wrong for r in self.per_seed.values())

    @property
    def exact(self) -> float:
        return sum(r.exact_sets for r in self.per_seed.values()) / self.settlements

    @property
    def precision(self) -> float:
        tp = sum(r.pair_tp for r in self.per_seed.values())
        fp = sum(r.pair_fp for r in self.per_seed.values())
        return tp / (tp + fp) if tp + fp else 0.0

    @property
    def worst_wrong(self) -> tuple[int, int]:
        s = max(self.per_seed, key=lambda k: self.per_seed[k].wrong)
        return s, self.per_seed[s].wrong

    def render(self) -> str:
        w = 58
        out = [f"\nSEED PANEL · {len(self.per_seed)} seeds × "
               f"{next(iter(self.per_seed.values())).n_settlements} settlements", "=" * w,
               f"  {'seed':<12s}{'exact':>9s}{'WRONG':>8s}{'precision':>12s}{'time':>10s}"]
        for seed, r in self.per_seed.items():
            out.append(f"  {seed:<12d}{r.set_accuracy:>8.1%}{r.wrong:>8d}"
                       f"{r.precision:>12.3f}{r.seconds:>9.2f}s")
        out.append("-" * w)
        out.append(f"  {'POOLED':<12s}{self.exact:>8.1%}{self.wrong:>8d}"
                   f"{self.precision:>12.3f}")
        ws, wn = self.worst_wrong
        out.append(f"  worst seed {ws} — {wn} false proof(s)")
        out.append("")
        out.append("  A single seed is an anecdote. Report the pooled figure and")
        out.append("  the worst seed; never the best one.")
        return "\n".join(out) + "\n"


def sweep(n: int, seeds: tuple[int, ...] = PANEL) -> Sweep:
    per: dict[int, Report] = {}
    for seed in seeds:
        ds = build(n, seed=seed)
        with Timer() as t:
            preds, pools, _ = run(ds.settlements, ds.orders)
        per[seed] = evaluate(ds.settlements, ds.truth, preds, pools, t.elapsed)
    return Sweep(per)
