"""D5 measurement: the CP-SAT set packing in `attest/partition.py` against the
greedy cascade that ships in `attest/pipeline.py`.

Runs the plan written into `hive/reports/attest-cpsat.md`: five seeds at n=250
plus n=1200 on the train seed, reporting WRONG as a pooled rate with the
per-seed spread. WRONG is a 0-or-1-event metric at n=250 -- the engine itself
scores 0,0,1,2,2 over those seeds -- so a single-seed delta is noise and is not
reported as anything else here.

`PYTHONHASHSEED` must be pinned: `blocking._capture_dates_for` returns a
`set[date]`, and the engine's pool order (unlike `partition.collect`'s, which
sorts) inherits that iteration order. Without the pin the *baseline* moves
between runs.

    PYTHONHASHSEED=0 ./.venv/bin/python -m eval.cpsat_study 250 20260821

Results land as JSON in `data/cpsat/` one seed at a time, so a run that dies
half way still leaves the seeds it finished on disk.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from attest.eval.harness import Prediction, Report, evaluate
from attest.generate.generator import build
from attest.model import Settlement, TrueMatch
from attest.partition import pack
from attest.pipeline import run

OUT = Path(__file__).resolve().parent.parent / "data" / "cpsat"


def _outcomes(truth: list[TrueMatch], preds: list[Prediction]) -> dict[str, str]:
    """Per settlement: EXACT, WRONG, or DECLINED.

    The aggregate deltas say how much changed; this says *which* settlements
    changed hands, which is the only part of the comparison a human can act on.
    """
    by_id = {p.settlement_id: p for p in preds}
    out: dict[str, str] = {}
    for t in truth:
        p = by_id.get(t.settlement_id)
        if p is None or p.order_ids is None:
            out[t.settlement_id] = "DECLINED"
        elif set(p.order_ids) == set(t.order_ids):
            out[t.settlement_id] = "EXACT"
        else:
            out[t.settlement_id] = "WRONG"
    return out


def _summary(r: Report) -> dict[str, object]:
    return {
        "n": r.n_settlements,
        "exact": r.exact_sets,
        "exact_pct": round(100 * r.set_accuracy, 2),
        "declined": r.declined,
        "wrong": r.wrong,
        "pair_tp": r.pair_tp,
        "pair_fp": r.pair_fp,
        "pair_fn": r.pair_fn,
        "precision": round(r.precision, 4),
        "recall": round(r.recall, 4),
        "blocking_recall": round(r.blocking_recall, 4),
        "rupees_pct": round(100 * r.rupees_explained / r.rupees_total, 2),
        "seconds": round(r.seconds, 2),
    }


def _quantiles(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {}
    s = sorted(xs)
    def q(p: float) -> float:
        return s[min(len(s) - 1, int(p * len(s)))]
    return {
        "n_calls": len(s),
        "min_ms": round(1000 * s[0], 2),
        "median_ms": round(1000 * statistics.median(s), 2),
        "p90_ms": round(1000 * q(0.90), 2),
        "p99_ms": round(1000 * q(0.99), 2),
        "max_ms": round(1000 * s[-1], 2),
        "total_s": round(sum(s), 2),
    }


def measure(n: int, seed: int, extract_cores: bool = True) -> dict[str, object]:
    ds = build(n, seed=seed)
    settle_by_id: dict[str, Settlement] = {s.settlement_id: s for s in ds.settlements}

    t0 = time.perf_counter()
    preds, pools, findings = run(ds.settlements, ds.orders)
    base_s = time.perf_counter() - t0
    base = evaluate(ds.settlements, ds.truth, preds, pools, base_s)

    t0 = time.perf_counter()
    pr = pack(ds.settlements, ds.orders, extract_cores=extract_cores)
    pack_s = time.perf_counter() - t0
    strict = evaluate(ds.settlements, ds.truth, pr.preds_strict, pr.pools, pack_s)
    opt = evaluate(ds.settlements, ds.truth, pr.preds_optimistic, pr.pools, pack_s)

    ob = _outcomes(ds.truth, preds)
    os_ = _outcomes(ds.truth, pr.preds_strict)
    case_by_id = {t.settlement_id: t.case for t in ds.truth}

    changed = [
        {
            "settlement_id": sid,
            "greedy": ob[sid],
            "cpsat": os_[sid],
            "case": case_by_id[sid],
            "rupees": settle_by_id[sid].net_paise // 100,
        }
        for sid in sorted(ob) if ob[sid] != os_[sid]
    ]

    rec = {
        "n": n,
        "seed": seed,
        "extract_cores": extract_cores,
        "greedy": _summary(base),
        "cpsat_strict": _summary(strict),
        "cpsat_optimistic": _summary(opt),
        "cpsat_candidate_seconds": round(pr.candidate_seconds, 2),
        "cpsat_solve_seconds": round(pr.solve_seconds, 2),
        "solve_time_dist": _quantiles(pr.solve_times),
        "component_hist": pr.size_histogram(),
        "component_max": max(pr.component_sizes) if pr.component_sizes else 0,
        "component_count": len(pr.component_sizes),
        "cores": pr.core_count,
        "changed": changed,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"n{n}_seed{seed}.json").write_text(json.dumps(rec, indent=2))
    return rec


def _line(tag: str, d: dict[str, object]) -> str:
    return (f"  {tag:<18s} exact {d['exact']:>4}/{d['n']} ({d['exact_pct']:>5.1f}%)  "
            f"WRONG {d['wrong']:>3}  declined {d['declined']:>4}  "
            f"prec {d['precision']:.3f}  {d['seconds']:>8.2f}s")


def main(argv: list[str]) -> int:
    n = int(argv[1]) if len(argv) > 1 else 250
    seed = int(argv[2]) if len(argv) > 2 else 20260821
    no_cores = "--no-cores" in argv
    rec = measure(n, seed, extract_cores=not no_cores)
    print(f"\nn={n} seed={seed}")
    print(_line("greedy cascade", rec["greedy"]))
    print(_line("cpsat strict", rec["cpsat_strict"]))
    print(_line("cpsat optimistic", rec["cpsat_optimistic"]))
    print(f"  components {rec['component_count']} max {rec['component_max']} "
          f"{rec['component_hist']}")
    print(f"  solve-time {rec['solve_time_dist']}")
    print(f"  cores {rec['cores']}  changed {len(rec['changed'])}")
    for c in rec["changed"]:
        print(f"    {c['settlement_id']}  {c['greedy']:>8s} -> {c['cpsat']:<8s} "
              f"{c['case']:<22s} Rs {c['rupees']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
