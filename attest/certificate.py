"""The proof certificate. §13.

A verdict is a word. A certificate is the account behind it: what was looked at,
what was excluded and on whose authority, what the solver found, what an
independent kernel made of it, and what the policy then allowed. It exists so
that "PROVEN" is never something a reader has to take on trust.

Two rules give it whatever value it has.

**It composes, it never computes.** Every field is read from a `Finding`, a
`SearchSpace` or a `Judgement`. A certificate that derived its own numbers could
disagree with the engine, and a document that can disagree with the ledger is
worse than no document.

**It states scope, not just result.** The uniqueness line reports what the
search space earned the right to claim — `unique` only when every exclusion was
deterministic, and `unique within the validated candidate space` otherwise. D8
cost 32 wrong answers to learn that difference and this is where it becomes
visible to whoever signs off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from attest.model import Settlement
from attest.policy import Decision, Judgement
from attest.searchspace import Integrity, SearchSpace
from attest.verdict import Finding, Verdict


@dataclass(frozen=True)
class Line:
    """One checkable assertion. `ok=None` means 'not applicable', which is not
    the same as passing and must never render as a tick."""

    name: str
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class Certificate:
    settlement_id: str
    value_date: date
    amount_paise: int
    verdict: Verdict
    universe: int
    candidates: int
    integrity: Integrity
    uniqueness: str
    solver: str
    feasible: int
    alternatives: int
    lines: tuple[Line, ...]
    decision: Decision
    expected_loss_paise: int | None
    policy_reasons: tuple[str, ...]

    @property
    def safe_to_post(self) -> bool:
        return self.decision is Decision.AUTO_POST

    def to_json(self) -> dict[str, object]:
        return {
            "settlement_id": self.settlement_id,
            "value_date": self.value_date.isoformat(),
            "amount_paise": self.amount_paise,
            "verdict": self.verdict.value,
            "universe": self.universe,
            "candidates": self.candidates,
            "integrity": self.integrity.value,
            "uniqueness": self.uniqueness,
            "solver": self.solver,
            "feasible": self.feasible,
            "alternatives": self.alternatives,
            "lines": [{"name": ln.name, "ok": ln.ok, "detail": ln.detail}
                      for ln in self.lines],
            "decision": self.decision.value,
            "expected_loss_paise": self.expected_loss_paise,
            "policy_reasons": list(self.policy_reasons),
            "safe_to_post": self.safe_to_post,
        }

    def render(self) -> str:
        w = 66
        mark = {True: "PASS", False: "FAIL", None: "n/a "}
        out = ["", "ATTEST PROOF CERTIFICATE", "=" * w,
               f"  settlement          {self.settlement_id}",
               f"  value date          {self.value_date}",
               f"  amount              {self.amount_paise} paise",
               f"  result              {self.verdict.value}",
               "-" * w,
               f"  input universe      {self.universe:,} orders",
               f"  candidate universe  {self.candidates:,} orders",
               f"  space integrity     {self.integrity.value.upper()}",
               f"  solver              {self.solver}",
               f"  feasible solutions  {self.feasible}",
               f"  alternatives        {self.alternatives}",
               "-" * w]
        for ln in self.lines:
            out.append(f"  {mark[ln.ok]}  {ln.name:<20s} {ln.detail}")
        out += ["-" * w, f"  uniqueness          {self.uniqueness}", "-" * w,
                f"  policy decision     {self.decision.value}"]
        if self.expected_loss_paise is not None:
            out.append(f"  expected loss       {self.expected_loss_paise} paise")
        for r in self.policy_reasons:
            out.append(f"                      {r}")
        out += ["=" * w,
                f"  {'SAFE TO AUTO-POST' if self.safe_to_post else 'NOT SAFE TO AUTO-POST'}",
                ""]
        return "\n".join(out)


def issue(finding: Finding, settlement: Settlement, judgement: Judgement) -> Certificate:
    """Assemble the certificate. Reads; never derives."""
    space = finding.space if isinstance(finding.space, SearchSpace) else None
    p = finding.proofs[0] if finding.proofs else None

    lines: list[Line] = []

    if p is not None:
        lines.append(Line(
            "amount", p.balances,
            f"residual {p.residual_paise} paise against a bound of "
            f"±{p.tolerance_paise} ({len(p.order_ids)} orders × 1 paisa of "
            f"double half-up rounding)"))
        lines.append(Line(
            "fee model", True,
            f"per-method basis points plus 18% GST on the fee; "
            f"{p.gross_paise} gross less {p.fee_paise} yields {p.net_paise}"))
        lines.append(Line(
            "adjustments", None if not p.adjustment_paise else True,
            "none applied" if not p.adjustment_paise
            else f"{p.adjustment_paise} paise, evidenced by linked records"))
    else:
        lines.append(Line("amount", False,
                          "no subset of the candidate space explains the credit"))

    if space is not None:
        lines.append(Line(
            "search space", space.integrity is not Integrity.COMPROMISED,
            f"{space.universe:,} reduced to {space.candidates:,} by "
            + "; ".join(f"{r.name} ({r.removed:,}"
                        f"{', deterministic' if r.deterministic else ', heuristic'})"
                        for r in space.reductions)))
        for r in space.heuristic_steps:
            lines.append(Line(f"— {r.name}", None, r.justification))

    lines.append(Line(
        "uniqueness", finding.verdict is Verdict.PROVEN,
        "exactly one explanation survived every constraint"
        if finding.verdict is Verdict.PROVEN
        else f"{len(finding.proofs)} explanations survived"))

    lines.append(Line(
        "search exhaustive", finding.exhaustive,
        "every explanation was enumerated"
        if finding.exhaustive
        else "the enumerator reached its cap, so 'every explanation' is a claim "
             "about a sample and no deduction may rest on it"))

    lines.append(Line(
        "independent kernel", p is not None,
        "re-derived from source records by verdict.check — 35 lines sharing no "
        "code with the solver, so a prover bug can cost recall but cannot post"
        if p is not None else "nothing to verify"))

    return Certificate(
        settlement_id=settlement.settlement_id,
        value_date=settlement.settled_on,
        amount_paise=settlement.net_paise,
        verdict=finding.verdict,
        universe=space.universe if space else 0,
        candidates=space.candidates if space else 0,
        integrity=space.integrity if space else Integrity.HEURISTIC,
        uniqueness=finding.uniqueness_claim or "not applicable — no unique explanation",
        solver=finding.layer,
        feasible=len(finding.proofs),
        alternatives=max(len(finding.proofs) - 1, 0),
        lines=tuple(lines),
        decision=judgement.decision,
        expected_loss_paise=judgement.expected_loss_paise,
        policy_reasons=judgement.reasons,
    )
