"""The rule engine. §44, §45.

Everything the engine assumes about how money moves is a rule, and every rule is
a **belief**, not a fact. The gateway charges what it charges; this module records
what ATTEST thinks it charges. When the two disagree, reconciliation degrades —
and that degradation is the engine detecting a misconfigured rule rather than a
solver failing, which is a distinction a finance team needs and cannot get from
an accuracy number.

Hardcoding the same values inside `model.py` would make that failure invisible:
the engine would be checking its assumptions against themselves and agreeing
every time. Separating them is what turns "our fee schedule is wrong" from an
unexplained drop in coverage into a stated cause.

**Versioning is the point of the exercise (§45).** A reconciliation is
reproducible only if you can say what it was reconciled *against*. Every rule set
carries a content hash, so a run records the exact rules, policy, solver and
dataset it saw. Replayability that cannot name its inputs is a claim, not a
property.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace

from attest.model import Method

#: Bumped when the SHAPE of a rule set changes, so an old stored set is refused
#: rather than silently reinterpreted under new semantics.
SCHEMA = 1


@dataclass(frozen=True)
class FeeSchedule:
    """What the engine believes the gateway charges.

    Basis points of gross per method, plus tax on the fee. UPI is zero-MDR in
    India, which is exactly the asymmetry that makes two settlements of identical
    gross value net differently — and the reason a blended rate cannot work.
    """

    bps: dict[str, int] = field(default_factory=lambda: {
        Method.UPI.value: 0, Method.CARD.value: 200,
        Method.NETBANKING.value: 150, Method.WALLET.value: 250})
    tax_bps: int = 1800
    fixed_paise: int = 0
    """A per-transaction flat component. Zero here; real schedules often are not,
    and a schedule that cannot express one would quietly mismatch every row."""


@dataclass(frozen=True)
class SettlementCalendar:
    """When money is expected to land."""

    lags: tuple[int, ...] = (2, 3, 4)
    """Business-day lags to try, tightest first. A convention, never a
    guarantee — see attest/searchspace.py, where relying on it is exactly what
    makes a proof local rather than global."""

    business_days_only: bool = True
    holidays: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToleranceRule:
    """How much arithmetic slack a proof may claim.

    Derived, not chosen: `fee` and `tax` each round half-up independently, so one
    order carries at most `per_order_paise` of error and a k-order subset at most
    k times that. A hand-picked constant is wrong in both directions at once —
    too tight and large bundles never match, too loose and small subsets collide
    inside the band.
    """

    per_order_paise: int = 1
    absolute_cap_paise: int = 0
    """0 means uncapped. A cap would silently break large bundles."""


@dataclass(frozen=True)
class RuleSet:
    name: str = "default"
    currency: str = "INR"
    fees: FeeSchedule = field(default_factory=FeeSchedule)
    calendar: SettlementCalendar = field(default_factory=SettlementCalendar)
    tolerance: ToleranceRule = field(default_factory=ToleranceRule)
    refunds_require_capture: bool = True
    merchant: str | None = None
    schema: int = SCHEMA

    # -- the fee model, expressed as rules rather than constants ------------

    def fee_paise(self, gross_paise: int, method: str) -> int:
        bps = self.fees.bps.get(method, 0)
        return _round_half_up(gross_paise * bps, 10_000) + self.fees.fixed_paise

    def tax_paise(self, fee: int) -> int:
        return _round_half_up(fee * self.fees.tax_bps, 10_000)

    def net_paise(self, gross_paise: int, method: str) -> int:
        f = self.fee_paise(gross_paise, method)
        return gross_paise - f - self.tax_paise(f)

    def tolerance_paise(self, subset_size: int) -> int:
        t = subset_size * self.tolerance.per_order_paise
        cap = self.tolerance.absolute_cap_paise
        return min(t, cap) if cap else t

    # -- identity ----------------------------------------------------------

    @property
    def version(self) -> str:
        """Content hash. Two rule sets that behave identically share a version;
        any change to a rule produces a new one, which is what makes a run's
        provenance meaningful rather than decorative."""
        blob = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return "rules_" + hashlib.sha256(blob.encode()).hexdigest()[:12]

    def with_(self, **kw: object) -> "RuleSet":
        return replace(self, **kw)

    def to_json(self) -> dict[str, object]:
        d = asdict(self)
        d["version"] = self.version
        return d

    def describe(self) -> list[tuple[str, str, str]]:
        """(rule, value, why) — for the UI, and for a reader who has to decide
        whether the engine's beliefs match their gateway contract."""
        f = self.fees
        return [
            ("currency", self.currency, "single-currency; mixed books need one rule set per currency"),
            ("settlement calendar", f"T+{'/'.join(map(str, self.calendar.lags))} business days",
             "tried tightest-first; a convention, so any proof resting on it is local"),
            ("fee schedule", ", ".join(f"{k} {v/100:g}%" for k, v in sorted(f.bps.items())),
             "per method — UPI is zero-MDR, so a blended rate cannot reconcile"),
            ("tax on fees", f"{f.tax_bps / 100:g}%", "charged on the fee, never on the gross"),
            ("fixed fee", f"{f.fixed_paise} paise", "per-transaction flat component"),
            ("tolerance", f"±{self.tolerance.per_order_paise} paise per order",
             "derived from two independent half-up roundings, not chosen"),
            ("refund eligibility", "captured transactions only" if self.refunds_require_capture
             else "any transaction", "a refund against an uncaptured payment is a data error"),
        ]


def _round_half_up(numerator: int, denominator: int) -> int:
    """Halves away from zero. `round` is banker's rounding and `int` truncates;
    a gateway does neither, and one paisa compounds across a 40-order bundle."""
    return (numerator + denominator // 2) // denominator


DEFAULT = RuleSet()


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Everything a run must name to be replayable. §45.

    A result without this is not reproducible, whatever the seed says: the same
    data reconciled under a different fee schedule is a different answer to a
    different question.
    """

    rules_version: str
    policy_version: str
    solver_version: str
    dataset_version: str
    model_version: str = "none"
    """Which model produced hypotheses, if any ran. 'none' is the honest and
    current answer — the loop is disabled: on the re-measurement in
    `benchmark/anchoring.json` it is silent on 94% of ambiguous cases."""

    def to_json(self) -> dict[str, str]:
        return asdict(self)

    def render(self) -> str:
        return " · ".join(f"{k.replace('_version', '')}={v}"
                          for k, v in asdict(self).items())


def solver_version() -> str:
    """Hash the code that actually decides, so a change to the solver shows up
    in provenance whether or not anyone remembered to bump a number."""
    import inspect

    from attest import blocking, layers, pipeline, subsetsum, verdict
    blob = "".join(inspect.getsource(m) for m in
                   (subsetsum, blocking, layers, pipeline, verdict))
    return "solver_" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def policy_version(costs: object) -> str:
    from dataclasses import asdict as _a
    blob = json.dumps(_a(costs), sort_keys=True, separators=(",", ":"))
    return "policy_" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def dataset_version(n: int, seed: int) -> str:
    return f"synthetic_n{n}_s{seed}"
