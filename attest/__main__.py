"""CLI: `python -m attest baseline`."""

from __future__ import annotations

import sys
from pathlib import Path

from attest.eval.harness import Timer, evaluate
from attest.generate.generator import build
from attest.pipeline import run

DATA = Path(__file__).resolve().parent.parent / "data"

#: Frozen on D1. The held-out seed is intended to be run exactly once, at the end.
SEED_TRAIN = 20260821
SEED_HOLDOUT = 900913


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 250
    holdout = "--holdout" in argv

    if "--changed" in argv:
        # Yesterday's run against today's. Simulated by withholding a fraction of
        # orders from the earlier run, which is the real scenario: refunds land
        # late, chargebacks arrive weeks after capture, exports get re-pulled.
        import random

        from attest.whatchanged import diff
        ds = build(n, seed=SEED_TRAIN)
        rng = random.Random(7)
        late = {o.order_id for o in ds.orders if rng.random() < 0.06}
        print(f"\n  yesterday {len(ds.orders) - len(late):,} orders · "
              f"today {len(ds.orders):,} · {len(late)} arrived late")
        _, pb, fb = run(ds.settlements,
                        [o for o in ds.orders if o.order_id not in late])
        _, pa, fa = run(ds.settlements, ds.orders)
        print(diff(fb, fa, pb, pa,
                   {s.settlement_id: s for s in ds.settlements}).render())
        return 0

    if "--sweep" in argv:
        from attest.eval.sweep import sweep
        print(sweep(n).render())
        return 0

    seed = SEED_HOLDOUT if holdout else SEED_TRAIN
    ds = build(n, seed=seed)
    ds.write(DATA / ("holdout" if holdout else "train"))

    with Timer() as t:
        preds, pools, findings = run(ds.settlements, ds.orders)
    rep = evaluate(ds.settlements, ds.truth, preds, pools, t.elapsed)

    if "--html" in argv:
        from attest.eval.report import render
        out = DATA.parent / "report.html"
        out.write_text(render(rep, findings, ds.settlements, ds.orders, seed))
        print(f"  wrote {out}")

    label = "HELD-OUT" if holdout else "TRAIN"
    from collections import Counter
    print(rep.render(f"ATTEST  ·  D3 cascade  ·  {label}  ·  seed {seed}"))
    print("  verdicts: " + "  ".join(
        f"{v}={n}" for v, n in Counter(f.verdict.value for f in findings).most_common()))
    print(f"  orders consumed by proofs: {sum(len(f.proofs[0].order_ids) for f in findings if f.postable):,}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
