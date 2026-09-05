"""What changed between two runs. §19, §30.

Reconciliation is not a one-shot answer, it is a standing claim about a moving
set of records. Refunds land late, chargebacks arrive weeks after the capture, an
export gets re-pulled with rows that were missing the first time. So the question
a finance team actually asks each morning is not "what is the state" but
**"what changed, and why"**.

Detecting a transition is bookkeeping. The value is entirely in **attributing**
it, and attribution here is computed rather than narrated: the engine compares
the candidate universes of the two runs and asks which of the orders that
appeared or disappeared are actually load-bearing for the verdict that moved.

An order that arrived but shows up in none of the new explanations did not cause
anything, and saying it did — because it happened to arrive at the same time —
would be the confident-sounding wrongness this whole project exists to refuse. A
transition the engine cannot attribute is reported as unattributed.

One asymmetry is deliberate. A settlement moving PROVEN -> AMBIGUOUS is not a
regression; it is usually the engine *learning* that its earlier confidence was
an artefact of missing data. Yesterday's certainty was cheap because there was
less to be uncertain about. The diff labels those separately from real
regressions rather than lumping both under "worse".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from attest.model import Order, Settlement
from attest.verdict import Finding, Verdict


class Direction(str, Enum):
    RESOLVED = "resolved"
    """Reached a unique explanation it did not have before."""

    WITHDRAWN = "withdrawn"
    """Was proven, now is not. Usually the engine discovering that its earlier
    uniqueness was an artefact of a thinner candidate pool — which is the
    engine working, not failing."""

    REFRAMED = "reframed"
    """Moved between non-proven states: contradicted to ambiguous, ambiguous to
    insufficient. The evidence changed shape without settling."""

    RECOMPOSED = "recomposed"
    """Still proven, but by a DIFFERENT set of orders. The most alarming
    transition in the file: the engine was certain twice and disagreed with
    itself, so at least one of the two was wrong."""


@dataclass(frozen=True)
class Cause:
    kind: str
    order_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class Change:
    settlement_id: str
    amount_paise: int
    before: Verdict
    after: Verdict
    direction: Direction
    causes: tuple[Cause, ...]
    before_orders: tuple[str, ...]
    after_orders: tuple[str, ...]

    @property
    def attributed(self) -> bool:
        return bool(self.causes)

    def explain(self) -> str:
        head = (f"{self.settlement_id} · {self.before.value} → {self.after.value}"
                f" · {self.direction.value}")
        if not self.causes:
            return head + "\n    unattributed — no input difference accounts for this"
        return head + "".join(f"\n    {c.detail}" for c in self.causes)


@dataclass
class Diff:
    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0
    appeared: int = 0
    vanished: int = 0

    def by_direction(self) -> dict[str, list[Change]]:
        out: dict[str, list[Change]] = {}
        for c in self.changes:
            out.setdefault(c.direction.value, []).append(c)
        return out

    @property
    def unattributed(self) -> list[Change]:
        return [c for c in self.changes if not c.attributed]

    def render(self) -> str:
        w = 66
        out = ["", "WHAT CHANGED", "=" * w,
               f"  {len(self.changes)} settlements changed state · "
               f"{self.unchanged} unchanged"]
        if self.appeared or self.vanished:
            out.append(f"  {self.appeared} new settlements · {self.vanished} gone")
        out.append("-" * w)
        for d, group in sorted(self.by_direction().items(),
                               key=lambda kv: -len(kv[1])):
            money = sum(c.amount_paise for c in group)
            out.append(f"  {d:<12s} {len(group):>4}   ₹{money / 100:>12,.0f}")
        if self.unattributed:
            out.append("-" * w)
            out.append(f"  ⚠ {len(self.unattributed)} unattributed — the inputs "
                       f"do not explain these")
        out.append("=" * w)
        for c in self.changes[:6]:
            out.append("  " + c.explain().replace("\n", "\n  "))
        if len(self.changes) > 6:
            out.append(f"  … {len(self.changes) - 6} more")
        return "\n".join(out) + "\n"


def _s(xs: object) -> str:
    return "" if len(xs) == 1 else "s"  # type: ignore[arg-type]


def _are(xs: object) -> str:
    return "is" if len(xs) == 1 else "are"  # type: ignore[arg-type]


def _were(xs: object) -> str:
    return "was" if len(xs) == 1 else "were"  # type: ignore[arg-type]


def _attribute(before: Finding, after: Finding,
               pool_before: set[str], pool_after: set[str]) -> tuple[Cause, ...]:
    """Which input difference actually accounts for this transition.

    An order is only named if it is load-bearing: it must appear in an
    explanation on the side it exists. An order that arrived and is cited by
    nothing changed nothing, however suggestive the timing.
    """
    causes: list[Cause] = []
    added = pool_after - pool_before
    removed = pool_before - pool_after

    cited_after = {o for p in after.proofs for o in p.order_ids}
    cited_before = {o for p in before.proofs for o in p.order_ids}

    load_added = tuple(sorted(added & cited_after))
    if load_added:
        causes.append(Cause(
            "order_arrived", load_added,
            f"{len(load_added)} order{_s(load_added)} entered the candidate "
            f"universe and {_are(load_added)} used by the new "
            f"explanation{_s(after.proofs)}: {', '.join(load_added[:4])}"
            + (" …" if len(load_added) > 4 else "")))

    load_removed = tuple(sorted(removed & cited_before))
    if load_removed:
        causes.append(Cause(
            "order_left", load_removed,
            f"{len(load_removed)} order{_s(load_removed)} left the candidate "
            f"universe and {_were(load_removed)} used by the old "
            f"explanation{_s(before.proofs)}: {', '.join(load_removed[:4])}"
            + (" …" if len(load_removed) > 4 else "")))

    n_b, n_a = len(before.proofs), len(after.proofs)
    if n_b != n_a and not causes:
        causes.append(Cause(
            "candidate_count", (),
            f"the number of valid explanations moved {n_b} → {n_a} with no "
            f"load-bearing order change; the pool shifted by "
            f"{len(added)} in / {len(removed)} out"))

    sb = getattr(before.space, "integrity", None)
    sa = getattr(after.space, "integrity", None)
    if sb is not None and sa is not None and sb != sa:
        causes.append(Cause(
            "space_integrity", (),
            f"search-space integrity moved {sb.value} → {sa.value}"))

    return tuple(causes)


def _direction(before: Finding, after: Finding) -> Direction:
    b, a = before.verdict, after.verdict
    if b is Verdict.PROVEN and a is Verdict.PROVEN:
        return Direction.RECOMPOSED
    if a is Verdict.PROVEN:
        return Direction.RESOLVED
    if b is Verdict.PROVEN:
        return Direction.WITHDRAWN
    return Direction.REFRAMED


def diff(before: list[Finding], after: list[Finding],
         pools_before: dict[str, list[Order]], pools_after: dict[str, list[Order]],
         settlements: dict[str, Settlement]) -> Diff:
    """Compare two runs and attribute every state change to an input difference."""
    b_by = {f.settlement_id: f for f in before}
    a_by = {f.settlement_id: f for f in after}
    d = Diff()

    for sid, af in a_by.items():
        bf = b_by.get(sid)
        if bf is None:
            d.appeared += 1
            continue

        b_orders = tuple(sorted(bf.proofs[0].order_ids)) if bf.proofs else ()
        a_orders = tuple(sorted(af.proofs[0].order_ids)) if af.proofs else ()
        same_verdict = bf.verdict is af.verdict
        # A proven settlement re-composed from different orders is a change even
        # though the verdict did not move — and it is the change most worth
        # surfacing, because the engine was certain twice and disagreed.
        recomposed = (same_verdict and af.verdict is Verdict.PROVEN
                      and b_orders != a_orders)
        if same_verdict and not recomposed:
            d.unchanged += 1
            continue

        d.changes.append(Change(
            settlement_id=sid,
            amount_paise=settlements[sid].net_paise,
            before=bf.verdict, after=af.verdict,
            direction=_direction(bf, af),
            causes=_attribute(bf, af,
                              {o.order_id for o in pools_before.get(sid, [])},
                              {o.order_id for o in pools_after.get(sid, [])}),
            before_orders=b_orders, after_orders=a_orders))

    d.vanished = len(set(b_by) - set(a_by))
    d.changes.sort(key=lambda c: -c.amount_paise)
    return d
