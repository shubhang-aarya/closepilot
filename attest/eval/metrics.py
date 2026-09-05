"""The metric model. §5, §6, §46, §60.

One number cannot describe this engine, and pretending otherwise would be the
most consequential dishonesty available to it. In particular:

    18.5% exact set recovery  +  98.1% proof precision
      is NOT
    "98.1% accurate reconciliation"

The first says how often the engine recovers a complete ground-truth set. The
second says how often it is right *when it claims to be sure*. They measure
different things and a product that blends them is selling the second number
while doing the work of the first.

So the vocabulary is deliberately plural, and the two that matter most are not
rates at all:

**False proof rate** — how often a claim of PROVEN is wrong. The only number
that moves money in the wrong direction.

**Incorrectly auto-posted amount** — because one wrong ₹50 and one wrong
₹5,00,000 are not the same event, and a count treats them as though they were.

And one summary figure worth having, §60:

**Safe resolution rate** — the share of cases resolved *without a human* while
holding the false-proof rate under its policy ceiling. Not "how often does it
say yes", but "how often has it earned the right to".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from attest.model import Settlement
from attest.exceptions import classify
from attest.policy import Costs, Decision, RiskModel, decide
from attest.verdict import Finding, Verdict


@dataclass
class Metrics:
    """Every figure the product is allowed to quote, computed in one place."""

    settlements: int
    proven: int
    ambiguous: int
    contradicted: int
    insufficient: int

    exact_sets: int
    false_proofs: int

    pair_tp: int
    pair_fp: int
    pair_fn: int

    processed_paise: int
    auto_posted_paise: int
    protected_paise: int
    incorrectly_auto_posted_paise: int
    expected_loss_paise: int
    max_exposure_paise: int

    auto_post: int
    review: int
    block: int

    settled_paise: int
    """Value inside AMBIGUOUS settlements that every surviving explanation
    agrees on. Not proven, not posted — but accounted for, and the single most
    useful thing the engine can say while refusing."""

    disputed_paise: int
    unexplained_paise: int

    # -- rates, all named for what they actually measure -------------------

    @property
    def exact_set_recovery(self) -> float:
        """Share of settlements whose complete ground-truth set was recovered."""
        return self.exact_sets / max(self.settlements, 1)

    @property
    def proof_precision(self) -> float:
        """When the engine claims PROVEN, how often is it right."""
        return (self.proven - self.false_proofs) / max(self.proven, 1)

    @property
    def false_proof_rate(self) -> float:
        """Share of ALL settlements on which a wrong claim of proof was made.
        Denominated over everything, not over PROVEN, because a merchant's
        exposure is per settlement processed."""
        return self.false_proofs / max(self.settlements, 1)

    @property
    def coverage(self) -> float:
        """Share the engine resolves at all, rather than handing back."""
        return self.proven / max(self.settlements, 1)

    @property
    def ambiguity_rate(self) -> float:
        """Share where the engine correctly refuses to choose. A feature."""
        return self.ambiguous / max(self.settlements, 1)

    @property
    def contradiction_rate(self) -> float:
        return self.contradicted / max(self.settlements, 1)

    @property
    def insufficiency_rate(self) -> float:
        return self.insufficient / max(self.settlements, 1)

    @property
    def pair_precision(self) -> float:
        d = self.pair_tp + self.pair_fp
        return self.pair_tp / d if d else 0.0

    @property
    def financial_error_rate(self) -> float:
        """Share of auto-posted VALUE that was posted wrongly. The rate that
        matters when the amounts are unequal, which they always are."""
        return self.incorrectly_auto_posted_paise / max(self.auto_posted_paise, 1)

    @property
    def accounted_rate(self) -> float:
        """Share of ALL processed value the engine can account for — proven
        outright, or agreed by every surviving explanation.

        The honest companion to exact-set recovery. 16% of settlements recovered
        completely sounds like an engine that fails five times out of six; that
        reading is wrong, and this is the figure that shows why. Most abstentions
        are not "we do not know", they are "we know all but this part, and here
        is the part".
        """
        return ((self.auto_posted_paise + self.settled_paise)
                / max(self.processed_paise, 1))

    @property
    def safe_resolution_rate(self) -> float:
        """§60. Resolved without a human, and allowed to be."""
        return self.auto_post / max(self.settlements, 1)

    def to_json(self) -> dict[str, object]:
        d = asdict(self)
        d.update({
            "exact_set_recovery": round(self.exact_set_recovery, 4),
            "proof_precision": round(self.proof_precision, 4),
            "false_proof_rate": round(self.false_proof_rate, 4),
            "coverage": round(self.coverage, 4),
            "ambiguity_rate": round(self.ambiguity_rate, 4),
            "contradiction_rate": round(self.contradiction_rate, 4),
            "insufficiency_rate": round(self.insufficiency_rate, 4),
            "pair_precision": round(self.pair_precision, 4),
            "financial_error_rate": round(self.financial_error_rate, 6),
            "safe_resolution_rate": round(self.safe_resolution_rate, 4),
            "accounted_rate": round(self.accounted_rate, 4),
        })
        return d

    def render(self) -> str:
        w = 60
        return "\n".join([
            "", "  RESOLUTION", "-" * w,
            f"  exact set recovery      {self.exact_set_recovery:>8.1%}"
            f"   complete truth recovered",
            f"  coverage                {self.coverage:>8.1%}"
            f"   resolved at all",
            f"  ambiguity rate          {self.ambiguity_rate:>8.1%}"
            f"   correctly refused",
            f"  contradiction rate      {self.contradiction_rate:>8.1%}",
            f"  insufficiency rate      {self.insufficiency_rate:>8.1%}"
            f"   evidence never present",
            "", "  SAFETY", "-" * w,
            f"  proof precision         {self.proof_precision:>8.3f}"
            f"   right when it claims sure",
            f"  false proof rate        {self.false_proof_rate:>8.2%}"
            f"   <- the number that moves money",
            f"  pair precision          {self.pair_precision:>8.3f}",
            "", "  MONEY", "-" * w,
            f"  processed             ₹{self.processed_paise / 100:>12,.0f}",
            f"  auto-posted           ₹{self.auto_posted_paise / 100:>12,.0f}",
            f"  protected             ₹{self.protected_paise / 100:>12,.0f}"
            f"   refused, deliberately",
            f"  wrongly auto-posted   ₹{self.incorrectly_auto_posted_paise / 100:>12,.0f}",
            f"  expected loss         ₹{self.expected_loss_paise / 100:>12,.0f}",
            f"  max single exposure   ₹{self.max_exposure_paise / 100:>12,.0f}",
            f"  financial error rate    {self.financial_error_rate:>8.4%}"
            f"   of posted value",
            "", "  ACCOUNTED FOR", "-" * w,
            f"  settled (undisputed)  ₹{self.settled_paise / 100:>12,.0f}"
            f"   agreed by every explanation",
            f"  disputed              ₹{self.disputed_paise / 100:>12,.0f}",
            f"  unexplained           ₹{self.unexplained_paise / 100:>12,.0f}",
            f"  accounted for           {self.accounted_rate:>8.1%}"
            f"   of all processed value",
            "", "  NORTH STAR", "-" * w,
            f"  safe resolution rate    {self.safe_resolution_rate:>8.1%}"
            f"   resolved without a human", ""])


def measure(findings: list[Finding], settlements: dict[str, Settlement],
            truth: dict[str, set[str]], risk: RiskModel,
            costs: Costs = Costs(), pools: dict | None = None) -> Metrics:
    m = Metrics(*([0] * 22))
    m.settlements = len(findings)
    m.processed_paise = sum(s.net_paise for s in settlements.values())

    for f in findings:
        s = settlements[f.settlement_id]
        actual = truth.get(f.settlement_id, set())

        if f.verdict is Verdict.PROVEN:
            m.proven += 1
        elif f.verdict is Verdict.AMBIGUOUS:
            m.ambiguous += 1
        elif f.verdict is Verdict.CONTRADICTED:
            m.contradicted += 1
        else:
            m.insufficient += 1

        got = set(f.proofs[0].order_ids) if f.postable and f.proofs else set()
        if f.verdict is Verdict.PROVEN and f.proofs:
            if got == actual:
                m.exact_sets += 1
            else:
                m.false_proofs += 1
        m.pair_tp += len(got & actual)
        m.pair_fp += len(got - actual)
        m.pair_fn += len(actual - got)

        exc = classify(f, s, pools.get(f.settlement_id, []), 0) if pools else None
        if exc is not None:
            if exc.settled:
                m.settled_paise += exc.settled.net_paise
                m.disputed_paise += exc.settled.disputed_paise
            m.unexplained_paise += exc.unexplained_paise if not exc.settled else 0

        j = decide(f, s, risk, costs)
        if j.decision is Decision.AUTO_POST:
            m.auto_post += 1
            m.auto_posted_paise += s.net_paise
            m.expected_loss_paise += j.expected_loss_paise or 0
            m.max_exposure_paise = max(m.max_exposure_paise,
                                       costs.wrong_post(s.net_paise))
            if got != actual:
                m.incorrectly_auto_posted_paise += s.net_paise
        else:
            m.block += int(j.decision is Decision.BLOCK)
            m.review += int(j.decision is Decision.REVIEW)
            m.protected_paise += s.net_paise
    return m


def write_source_of_truth(path: Path, payload: dict[str, object]) -> None:
    """One machine-readable benchmark result. §46.

    README, the console, the evaluation screen and any deck must read from this
    file rather than restating numbers. Every mismatch this project has shipped —
    "precision 1.000" surviving six days past the measurement that refuted it —
    happened because a figure was typed in a second place and then diverged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
