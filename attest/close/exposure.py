"""Financial Exposure Engine — measures financial risk in integer paise.

Reconciliation reports match status (PROVEN, AMBIGUOUS, CONTRADICTED).
A finance controller needs to know: **how much money is at risk?**

Core Principles:
1. Economic Value, Not Exception Count:
   Exposure is the financial value that cannot be verified — unexplained
   residuals and disputed subsets, summed across the period in integer paise.
2. Deduplication by Canonical Identity:
   The same economic exposure must never be counted twice merely because multiple
   findings or exception references point to the same settlement.
3. No Unsound Cross-Settlement Netting:
   A shortfall of ₹500 on settlement A does not offset an overage of ₹500 on
   settlement B. Both represent financial discrepancies and risk at stake.
4. Currency Safety:
   Monetary values cannot be aggregated across mismatched currencies without
   verified conversion. Mismatches are treated as safety violations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import Enum
from typing import Any

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement
from attest.money import rupees
from attest.policy import Decision
from attest.verdict import Finding, Verdict


class CurrencyMismatchError(ValueError):
    """Raised when records with incompatible currencies are aggregated."""


class ExposureKind(str, Enum):
    """Classification of the underlying financial risk."""

    UNVERIFIED = "UNVERIFIED"
    """The settlement has no verified explanation; full value at risk."""

    PARTIAL = "PARTIAL"
    """Part of the settlement is explained; an unexplained residual remains."""

    AMBIGUOUS = "AMBIGUOUS"
    """Multiple valid explanations exist; disputed portion is at risk."""

    INSUFFICIENT = "INSUFFICIENT"
    """Solver could not evaluate the settlement (out of envelope)."""

    POLICY_BLOCKED = "POLICY_BLOCKED"
    """Reconciliation proved a match, but action policy refused to post."""


@dataclass(frozen=True, slots=True)
class ExposureItem:
    """A single settlement's financial exposure within the period.

    `exposure_paise` is the non-negative monetary amount at risk in integer paise.
    """

    settlement_id: str
    settlement_value_paise: int
    exposure_paise: int
    kind: ExposureKind
    reason: ReasonCode
    severity: Severity
    explanation: str
    currency: str = "INR"

    def __post_init__(self) -> None:
        if self.exposure_paise < 0:
            raise ValueError(
                f"exposure_paise must be non-negative, got {self.exposure_paise}"
            )
        if self.settlement_value_paise < 0:
            raise ValueError(
                f"settlement_value_paise must be non-negative, got {self.settlement_value_paise}"
            )

    @property
    def exposure_share(self) -> float:
        """Fraction of settlement value at risk."""
        return self.exposure_paise / max(self.settlement_value_paise, 1)


@dataclass(frozen=True, slots=True)
class PeriodExposure:
    """Aggregate financial exposure for a period.

    Composed strictly from deterministic reconciliation findings and exception records.
    Every amount is in integer paise.

    Distinguishes two vital economic dimensions:
    1. Net Balance-Sheet Unresolved Exposure (`net_unresolved_exposure_paise`):
       The actual net balance-sheet unposted value across unverified settlements.
       Conserves the fundamental accounting identity:
           reconciled_net + net_unresolved = total_period_value
           (verified_value_paise + net_unresolved_exposure_paise == total_value_paise)
       This is the primary economic metric for period close-readiness.

    2. Gross Contested Claim Exposure (`gross_contested_claim_exposure_paise`):
       The gross sum of all candidate orders disputed across alternative ambiguous hypotheses.
       When an ambiguous settlement has multiple candidate subset-sum proofs, their candidate
       order sets are largely disjoint; summing them aggregates competing candidate explanations.
       Therefore, when competing candidate hypotheses overlap,
           gross_contested_claim_exposure_paise >= net_unresolved_exposure_paise
       and can exceed total portfolio value (acting as a diagnostic risk metric for ambiguity).
    """

    items: tuple[ExposureItem, ...]
    total_settlements: int
    verified_count: int
    unresolved_count: int
    total_value_paise: int
    verified_value_paise: int
    total_exposure_paise: int
    ambiguous_exposure_paise: int
    contradicted_exposure_paise: int
    insufficient_exposure_paise: int
    currency: str = "INR"
    net_unresolved_exposure_paise: int = 0
    gross_contested_claim_exposure_paise: int = 0

    @property
    def verified_share(self) -> float:
        """Fraction of total settlements fully verified."""
        return self.verified_count / max(self.total_settlements, 1)

    @property
    def reconciled_value_share(self) -> float:
        """Fraction of portfolio value reconciled and verified."""
        return self.verified_value_paise / max(self.total_value_paise, 1)

    @property
    def exposure_share(self) -> float:
        """Share of total portfolio representing net unposted exposure."""
        return self.net_unresolved_exposure_paise / max(self.total_value_paise, 1)

    @property
    def net_unresolved_share(self) -> float:
        """Fraction of portfolio representing net unposted ledger balance."""
        return self.net_unresolved_exposure_paise / max(self.total_value_paise, 1)

    @property
    def gross_contested_share(self) -> float:
        """Fraction of portfolio representing gross disputed candidate claims."""
        return self.gross_contested_claim_exposure_paise / max(self.total_value_paise, 1)

    def top_exposures(self, n: int = 10) -> tuple[ExposureItem, ...]:
        """Ranked largest exposure first, tie-broken deterministically by settlement_id."""
        return self.items[:n]

    def summary(self) -> str:
        return (
            f"{self.verified_count}/{self.total_settlements} settlements verified "
            f"({self.verified_share:.1%}, {rupees(self.verified_value_paise)}), "
            f"net unresolved exposure {rupees(self.net_unresolved_exposure_paise)} of "
            f"{rupees(self.total_value_paise)} ({self.net_unresolved_share:.2%}), "
            f"gross contested claim exposure {rupees(self.gross_contested_claim_exposure_paise)} "
            f"({self.gross_contested_share:.2%}) [{self.currency}]"
        )


def _check_currency(obj: object, expected_currency: str) -> None:
    curr = getattr(obj, "currency", None)
    if curr is not None and curr != expected_currency:
        raise CurrencyMismatchError(
            f"Currency mismatch: expected {expected_currency}, got {curr} on {obj}"
        )


def assess_exposure(
    findings: Sequence[Finding],
    exceptions: Sequence[Exception_] | Mapping[str, Exception_] | None = None,
    settlements: Sequence[Settlement] | None = None,
    target_settlement_ids: Set[str] | Sequence[str] | None = None,
    currency: str = "INR",
    judgements: Mapping[str, Any] | None = None,
) -> PeriodExposure:
    """Compute aggregate financial exposure for a period.

    Guarantees:
    - Deduplication: Duplicate findings or exception references for the same
      settlement are processed exactly once.
    - Determinism: Input order does not change the resulting exposure or ranking.
    - Integer paise: Pure integer arithmetic throughout.
    - Non-negative risk: Signed residuals are evaluated by their absolute magnitude
      of financial uncertainty; cross-settlement netting is prevented.
    - Currency safety: Mismatches raise CurrencyMismatchError.
    """
    # 1. Currency validation
    if settlements is not None:
        for s in settlements:
            _check_currency(s, currency)

    # 2. Canonical settlement universe mapping
    settlements_by_id: dict[str, Settlement] = {}
    if settlements is not None:
        for s in settlements:
            _check_currency(s, currency)
            if s.settlement_id not in settlements_by_id:
                settlements_by_id[s.settlement_id] = s

    # 3. Canonical exceptions mapping (deduplicate by exception id and settlement_id)
    exceptions_by_sid: dict[str, Exception_] = {}
    seen_exception_ids: set[str] = set()

    if exceptions is not None:
        raw_exceptions = (
            exceptions.values() if isinstance(exceptions, Mapping) else exceptions
        )
        for ex in raw_exceptions:
            _check_currency(ex, currency)
            if ex.id in seen_exception_ids:
                continue
            seen_exception_ids.add(ex.id)
            # Retain the highest-magnitude exception if multiple exist for a settlement.
            existing = exceptions_by_sid.get(ex.settlement_id)
            if existing is None or abs(ex.unexplained_paise) > abs(existing.unexplained_paise):
                exceptions_by_sid[ex.settlement_id] = ex

    # 4. Canonical findings mapping (deduplicate by settlement_id)
    findings_by_id: dict[str, Finding] = {}
    for f in findings:
        _check_currency(f, currency)
        if f.settlement_id not in findings_by_id:
            findings_by_id[f.settlement_id] = f
        else:
            # If multiple findings exist, ensure contradictory findings don't hide
            existing = findings_by_id[f.settlement_id]
            if existing.verdict is Verdict.PROVEN and f.verdict is not Verdict.PROVEN:
                findings_by_id[f.settlement_id] = f  # conservative: unproven takes precedence

    # 5. Determine active settlement ID universe
    if target_settlement_ids is not None:
        active_ids = set(target_settlement_ids)
    elif settlements_by_id:
        active_ids = set(settlements_by_id.keys())
    else:
        active_ids = set(findings_by_id.keys()) | set(exceptions_by_sid.keys())

    # Deterministic processing order
    sorted_sids = sorted(active_ids)

    items: list[ExposureItem] = []
    verified_count = 0
    verified_value_paise = 0
    total_value_paise = 0

    for sid in sorted_sids:
        s = settlements_by_id.get(sid)
        f = findings_by_id.get(sid)
        ex = exceptions_by_sid.get(sid)

        # Determine settlement value in paise
        if s is not None:
            s_val = abs(s.net_paise)
        elif f is not None and f.proofs:
            s_val = abs(f.proofs[0].net_paise)
        elif ex is not None:
            s_val = abs(ex.amount_paise)
        else:
            s_val = 0

        total_value_paise += s_val

        # Check policy approval if judgements are provided
        is_policy_blocked = False
        if judgements is not None:
            j = judgements.get(sid)
            if j is not None and getattr(j, "decision", None) is Decision.BLOCK:
                is_policy_blocked = True

        # Case A: Fully verified finding (PROVEN and postable, zero exception or zero unexplained, not policy blocked)
        if (
            f is not None
            and f.verdict is Verdict.PROVEN
            and f.postable
            and (ex is None or ex.unexplained_paise == 0)
            and not is_policy_blocked
        ):
            verified_count += 1
            verified_value_paise += s_val
            continue

        # Case A.1: Proven by solver but blocked by action policy from posting
        if (
            f is not None
            and f.verdict is Verdict.PROVEN
            and f.postable
            and is_policy_blocked
        ):
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=s_val,
                    kind=ExposureKind.POLICY_BLOCKED,
                    reason=ex.reason if ex is not None else ReasonCode.INSUFFICIENT_EVIDENCE,
                    severity=Severity.HIGH,
                    explanation="proven by solver but action policy refused to post",
                    currency=currency,
                )
            )
            continue

        # Case A.2: Proven with partial unexplained exception (not policy blocked)
        if (
            f is not None
            and f.verdict is Verdict.PROVEN
            and f.postable
            and not is_policy_blocked
            and ex is not None
            and ex.unexplained_paise > 0
        ):
            unexplained = min(s_val, abs(ex.unexplained_paise))
            verified_portion = max(0, s_val - unexplained)
            verified_value_paise += verified_portion
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=unexplained,
                    kind=ExposureKind.PARTIAL,
                    reason=ex.reason,
                    severity=ex.severity,
                    explanation=f"proven with residual {rupees(unexplained)} unexplained",
                    currency=currency,
                )
            )
            continue

        # Case B: AMBIGUOUS finding
        if f is not None and f.verdict is Verdict.AMBIGUOUS:
            # Gross contested claim exposure represents competing candidate orders across alternative hypotheses
            if ex is not None and ex.settled is not None and ex.settled.disputed_paise > 0:
                exp_paise = abs(ex.settled.disputed_paise)
            elif f.proofs and len(f.proofs) > 1:
                exp_paise = sum(p.gross_paise for p in f.proofs)
            elif ex is not None and ex.unexplained_paise != 0:
                exp_paise = abs(ex.unexplained_paise)
            else:
                exp_paise = s_val

            reason = ex.reason if ex else ReasonCode.MULTIPLE_VALID_ASSIGNMENTS
            severity = ex.severity if ex else Severity.MEDIUM
            explanation = (
                f"ambiguous settlement with {len(f.proofs)} proofs; "
                f"disputed portion {rupees(exp_paise)}"
                if exp_paise > 0
                else f"ambiguous settlement with {len(f.proofs)} proofs; "
                f"money is present but attribution is non-unique"
            )
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=exp_paise,
                    kind=ExposureKind.AMBIGUOUS,
                    reason=reason,
                    severity=severity,
                    explanation=explanation,
                    currency=currency,
                )
            )
            continue

        # Case C: INSUFFICIENT finding
        if f is not None and f.verdict is Verdict.INSUFFICIENT:
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=s_val,
                    kind=ExposureKind.INSUFFICIENT,
                    reason=ex.reason if ex else ReasonCode.INSUFFICIENT_EVIDENCE,
                    severity=Severity.HIGH,
                    explanation="solver envelope exceeded or unexamined evidence",
                    currency=currency,
                )
            )
            continue

        # Case D: CONTRADICTED finding
        if f is not None and f.verdict is Verdict.CONTRADICTED:
            if ex is not None:
                unexplained = abs(ex.unexplained_paise)
            else:
                unexplained = s_val

            kind = ExposureKind.PARTIAL if unexplained < s_val else ExposureKind.UNVERIFIED
            reason = ex.reason if ex else ReasonCode.NO_VALID_ASSIGNMENT
            severity = ex.severity if ex else Severity.HIGH
            explanation = (
                f"contradicted: residual {rupees(unexplained)} unexplained"
                if unexplained < s_val
                else "contradicted: no candidate combination reaches settlement value"
            )
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=unexplained,
                    kind=kind,
                    reason=reason,
                    severity=severity,
                    explanation=explanation,
                    currency=currency,
                )
            )
            continue

        # Case E: PROVEN but not postable (e.g. HEURISTIC search space)
        if f is not None and f.verdict is Verdict.PROVEN and not f.postable:
            reason = ex.reason if ex else ReasonCode.SEARCH_SPACE_UNCERTAIN
            severity = ex.severity if ex else Severity.LOW
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=0,  # Money is verified, uniqueness is local
                    kind=ExposureKind.AMBIGUOUS,
                    reason=reason,
                    severity=severity,
                    explanation="proven within heuristic space; uniqueness is local",
                    currency=currency,
                )
            )
            continue

        # Case F: Standalone exception without finding or missing record
        if ex is not None:
            exp_paise = abs(ex.unexplained_paise)
            items.append(
                ExposureItem(
                    settlement_id=sid,
                    settlement_value_paise=s_val,
                    exposure_paise=exp_paise,
                    kind=ExposureKind.UNVERIFIED if exp_paise == s_val else ExposureKind.PARTIAL,
                    reason=ex.reason,
                    severity=ex.severity,
                    explanation=f"unresolved exception {ex.id}: {ex.missing}",
                    currency=currency,
                )
            )
            continue

        # Case G: Unexamined / missing settlement (in target list but absent from engine output)
        items.append(
            ExposureItem(
                settlement_id=sid,
                settlement_value_paise=s_val,
                exposure_paise=s_val,
                kind=ExposureKind.UNVERIFIED,
                reason=ReasonCode.INSUFFICIENT_EVIDENCE,
                severity=Severity.HIGH,
                explanation="settlement present in period scope but missing from solver output",
                currency=currency,
            )
        )

    # Deterministic sorting: largest gross contested exposure first, tie-break by settlement_id
    sorted_items = tuple(sorted(items, key=lambda x: (-x.exposure_paise, x.settlement_id)))

    gross_contested_paise = sum(i.exposure_paise for i in sorted_items)

    # Net Balance-Sheet Unresolved Exposure: actual unposted settlement value.
    net_unresolved_paise = total_value_paise - verified_value_paise

    ambiguous_exp = sum(
        i.exposure_paise for i in sorted_items if i.kind is ExposureKind.AMBIGUOUS
    )
    contradicted_exp = sum(
        i.exposure_paise
        for i in sorted_items
        if i.kind in (ExposureKind.PARTIAL, ExposureKind.UNVERIFIED)
    )
    insufficient_exp = sum(
        i.exposure_paise for i in sorted_items if i.kind is ExposureKind.INSUFFICIENT
    )

    return PeriodExposure(
        items=sorted_items,
        total_settlements=len(sorted_sids),
        verified_count=verified_count,
        unresolved_count=len(sorted_items),
        total_value_paise=total_value_paise,
        verified_value_paise=verified_value_paise,
        total_exposure_paise=net_unresolved_paise,
        ambiguous_exposure_paise=ambiguous_exp,
        contradicted_exposure_paise=contradicted_exp,
        insufficient_exposure_paise=insufficient_exp,
        currency=currency,
        net_unresolved_exposure_paise=net_unresolved_paise,
        gross_contested_claim_exposure_paise=gross_contested_paise,
    )
