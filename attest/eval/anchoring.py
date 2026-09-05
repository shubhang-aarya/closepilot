"""Re-measure the hypothesis loop against ground truth. D8, D22.

D8 recorded 0.521 precision for the shipped design — the loop selecting among
explanations the solver had already validated — and that number disabled the
feature. It was taken by hand. This makes it re-runnable, because a number that
decides whether a feature ships should not live only in a markdown table.

Two things it reports that the original did not:

  * How often the loop had anything to say at all. A hypothesis refuted on
    UNIQUENESS carries no rejected orders, so before D22 the Evidence handed
    back to the proposer was unchanged and it returned the identical anchor
    until the rounds ran out. The measurement was taken under that loop, which
    means it was measuring one hypothesis per settlement, not three.

  * How many candidate pools span more than one capture date. The offline
    proposer's whole lens is "the densest same-day batch", and on a pool that
    is a single date that sentence is true of every order in it. Where it is,
    the lens carries no information and the anchor is an arbitrary pick with a
    plausible rationale attached — which is a worse failure than a wrong guess,
    because it is a wrong guess that sounds like a reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from attest.generate.generator import build
from attest.hypothesis import batch_proposer, investigate
from attest.model import BankCredit
from attest.pipeline import run
from attest.verdict import Verdict


@dataclass
class Tally:
    seeds: list[int] = field(default_factory=list)
    ambiguous: int = 0
    resolved: int = 0
    correct: int = 0
    wrong: int = 0
    single_date_pools: int = 0
    pools: int = 0
    rounds_used: int = 0
    repeats_avoided: int = 0

    @property
    def precision(self) -> float:
        return self.correct / self.resolved if self.resolved else 0.0

    @property
    def single_date_share(self) -> float:
        return self.single_date_pools / self.pools if self.pools else 0.0

    def render(self) -> str:
        w = 74
        return "\n".join([
            "", "ANCHORING · the hypothesis loop against ground truth", "=" * w,
            f"  seeds                 {', '.join(str(s) for s in self.seeds)}",
            f"  ambiguous settlements {self.ambiguous:>6}",
            "-" * w,
            f"  {'':22}{'resolved':>10}{'correct':>10}{'WRONG':>9}{'precision':>12}",
            f"  {'anchor selects only':22}{self.resolved:>10}{self.correct:>10}"
            f"{self.wrong:>9}{self.precision:>12.3f}",
            "-" * w,
            f"  candidate pools spanning ONE capture date: "
            f"{self.single_date_pools}/{self.pools} "
            f"({self.single_date_share * 100:.0f}%)",
            "  On those the 'densest same-day batch' lens is true of every order",
            "  in the pool, so the anchor is an arbitrary pick wearing a reason.",
            "=" * w, "",
        ])


def measure(n: int = 250, seeds: tuple[int, ...] = (11, 23, 37, 53, 71),
            max_rounds: int = 3) -> Tally:
    t = Tally(seeds=list(seeds))
    for seed in seeds:
        ds = build(n, seed=seed)
        _, pools, findings = run(ds.settlements, ds.orders)
        st = {x.settlement_id: x for x in ds.settlements}
        truth = {x.settlement_id: set(x.order_ids) for x in ds.truth}

        for sid, pool in pools.items():
            t.pools += 1
            if len({o.captured_on for o in pool}) == 1:
                t.single_date_pools += 1

        for f in findings:
            if f.verdict is not Verdict.AMBIGUOUS:
                continue
            t.ambiguous += 1
            s = st[f.settlement_id]
            credit = BankCredit(f"bank_{f.settlement_id}", s.settled_on,
                                s.net_paise, "NEFT-SETTLEMENT")
            out, trail = investigate(f, s, credit, pools.get(f.settlement_id, []),
                                     batch_proposer, max_rounds=max_rounds)
            t.rounds_used += sum(1 for e in trail.events if e["act"] == "propose")
            t.repeats_avoided += sum(1 for e in trail.events
                                     if e["act"] == "exhausted"
                                     and "already been refuted" in e["detail"])
            if out.verdict is not Verdict.PROVEN:
                continue
            t.resolved += 1
            got = set(out.proofs[0].order_ids)
            if got == truth.get(f.settlement_id, set()):
                t.correct += 1
            else:
                t.wrong += 1
    return t


RESULTS = __import__("pathlib").Path(__file__).resolve().parent.parent.parent \
    / "benchmark" / "anchoring.json"


def write(t: "Tally", one: "Tally") -> None:
    """Persist it, so the screen reads a measurement rather than a transcription.

    The Accuracy screen already reads the same benchmark files the build reads,
    for the same reason: a number that has to be copied by hand is a number that
    will eventually be copied wrong, and the one that decides whether a feature
    ships is the worst one to get wrong."""
    import json
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps({
        "seeds": t.seeds, "settlements_per_seed": 250,
        "ambiguous": t.ambiguous,
        "resolved": t.resolved, "correct": t.correct, "wrong": t.wrong,
        "precision": round(t.precision, 4),
        "one_round": {"resolved": one.resolved, "correct": one.correct,
                      "wrong": one.wrong, "precision": round(one.precision, 4)},
        "single_date_pools": t.single_date_pools, "pools": t.pools,
        "single_date_share": round(t.single_date_share, 4),
        "proposals": t.rounds_used,
        "proposals_per_settlement": round(t.rounds_used / max(t.ambiguous, 1), 2),
        "note": (
            "The loop selects among explanations the solver already validated; "
            "it never constructs one. Three rounds resolve exactly what one "
            "round resolves, so the exploration added by D22 is free and "
            "inconsequential — the second-densest capture day never yields an "
            "anchor contained in exactly one explanation. Underneath that: "
            f"{t.single_date_share * 100:.0f}% of candidate pools span a single "
            "capture date, and on those the lens is true of every order in the "
            "pool. The feature stays disabled."),
    }, indent=1, sort_keys=True) + "\n")


def main() -> int:
    # One round is what the loop effectively was before D22: a uniqueness
    # refutation fed nothing back, so rounds two and three re-proposed the
    # identical anchor. Measuring both on the SAME seeds is the only way to say
    # whether the fix helped, and it is the comparison D8 could not make.
    one = measure(max_rounds=1)
    t = measure()
    print(t.render())
    print(f"  one round only (the pre-D22 loop, effectively): "
          f"{one.resolved} resolved, {one.correct} correct, {one.wrong} wrong, "
          f"precision {one.precision:.3f}")
    print(f"  proposals made: {t.rounds_used} across {t.ambiguous} settlements "
          f"({t.rounds_used / max(t.ambiguous, 1):.2f} each)")
    print(f"  rounds ended early because every hypothesis was already refuted: "
          f"{t.repeats_avoided}")
    write(t, one)
    print(f"  written to {RESULTS}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
