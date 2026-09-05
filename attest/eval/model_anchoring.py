"""Measure a real language model in the advisory slot. §47.

`attest/eval/anchoring.py` measures `batch_proposer`, the deterministic
stand-in: 27 correct of 63 resolved, silent on 94% of the 1,020 ambiguous cases
it exists for. The obvious objection to that number is that it measures a
30-line heuristic rather than a model, and therefore says nothing about what a
model would do.

This answers that objection with the same harness. Same seeds, same generator,
same solver, same scoring against the same ground truth. One thing differs: the
proposer is `advisors.groq_proposer`, which calls an actual model.

Whatever comes back is published. If the model resolves more, the loop has
earned a role it does not currently have. If it does not, the architecture's
claim stops being a statement about a placeholder and becomes a statement about
the real thing.

Written as a separate module and a separate artifact so that the existing
measurement and its methodology are untouched: this adds a column, it does not
edit one.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import asdict, dataclass, field

from attest.advisors import MODEL, AdvisorUnavailable, strict_proposer
from attest.generate.generator import build
from attest.hypothesis import investigate
from attest.model import BankCredit
from attest.pipeline import run
from attest.verdict import Verdict

ARTIFACT = pathlib.Path(__file__).resolve().parents[2] / "benchmark" / "model-anchoring.json"


@dataclass
class Tally:
    model: str = MODEL
    seeds: list[int] = field(default_factory=list)
    settlements_per_seed: int = 0
    ambiguous: int = 0
    resolved: int = 0
    correct: int = 0
    wrong: int = 0
    proposals: int = 0
    silent_cases: int = 0
    """Cases where the model offered nothing at all — the honest denominator."""
    seconds: float = 0.0

    @property
    def precision(self) -> float:
        return self.correct / self.resolved if self.resolved else 0.0

    @property
    def silent_share(self) -> float:
        """How often the model had NOTHING to say. Not the same as unresolved."""
        return self.silent_cases / self.ambiguous if self.ambiguous else 0.0

    @property
    def unresolved_share(self) -> float:
        """How often the loop ended without a PROVEN verdict, whatever the
        model said. The stand-in and the model are compared on this."""
        return (self.ambiguous - self.resolved) / self.ambiguous if self.ambiguous else 0.0


def measure(seeds: tuple[int, ...], n: int = 250, max_rounds: int = 3,
            limit: int | None = None, pause: float = 0.0) -> Tally:
    """Identical to eval.anchoring.measure, with one substitution.

    `limit` caps the number of ambiguous cases examined, for a shorter run on a
    rate-limited key. It is recorded in the artifact so a partial measurement
    can never be mistaken for the full one.
    """
    t = Tally(seeds=list(seeds), settlements_per_seed=n)
    propose = strict_proposer()
    t0 = time.time()
    seen = 0

    for seed in seeds:
        ds = build(n, seed=seed)
        _, pools, findings = run(ds.settlements, ds.orders)
        st = {x.settlement_id: x for x in ds.settlements}
        truth = {x.settlement_id: set(x.order_ids) for x in ds.truth}

        for f in findings:
            if f.verdict is not Verdict.AMBIGUOUS:
                continue
            if limit is not None and seen >= limit:
                break
            seen += 1
            t.ambiguous += 1
            s = st[f.settlement_id]
            credit = BankCredit(f"bank_{f.settlement_id}", s.settled_on,
                                s.net_paise, "NEFT-SETTLEMENT")
            try:
                out, trail = investigate(f, s, credit, pools.get(f.settlement_id, []),
                                         propose, max_rounds=max_rounds)
            except AdvisorUnavailable as e:
                # Abort rather than bank an empty answer as an opinion. A pilot
                # run recorded the model "silent on 100% of the work" when the
                # truth was eight consecutive 429s.
                raise SystemExit(
                    f"aborting after {t.ambiguous - 1} cases: the advisor became "
                    f"unavailable ({e}). No artifact written — a partial run "
                    f"where the model could not answer is not a measurement of "
                    f"the model.") from e
            proposals = sum(1 for e in trail.events if e["act"] == "propose")
            t.proposals += proposals
            if proposals == 0:
                t.silent_cases += 1
            if pause:
                time.sleep(pause)
            if out.verdict is not Verdict.PROVEN:
                continue
            t.resolved += 1
            if set(out.proofs[0].order_ids) == truth.get(f.settlement_id, set()):
                t.correct += 1
            else:
                t.wrong += 1

    t.seconds = round(time.time() - t0, 1)
    return t


def write(t: Tally, limit: int | None) -> None:
    d = asdict(t)
    d["precision"] = round(t.precision, 4)
    d["silent_share"] = round(t.silent_share, 4)
    d["unresolved_share"] = round(t.unresolved_share, 4)
    d["cases_examined_limit"] = limit
    d["note"] = (
        "The advisory slot filled by a real model instead of the deterministic "
        "stand-in, measured with the same harness, seeds, solver and ground "
        "truth as benchmark/anchoring.json. The proposer is the only difference."
    )
    ARTIFACT.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")


def render(t: Tally) -> str:
    w = 78
    return "\n".join([
        "=" * w,
        f"  A MODEL IN THE ADVISORY SLOT  ·  {t.model}",
        "-" * w,
        f"  ambiguous cases examined   {t.ambiguous:>8}",
        f"  the model proposed at all  {t.ambiguous - t.silent_cases:>8}",
        f"  silent (nothing to say)    {t.silent_cases:>8}   {t.silent_share:>7.1%}",
        f"  ended unresolved           {t.ambiguous - t.resolved:>8}   {t.unresolved_share:>7.1%}",
        f"  resolved to PROVEN         {t.resolved:>8}",
        f"    correct                  {t.correct:>8}",
        f"    WRONG                    {t.wrong:>8}",
        f"  precision when it resolved {t.precision:>8.3f}",
        f"  proposals issued           {t.proposals:>8}",
        f"  seconds                    {t.seconds:>8.1f}",
        "=" * w,
    ])


def main() -> None:
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set; refusing to report a measurement "
                         "of a proposer that cannot run.")
    limit = int(os.environ["MODEL_LIMIT"]) if os.environ.get("MODEL_LIMIT") else None
    seeds = tuple(int(s) for s in os.environ.get("MODEL_SEEDS", "555001,999983").split(","))
    pause = float(os.environ.get("MODEL_PAUSE", "0"))
    t = measure(seeds, limit=limit, pause=pause)
    write(t, limit)
    print(render(t))
    print(f"  written to {ARTIFACT}")


if __name__ == "__main__":
    main()
