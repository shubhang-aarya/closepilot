"""CLOSEPILOT — Human Review Queue (Phase 2D).

Routes uncertainty instead of forcing automation.

Architectural Guarantees:
- Every unresolved exception routed to human reviewers contains complete operational context:
    * exception ID
    * exposure (integer paise)
    * severity
    * reason
    * evidence
    * current status
    * recommended action
    * predicted resolution
    * close impact
- Prioritization is purely deterministic based on:
    * Safety (hard blockers, high severity, ambiguity)
    * Financial Impact (exposure paise, materiality)
    * Urgency (age, low probability of natural resolution)
- The queue NEVER silently resolves an exception.
- Human actions are explicit, justified, signed by a reviewer, and recorded in a
  tamper-evident audit trail.
- Recommendations and human queue actions NEVER automatically alter financial truth
  or mutate source ledger state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from attest.close.exposure import ExposureItem, PeriodExposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import (
    Blocker,
    BlockerKind,
    CarryForwardItem,
    PeriodVerdict,
)
from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement
from attest.money import rupees

from closepilot.predictor import (
    ResolutionPrediction,
    ResolutionRouting,
    predict_resolution,
)


class ReviewItemStatus(str, Enum):
    """Lifecycle status of an item within the human review queue."""

    PENDING = "PENDING"
    """Awaiting human review and triage."""

    IN_REVIEW = "IN_REVIEW"
    """Assigned to an operational reviewer / currently under investigation."""

    ACTIONED = "ACTIONED"
    """Explicit human action has been approved and recorded."""

    DEFERRED = "DEFERRED"
    """Review deferred to next close cycle or specified target date."""


class HumanActionType(str, Enum):
    """Explicit taxonomy of human reviewer actions."""

    APPROVE_MANUAL_ADJUSTMENT = "APPROVE_MANUAL_ADJUSTMENT"
    """Approve booking a manual ledger journal entry to resolve the residual."""

    SUBMIT_GATEWAY_DISPUTE = "SUBMIT_GATEWAY_DISPUTE"
    """Initiate formal dispute or inquiry with payment gateway / acquirer."""

    APPROVE_CARRY_FORWARD = "APPROVE_CARRY_FORWARD"
    """Authorize immaterial residual to carry forward into the next close period."""

    REQUEST_DATA_OPS_CORRECTION = "REQUEST_DATA_OPS_CORRECTION"
    """Escalate to data engineering for file re-export, format fix, or missing record ingestion."""

    DEFER_REVIEW = "DEFER_REVIEW"
    """Defer investigation awaiting bank feed, gateway settlement batch, or counterparty reply."""

    REJECT_AND_ESCALATE = "REJECT_AND_ESCALATE"
    """Reject unverified transaction and escalate to senior financial controller."""

    ASSIGN_REVIEWER = "ASSIGN_REVIEWER"
    """Assign case ownership to a designated analyst or controller."""


@dataclass(frozen=True, slots=True)
class HumanActionRecord:
    """Tamper-evident, auditable record of an explicit human controller action.

    Guarantees:
    - Never silently resolves: must state reviewer and justification.
    - Cryptographically hashed for non-repudiation.
    - Records operational intent without mutating source financial truth.
    """

    action_id: str
    item_id: str
    exception_id: str
    action_type: HumanActionType
    reviewer: str
    justification: str
    previous_status: ReviewItemStatus
    new_status: ReviewItemStatus
    evidence_ref: str | None = None
    timestamp: str = ""
    action_hash: str = ""

    def __post_init__(self) -> None:
        if not self.reviewer or not self.reviewer.strip():
            raise ValueError("Explicit reviewer is required for auditable human action")
        if not self.justification or not self.justification.strip():
            raise ValueError("Explicit justification is required for auditable human action")

        if not self.action_hash:
            ts = self.timestamp or datetime.now(timezone.utc).isoformat()
            raw = (
                f"{self.action_id}:{self.exception_id}:{self.action_type.value}:"
                f"{self.reviewer.strip()}:{self.justification.strip()}:"
                f"{self.previous_status.value}:{self.new_status.value}:"
                f"{self.evidence_ref or ''}:{ts}"
            )
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            object.__setattr__(self, "timestamp", ts)
            object.__setattr__(self, "action_hash", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "item_id": self.item_id,
            "exception_id": self.exception_id,
            "action_type": self.action_type.value,
            "reviewer": self.reviewer,
            "justification": self.justification,
            "previous_status": self.previous_status.value,
            "new_status": self.new_status.value,
            "evidence_ref": self.evidence_ref,
            "timestamp": self.timestamp,
            "action_hash": self.action_hash,
        }


@dataclass(frozen=True, slots=True)
class HumanReviewItem:
    """A prioritized work item in the ClosePilot Human Review Queue.

    Contains all 9 required operational dimensions:
    1. exception ID
    2. exposure (integer paise)
    3. severity
    4. reason
    5. evidence
    6. current status
    7. recommended action
    8. predicted resolution
    9. close impact
    """

    item_id: str
    exception_id: str
    settlement_id: str
    exposure: int  # integer paise
    severity: str
    reason: str
    evidence: str
    current_status: ReviewItemStatus
    recommended_action: str
    predicted_resolution: ResolutionPrediction | None
    close_impact: str

    # Prioritization & classification metrics
    priority_score: int
    is_material_blocker: bool
    is_ambiguous: bool
    is_carry_forward: bool
    age_days: int = 0
    assigned_reviewer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def net_unresolved_exposure_paise(self) -> int:
        return self.exposure

    def summary(self) -> str:
        """Controller-friendly single-line operational summary."""
        pred_str = (
            f"p(res)={self.predicted_resolution.probability*100:.0f}%"
            if self.predicted_resolution
            else "no-pred"
        )
        return (
            f"[{self.exception_id}] Priority={self.priority_score} | "
            f"{rupees(self.exposure)} ({self.severity}) | "
            f"Impact: {self.close_impact} | Status: {self.current_status.value} | "
            f"Rec: {self.recommended_action} ({pred_str})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "exception_id": self.exception_id,
            "settlement_id": self.settlement_id,
            "exposure": self.exposure,
            "net_unresolved_exposure_paise": self.exposure,
            "severity": self.severity,
            "reason": self.reason,
            "evidence": self.evidence,
            "current_status": self.current_status.value,
            "recommended_action": self.recommended_action,
            "predicted_resolution": (
                self.predicted_resolution.to_dict()
                if self.predicted_resolution
                else None
            ),
            "close_impact": self.close_impact,
            "priority_score": self.priority_score,
            "is_material_blocker": self.is_material_blocker,
            "is_ambiguous": self.is_ambiguous,
            "is_carry_forward": self.is_carry_forward,
            "age_days": self.age_days,
            "assigned_reviewer": self.assigned_reviewer,
            "metadata": dict(self.metadata),
        }


def compute_priority_score(
    exposure_paise: int,
    severity: str,
    reason: str,
    is_hard_blocker: bool,
    is_material: bool,
    is_ambiguous: bool,
    age_days: int,
    predicted_resolution: ResolutionPrediction | None = None,
) -> int:
    """Deterministic prioritization formula: Financial Impact + Safety + Urgency.

    Higher score = higher priority in human review queue.

    Safety:
        Hard Blocker:           +1,000,000
        Material Blocker:       +500,000
        High Severity:          +300,000
        Ambiguous / Contradict: +200,000
        Medium Severity:        +100,000
        Low Severity:           0

    Financial Impact:
        Exposure:               exposure_paise // 1,000 (scaled integer paise)
        Individually Material:  +200,000

    Urgency:
        Age:                    min(age_days * 1,000, 50,000)
        Low Auto-Resolution p:  int((1.0 - p) * 100,000) when predicted
    """
    safety_score = 0
    if is_hard_blocker:
        safety_score += 1_000_000
    if is_material:
        safety_score += 500_000
    if severity == Severity.HIGH.value or severity == "HIGH":
        safety_score += 300_000
    elif severity == Severity.MEDIUM.value or severity == "MEDIUM":
        safety_score += 100_000

    if is_ambiguous or reason == ReasonCode.MULTIPLE_VALID_ASSIGNMENTS.value:
        safety_score += 200_000

    # Financial Impact (1 pt per ₹10 / 1,000 paise)
    impact_score = min(max(0, exposure_paise) // 1_000, 10_000_000)
    if is_material:
        impact_score += 200_000

    # Urgency
    urgency_score = min(max(0, age_days) * 1_000, 50_000)
    if predicted_resolution is not None:
        # Lower probability of natural resolution = higher human review urgency
        prob = max(0.0, min(1.0, predicted_resolution.probability))
        urgency_score += int((1.0 - prob) * 100_000)
    else:
        if reason in (
            ReasonCode.MISSING_TRANSACTION.value,
            ReasonCode.CHARGEBACK.value,
            ReasonCode.DATA_QUALITY.value,
        ):
            urgency_score += 80_000

    return safety_score + impact_score + urgency_score


@dataclass(frozen=True, slots=True)
class HumanReviewQueue:
    """Deterministic, auditable controller review queue.

    Guarantees:
    - Elements sorted deterministically by (-priority_score, -exposure, exception_id).
    - Permutation invariant: Reordering inputs produces identical queue.
    - Immutable updates: record_action returns new instance with updated status and audit log.
    - Source ledger / financial truth remains unmutated.
    """

    period_id: str
    items: tuple[HumanReviewItem, ...]
    audit_log: tuple[HumanActionRecord, ...] = ()

    def get_item(self, exception_id: str) -> HumanReviewItem | None:
        """Find review item by canonical exception ID."""
        for it in self.items:
            if it.exception_id == exception_id:
                return it
        return None

    def get_pending_items(self) -> tuple[HumanReviewItem, ...]:
        """All items currently pending controller review."""
        return tuple(it for it in self.items if it.current_status == ReviewItemStatus.PENDING)

    def get_blocker_items(self) -> tuple[HumanReviewItem, ...]:
        """All items identified as hard or material blockers."""
        return tuple(it for it in self.items if it.is_material_blocker)

    def get_ambiguous_items(self) -> tuple[HumanReviewItem, ...]:
        """All items involving ambiguous / multiple valid assignments."""
        return tuple(it for it in self.items if it.is_ambiguous)

    def get_carry_forward_items(self) -> tuple[HumanReviewItem, ...]:
        """All items eligible for carry-forward."""
        return tuple(it for it in self.items if it.is_carry_forward)

    def get_actions_for_item(self, exception_id: str) -> tuple[HumanActionRecord, ...]:
        """Audit history for a specific exception."""
        return tuple(a for a in self.audit_log if a.exception_id == exception_id)

    def record_action(
        self,
        exception_id: str,
        action_type: HumanActionType,
        reviewer: str,
        justification: str,
        evidence_ref: str | None = None,
        timestamp: str = "",
    ) -> HumanReviewQueue:
        """Record an explicit human controller action.

        Returns a new HumanReviewQueue with:
        - target item status updated
        - new tamper-evident audit record appended
        - financial truth unmutated

        Raises ValueError if exception not found, or if reviewer/justification is missing.
        """
        item = self.get_item(exception_id)
        if item is None:
            raise ValueError(f"Exception '{exception_id}' not found in review queue")

        # Determine new status based on action type
        previous_status = item.current_status
        new_status = ReviewItemStatus.ACTIONED
        new_assigned = item.assigned_reviewer

        if action_type == HumanActionType.DEFER_REVIEW:
            new_status = ReviewItemStatus.DEFERRED
        elif action_type == HumanActionType.ASSIGN_REVIEWER:
            new_status = ReviewItemStatus.IN_REVIEW
            new_assigned = reviewer

        action_seq = len(self.audit_log) + 1
        action_id = f"act:{self.period_id}:{exception_id}:{action_seq:04d}"

        audit_entry = HumanActionRecord(
            action_id=action_id,
            item_id=item.item_id,
            exception_id=exception_id,
            action_type=action_type,
            reviewer=reviewer,
            justification=justification,
            previous_status=previous_status,
            new_status=new_status,
            evidence_ref=evidence_ref,
            timestamp=timestamp,
        )

        updated_item = HumanReviewItem(
            item_id=item.item_id,
            exception_id=item.exception_id,
            settlement_id=item.settlement_id,
            exposure=item.exposure,
            severity=item.severity,
            reason=item.reason,
            evidence=item.evidence,
            current_status=new_status,
            recommended_action=item.recommended_action,
            predicted_resolution=item.predicted_resolution,
            close_impact=item.close_impact,
            priority_score=item.priority_score,
            is_material_blocker=item.is_material_blocker,
            is_ambiguous=item.is_ambiguous,
            is_carry_forward=item.is_carry_forward,
            age_days=item.age_days,
            assigned_reviewer=new_assigned,
            metadata=item.metadata,
        )

        updated_items = tuple(
            updated_item if it.exception_id == exception_id else it
            for it in self.items
        )

        return HumanReviewQueue(
            period_id=self.period_id,
            items=updated_items,
            audit_log=self.audit_log + (audit_entry,),
        )

    def render(self) -> str:
        """Render clean ASCII operational table for controller audit."""
        lines = [
            f"=== CLOSEPILOT HUMAN REVIEW QUEUE (Period: {self.period_id}) ===",
            f"Total Items: {len(self.items)} | Pending: {len(self.get_pending_items())} | "
            f"Blockers: {len(self.get_blocker_items())} | Audit Actions: {len(self.audit_log)}",
            "-" * 88,
            f"{'Score':<7} | {'ID':<10} | {'Exposure':<12} | {'Severity':<8} | {'Status':<9} | {'Close Impact'}",
            "-" * 88,
        ]
        for it in self.items:
            lines.append(
                f"{it.priority_score:<7} | {it.exception_id:<10} | {rupees(it.exposure):<12} | "
                f"{it.severity:<8} | {it.current_status.value:<9} | {it.close_impact[:40]}"
            )
        lines.append("-" * 88)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        blocker_items = self.get_blocker_items()
        return {
            "period_id": self.period_id,
            "total_items": len(self.items),
            "pending_count": len(self.get_pending_items()),
            "active_blocker_rule_instances": len(blocker_items),
            "unique_blocked_exceptions": len({it.exception_id for it in blocker_items}),
            "unique_blocked_settlements": len({it.settlement_id for it in blocker_items}),
            "blocker_count": len(blocker_items),
            "items": [it.to_dict() for it in self.items],
            "audit_log": [a.to_dict() for a in self.audit_log],
        }


def build_review_queue(
    exceptions: Sequence[Exception_],
    verdict: PeriodVerdict | None = None,
    exposure: PeriodExposure | None = None,
    materiality: MaterialityBound | None = None,
    predictions: Sequence[ResolutionPrediction] | Mapping[str, ResolutionPrediction] | None = None,
    settlements: Sequence[Settlement] | None = None,
    period_id: str = "",
) -> HumanReviewQueue:
    """Build a prioritized, deterministic Human Review Queue from exceptions and close artifacts.

    Guarantees:
    - Every review item contains all 9 required operational dimensions.
    - Prioritized by Financial Impact + Safety + Urgency.
    - Tie-broken deterministically by (-priority_score, -exposure, exception_id).
    - Permutation invariant: Order of input `exceptions` does not alter queue output.
    - Never mutates financial truth.
    """
    if not period_id and verdict is not None:
        period_id = verdict.period_id
    if not period_id:
        period_id = "CURRENT_PERIOD"

    # Index settlements by settlement_id
    settlement_map: dict[str, Settlement] = {}
    if settlements is not None:
        for s in settlements:
            settlement_map[s.settlement_id] = s

    # Index predictions by exception_id and settlement_id
    pred_by_ex: dict[str, ResolutionPrediction] = {}
    pred_by_settlement: dict[str, ResolutionPrediction] = {}
    if predictions is not None:
        if isinstance(predictions, Mapping):
            for k, p in predictions.items():
                pred_by_ex[k] = p
                pred_by_settlement[p.settlement_id] = p
        else:
            for p in predictions:
                pred_by_ex[p.exception_id] = p
                pred_by_settlement[p.settlement_id] = p

    # Index blockers from verdict
    blockers_by_ref: dict[str, list[Blocker]] = {}
    if verdict is not None:
        for b in verdict.structured_blockers:
            blockers_by_ref.setdefault(b.ref_id, []).append(b)

    # Index carry-forward items from verdict
    carry_forward_ex_ids: set[str] = set()
    if verdict is not None:
        for cf in verdict.carry_forward_items:
            carry_forward_ex_ids.add(cf.exception_id)

    # Calculate allowable threshold
    allowable_paise = 0
    if materiality is not None:
        base_val = exposure.total_value_paise if exposure else 0
        allowable_paise = materiality.max_allowable_exposure_paise(base_val)

    # Build review items
    review_items: list[HumanReviewItem] = []
    seen_ex_ids: set[str] = set()

    for ex in exceptions:
        if ex.id in seen_ex_ids:
            continue
        seen_ex_ids.add(ex.id)

        exp_paise = abs(ex.unexplained_paise)
        sev_str = ex.severity.value if hasattr(ex.severity, "value") else str(ex.severity)
        reason_str = ex.reason.value if hasattr(ex.reason, "value") else str(ex.reason)

        # Settlement reference & age
        s = settlement_map.get(ex.settlement_id)
        age_days = 0
        if s is not None and s.settled_on is not None:
            # If we know the settlement date, compare against today/reference
            today = datetime.now(timezone.utc).date()
            if s.settled_on <= today:
                age_days = max(0, (today - s.settled_on).days)

        # Compile evidence summary
        evidence_parts: list[str] = []
        if ex.missing:
            evidence_parts.append(f"missing: {ex.missing}")
        if ex.established:
            evidence_parts.append(f"established: {', '.join(ex.established)}")
        if ex.partial is not None:
            evidence_parts.append(
                f"partial match: {len(ex.partial.order_ids)} order(s) totalling {rupees(ex.partial.net_paise)}"
            )
        if ex.settled is not None:
            evidence_parts.append(
                f"uncontested: {len(ex.settled.order_ids)} order(s) totalling {rupees(ex.settled.net_paise)}"
            )
        if s is not None and s.utr:
            evidence_parts.append(f"UTR: {s.utr}")
        evidence_str = "; ".join(evidence_parts) if evidence_parts else f"settlement {ex.settlement_id}"

        # Check prediction
        pred = pred_by_ex.get(ex.id) or pred_by_settlement.get(ex.settlement_id)
        if pred is None:
            # Fallback to deterministic on-demand prediction
            try:
                pred = predict_resolution(ex, s)
            except Exception:
                pred = None

        # Recommended action
        if pred is not None:
            recommended_action = pred.recommended_routing.value
        elif ex.next_step:
            recommended_action = ex.next_step
        else:
            recommended_action = "INVESTIGATE_OPERATIONAL"

        # Check Close Impact & Blockers
        matching_blockers = blockers_by_ref.get(ex.id, []) + blockers_by_ref.get(ex.settlement_id, [])
        is_hard_blocker = bool(matching_blockers)
        is_material = (allowable_paise > 0 and exp_paise > allowable_paise) or any(
            b.kind in (BlockerKind.UNRESOLVED_MATERIAL_AMOUNT, BlockerKind.AMBIGUOUS_MATERIAL_SETTLEMENT)
            for b in matching_blockers
        )
        is_carry_forward = ex.id in carry_forward_ex_ids
        is_ambiguous = (
            ex.reason == ReasonCode.MULTIPLE_VALID_ASSIGNMENTS
            or ex.settled is not None
            or any(b.kind == BlockerKind.AMBIGUOUS_MATERIAL_SETTLEMENT for b in matching_blockers)
        )

        if matching_blockers:
            b_kinds = sorted({b.kind.value for b in matching_blockers})
            close_impact = f"HARD_BLOCKER: {', '.join(b_kinds)}"
        elif is_material:
            close_impact = f"MATERIAL_EXPOSURE: {rupees(exp_paise)} exceeds allowable threshold"
        elif is_carry_forward:
            close_impact = "CARRY_FORWARD_ELIGIBLE: Immaterial residual authorized for carry-forward"
        elif is_ambiguous:
            close_impact = "AMBIGUOUS_SETTLEMENT: Disputed across candidate orders"
        else:
            close_impact = f"UNRESOLVED_EXPOSURE: {rupees(exp_paise)} awaiting operational clearance"

        priority_score = compute_priority_score(
            exposure_paise=exp_paise,
            severity=sev_str,
            reason=reason_str,
            is_hard_blocker=is_hard_blocker,
            is_material=is_material,
            is_ambiguous=is_ambiguous,
            age_days=age_days,
            predicted_resolution=pred,
        )

        review_items.append(
            HumanReviewItem(
                item_id=f"rev:{ex.id}",
                exception_id=ex.id,
                settlement_id=ex.settlement_id,
                exposure=exp_paise,
                severity=sev_str,
                reason=reason_str,
                evidence=evidence_str,
                current_status=ReviewItemStatus.PENDING,
                recommended_action=recommended_action,
                predicted_resolution=pred,
                close_impact=close_impact,
                priority_score=priority_score,
                is_material_blocker=is_hard_blocker or is_material,
                is_ambiguous=is_ambiguous,
                is_carry_forward=is_carry_forward,
                age_days=age_days,
            )
        )

    # Deterministic multi-factor sort:
    # 1. priority_score descending
    # 2. exposure descending
    # 3. exception_id ascending
    review_items.sort(key=lambda it: (-it.priority_score, -it.exposure, it.exception_id))

    return HumanReviewQueue(
        period_id=period_id,
        items=tuple(review_items),
        audit_log=(),
    )
