"""Evaluation harness.

Written before the interesting algorithm, on purpose. A matcher built first and
measured second gets tuned, unconsciously, until the benchmark agrees with it.

Three things this reports that a percentage alone hides:

* **blocking_recall** -- the ceiling. Pairs discarded in layer 0 are unreachable
  by every later layer, so final recall must always be read against this.
* **per-case accuracy** -- attributes misses to a named hazard rather than to a
  number, which is the difference between "94%" and an engineering claim.
* **rupee coverage** -- a settlement is not worth its row count. Matching 94% of
  settlements while missing the large ones is a worse outcome that scores the
  same on accuracy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from attest.model import Order, Settlement, TrueMatch


@dataclass
class Prediction:
    """One settlement's proposed explanation.

    `order_ids is None` means *declined*, which is a first-class outcome and not
    a failure: a decline routes to a human, a wrong match moves money.
    """

    settlement_id: str
    order_ids: list[str] | None
    layer: str
    reason: str = ""


@dataclass
class Report:
    n_settlements: int
    exact_sets: int
    declined: int
    wrong: int
    pair_tp: int
    pair_fp: int
    pair_fn: int
    rupees_total: int
    rupees_explained: int
    blocking_recall: float
    by_case: dict[str, tuple[int, int]] = field(default_factory=dict)
    by_layer: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def set_accuracy(self) -> float:
        return self.exact_sets / self.n_settlements

    @property
    def precision(self) -> float:
        d = self.pair_tp + self.pair_fp
        return self.pair_tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.pair_tp + self.pair_fn
        return self.pair_tp / d if d else 0.0

    def render(self, title: str) -> str:
        w = 62
        out = [f"\n{title}", "=" * w]
        out.append(f"  settlements            {self.n_settlements:>10,}")
        out.append(f"  exact set match        {self.exact_sets:>10,}   {self.set_accuracy:6.1%}")
        out.append(f"  declined (to human)    {self.declined:>10,}   {self.declined/self.n_settlements:6.1%}")
        out.append(f"  WRONG (moved money)    {self.wrong:>10,}   {self.wrong/self.n_settlements:6.1%}")
        out.append("-" * w)
        out.append(f"  pair precision         {self.precision:>10.3f}")
        out.append(f"  pair recall            {self.recall:>10.3f}")
        out.append(f"  blocking recall (ceil) {self.blocking_recall:>10.3f}")
        out.append("-" * w)
        out.append(f"  rupees explained       {self.rupees_explained/100:>13,.0f} "
                   f"of {self.rupees_total/100:,.0f}   "
                   f"{self.rupees_explained/self.rupees_total:5.1%}")
        out.append(f"  wall clock             {self.seconds:>10.2f}s")
        if self.by_layer:
            out.append("-" * w)
            for layer, n in sorted(self.by_layer.items(), key=lambda kv: -kv[1]):
                out.append(f"  resolved by {layer:<18s} {n:>6,}   {n/self.n_settlements:6.1%}")
        if self.by_case:
            out.append("-" * w)
            out.append(f"  {'hazard':<24s} {'n':>6s} {'exact':>8s}")
            for case, (hit, n) in sorted(self.by_case.items(), key=lambda kv: kv[1][0]/kv[1][1]):
                out.append(f"  {case:<24s} {n:>6,} {hit/n:>8.1%}")
        return "\n".join(out) + "\n"


def evaluate(
    settlements: list[Settlement],
    truth: list[TrueMatch],
    preds: list[Prediction],
    pools: dict[str, list[Order]],
    seconds: float = 0.0,
) -> Report:
    truth_by_id = {t.settlement_id: t for t in truth}
    pred_by_id = {p.settlement_id: p for p in preds}
    settle_by_id = {s.settlement_id: s for s in settlements}

    exact = declined = wrong = 0
    tp = fp = fn = 0
    rupees_ok = 0
    by_case: dict[str, list[int]] = {}
    by_layer: dict[str, int] = {}

    # Ceiling imposed by layer 0: true pairs whose order survived blocking.
    reachable = total_pairs = 0

    for t in truth:
        pool_ids = {o.order_id for o in pools.get(t.settlement_id, ())}
        total_pairs += len(t.order_ids)
        reachable += sum(1 for oid in t.order_ids if oid in pool_ids)

        slot = by_case.setdefault(t.case, [0, 0])
        slot[1] += 1

        p = pred_by_id.get(t.settlement_id)
        actual = set(t.order_ids)

        if p is None or p.order_ids is None:
            declined += 1
            fn += len(actual)
            continue

        by_layer[p.layer] = by_layer.get(p.layer, 0) + 1
        got = set(p.order_ids)
        tp += len(got & actual)
        fp += len(got - actual)
        fn += len(actual - got)

        if got == actual:
            exact += 1
            slot[0] += 1
            rupees_ok += settle_by_id[t.settlement_id].net_paise
        else:
            wrong += 1

    return Report(
        n_settlements=len(truth),
        exact_sets=exact,
        declined=declined,
        wrong=wrong,
        pair_tp=tp, pair_fp=fp, pair_fn=fn,
        rupees_total=sum(s.net_paise for s in settlements),
        rupees_explained=rupees_ok,
        blocking_recall=reachable / total_pairs if total_pairs else 0.0,
        by_case={k: (v[0], v[1]) for k, v in by_case.items()},
        by_layer=by_layer,
        seconds=seconds,
    )


class Timer:
    def __enter__(self) -> "Timer":
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.perf_counter() - self.t0
