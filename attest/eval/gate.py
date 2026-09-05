"""Regression gates. §49, §50.

    The optimization target is not MAXIMUM MATCHES.
    It is MAXIMUM SAFE RESOLUTION.

So the build fails on safety, not on accuracy. Exact-set match may fall without
consequence; the false-proof rate may not rise, and money wrongly auto-posted may
not rise at all.

**The asymmetry is the entire policy.** A gate that failed on any regression
would make every honest measurement a build break, and the project has recorded
three occasions where the correct move was to accept less coverage for less risk
— D4, D8, D12. A gate that punished those would have argued for shipping them.

Two things this deliberately does NOT do.

It does not fail on a *single* seed. D7 cost six days to a figure that held on
one draw, so every comparison is over the pooled panel.

It does not auto-update the baseline. A gate that rewrites its own reference on
pass is a gate that ratchets quietly in whichever direction the last change went;
accepting a new baseline is a decision a person makes and a commit records.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from attest.eval.benchmark import RESULTS, benchmark
from attest.eval.metrics import write_source_of_truth

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "benchmark" / "baseline.json"


@dataclass(frozen=True)
class Gate:
    key: str
    label: str
    direction: str
    """'lower_is_better' or 'higher_is_better'."""
    tolerance: float
    fatal: bool
    why: str


#: Ordered by how much a breach matters, not alphabetically — a reader scanning
#: output should hit the important failure first.
GATES: tuple[Gate, ...] = (
    Gate("incorrectly_auto_posted_paise", "money wrongly auto-posted",
         "lower_is_better", 0.0, True,
         "the only number that moves a merchant's money in the wrong direction; "
         "no tolerance at all"),
    Gate("false_proof_rate", "false proof rate", "lower_is_better", 0.0, True,
         "a claim of proof that was wrong; the engine's central promise"),
    Gate("proof_precision", "proof precision", "higher_is_better", 0.01, True,
         "right when it claims to be sure; a point of slack for panel noise"),
    Gate("safe_resolution_rate", "safe resolution rate", "higher_is_better",
         0.05, False,
         "coverage without a human. Advisory: three documented decisions traded "
         "coverage for safety on purpose (D4, D8, D12) and a gate that punished "
         "them would have argued for shipping them"),
    Gate("exact_set_recovery", "exact set recovery", "higher_is_better", 0.05,
         False,
         "how often the engine recovers the true order set exactly. Advisory "
         "for the same reason as coverage: it is the number a change trades "
         "away when it buys safety, so a fatal gate here would argue against "
         "every refusal in the log"),
    Gate("accounted_rate", "value accounted for", "higher_is_better", 0.05, False,
         "proven value plus the undisputed part of ambiguity — the share of "
         "the book a merchant can act on. Advisory because it moves with "
         "portfolio density rather than with correctness"),
)


@dataclass
class Result:
    gate: Gate
    before: float
    after: float
    ok: bool

    @property
    def delta(self) -> float:
        return self.after - self.before

    def line(self) -> str:
        mark = "PASS" if self.ok else ("FAIL" if self.gate.fatal else "WARN")
        fmt = ((lambda v: f"{v:,.0f}") if "paise" in self.gate.key
               else (lambda v: f"{v:.4f}"))
        arrow = "→"
        return (f"  {mark:<5s} {self.gate.label:<28s}"
                f"{fmt(self.before):>12s} {arrow} {fmt(self.after):<12s}"
                f"{self.delta:+.4f}" if "paise" not in self.gate.key else
                f"  {mark:<5s} {self.gate.label:<28s}"
                f"{fmt(self.before):>12s} {arrow} {fmt(self.after):<12s}"
                f"{self.delta:+,.0f}")


def compare(before: dict[str, object], after: dict[str, object]) -> list[Result]:
    out = []
    for g in GATES:
        b = float(before.get(g.key, 0) or 0)
        a = float(after.get(g.key, 0) or 0)
        ok = (a <= b + g.tolerance if g.direction == "lower_is_better"
              else a >= b - g.tolerance)
        out.append(Result(g, b, a, ok))
    return out


def run(n: int = 250, update: bool = False) -> int:
    payload = benchmark(n)
    after = payload["pooled"]

    # Gating is READ-ONLY unless asked otherwise. This used to overwrite
    # benchmark/results.json on every run, and results.json is what generates
    # the figures in README — so simply checking the gates republished the
    # project's headline numbers as a side effect.
    #
    # That matters because the numbers depend on the execution path. On a clean
    # machine with no Rust extension the numpy kernel has a narrower envelope
    # and "value accounted for" measures 22.7% against the 66.7% the committed
    # artifact records. A gate run there would have rewritten README to the
    # numpy figures without anyone asking, which is the drift D13 recorded
    # arriving through the door marked "verification".
    #
    # Refreshing the published numbers is now deliberate: --update.
    if update:
        write_source_of_truth(RESULTS, payload)

    if not BASELINE.exists():
        write_source_of_truth(BASELINE, payload)
        print(f"\n  no baseline; wrote {BASELINE.relative_to(ROOT)} from this run.")
        print("  commit it — a baseline that is not in version control is not a "
              "baseline.\n")
        return 0

    before = json.loads(BASELINE.read_text())["pooled"]
    results = compare(before, after)

    w = 78
    print(f"\nREGRESSION GATES · pooled over {len(payload['evaluation_seeds'])} "
          f"held-out seeds × {n}")
    print("=" * w)
    for r in results:
        print(r.line())
    print("=" * w)

    fatal = [r for r in results if not r.ok and r.gate.fatal]
    warn = [r for r in results if not r.ok and not r.gate.fatal]

    for r in fatal:
        print(f"\n  FAIL · {r.gate.label}\n        {r.gate.why}")
    for r in warn:
        print(f"\n  WARN · {r.gate.label}\n        {r.gate.why}")

    if fatal:
        print("\n  Safety regressed. The target is maximum SAFE resolution, not "
              "maximum matches.\n")
        return 1

    if warn:
        print("\n  Coverage fell and safety held. That is an allowed trade and "
              "the reason these gates are advisory.\n")

    if update:
        write_source_of_truth(BASELINE, payload)
        print(f"  baseline and results updated — commit "
              f"{BASELINE.relative_to(ROOT)} and {RESULTS.relative_to(ROOT)}.\n")
    else:
        print("  All safety gates held.\n")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    n = next((int(a) for a in args if a.isdigit()), 250)
    raise SystemExit(run(n, update="--update" in args))
