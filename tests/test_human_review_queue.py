"""Tests for ClosePilot Phase 2D: Deterministic Human Review Queue.

Verifies:
1. All 9 required review item dimensions are present:
   - exception ID
   - exposure
   - severity
   - reason
   - evidence
   - current status
   - recommended action
   - predicted resolution
   - close impact
2. Prioritization by Financial Impact + Safety + Urgency.
3. Material blockers prioritized at top of queue.
4. Ambiguous cases correctly tagged and scored.
5. Carry-forward cases identified and given appropriate close impact.
6. Deterministic ordering and permutation invariance.
7. Auditability: explicit actions, mandatory justification/reviewer, tamper-evident hash.
8. Non-mutation of financial truth.
"""

from __future__ import annotations

import datetime
from typing import Sequence

import pytest

from attest.close.exposure import ExposureItem, ExposureKind, PeriodExposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import (
    Blocker,
    BlockerKind,
    CarryForwardItem,
    PeriodVerdict,
    ReadinessDecision,
)
from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement

from closepilot.predictor import (
    ConfidenceTier,
    ResolutionFeatures,
    ResolutionPrediction,
    ResolutionRouting,
)
from closepilot.review_queue import (
    HumanActionRecord,
    HumanActionType,
    HumanReviewItem,
    HumanReviewQueue,
    ReviewItemStatus,
    build_review_queue,
    compute_priority_score,
)


def _make_dummy_prediction(
    exception_id: str,
    settlement_id: str,
    prob: float = 0.85,
    horizon: int = 2,
    routing: ResolutionRouting = ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE,
) -> ResolutionPrediction:
    features = ResolutionFeatures(
        exception_id=exception_id,
        settlement_id=settlement_id,
        reason_code=ReasonCode.TIMING_MISMATCH.value,
        severity=Severity.LOW.value,
        age_days=1,
        exposure_paise=5000,
        settlement_value_paise=100000,
        exposure_ratio=0.05,
        has_partial_match=True,
        has_established_orders=True,
        has_missing_evidence_ref=False,
        ambiguity_count=1,
        prior_attempts=1,
    )
    return ResolutionPrediction(
        exception_id=exception_id,
        settlement_id=settlement_id,
        probability=prob,
        expected_horizon_days=horizon,
        confidence=ConfidenceTier.HIGH,
        confidence_score=0.9,
        recommended_routing=routing,
        rationale="Timing mismatch cleared by T+2 settlement window",
        features=features,
        feature_contributions={"prior": 0.88, "age": -0.03},
    )


class TestHumanReviewQueue:
    """Test suite for ClosePilot Human Review Queue."""

    def test_review_item_contains_all_required_fields(self) -> None:
        """Every review item must contain all 9 required operational fields."""
        ex = Exception_(
            id="EX-00001",
            settlement_id="SETTLE-001",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=100_000,
            unexplained_paise=2_500,
            established=("order ORD-1 matches partially",),
            missing="missing capture record",
            next_step="confirm payout calendar",
            partial=None,
            settled=None,
        )
        pred = _make_dummy_prediction("EX-00001", "SETTLE-001")
        queue = build_review_queue(
            exceptions=[ex],
            predictions=[pred],
            period_id="P-2026-09",
        )

        assert len(queue.items) == 1
        item = queue.items[0]

        # 1. exception ID
        assert item.exception_id == "EX-00001"
        # 2. exposure
        assert item.exposure == 2_500
        # 3. severity
        assert item.severity == "LOW"
        # 4. reason
        assert item.reason == "TIMING_MISMATCH"
        # 5. evidence
        assert "missing capture record" in item.evidence
        assert "order ORD-1 matches partially" in item.evidence
        # 6. current status
        assert item.current_status == ReviewItemStatus.PENDING
        # 7. recommended action
        assert item.recommended_action == ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE.value
        # 8. predicted resolution
        assert item.predicted_resolution is not None
        assert item.predicted_resolution.probability == 0.85
        # 9. close impact
        assert "UNRESOLVED_EXPOSURE" in item.close_impact

        # Check export serializability
        d = item.to_dict()
        assert d["exception_id"] == "EX-00001"
        assert d["current_status"] == "PENDING"
        assert d["predicted_resolution"]["probability"] == 0.85

    def test_prioritization_formula(self) -> None:
        """Verify priority formula accounts for safety, financial impact, and urgency."""
        # 1. Hard blocker gives massive safety boost
        score_normal = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
        )
        score_blocker = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=True,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
        )
        assert score_blocker >= score_normal + 1_000_000

        # 2. Higher financial exposure increases priority score
        score_low_val = compute_priority_score(
            exposure_paise=10_000,  # ₹100
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
        )
        score_high_val = compute_priority_score(
            exposure_paise=10_000_000,  # ₹100,000
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
        )
        assert score_high_val > score_low_val

        # 3. Urgency: Stale item has higher priority than brand new item
        score_fresh = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=1,
        )
        score_stale = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=30,
        )
        assert score_stale > score_fresh

        # 4. Urgency: Low resolution probability increases human review urgency
        pred_likely = _make_dummy_prediction("EX-1", "S-1", prob=0.95)
        pred_unlikely = _make_dummy_prediction("EX-2", "S-2", prob=0.05)
        score_auto = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
            predicted_resolution=pred_likely,
        )
        score_manual = compute_priority_score(
            exposure_paise=10_000,
            severity="LOW",
            reason="TIMING_MISMATCH",
            is_hard_blocker=False,
            is_material=False,
            is_ambiguous=False,
            age_days=0,
            predicted_resolution=pred_unlikely,
        )
        assert score_manual > score_auto

    def test_material_blockers(self) -> None:
        """Material blockers must be tagged, flagged as blockers, and placed at top of queue."""
        ex_immaterial = Exception_(
            id="EX-IMMAT",
            settlement_id="SETTLE-001",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=100_000,
            unexplained_paise=500,
            established=(),
            missing="",
            next_step="",
            partial=None,
            settled=None,
        )
        ex_material_blocker = Exception_(
            id="EX-MAT-BLOCK",
            settlement_id="SETTLE-002",
            reason=ReasonCode.MISSING_TRANSACTION,
            severity=Severity.HIGH,
            amount_paise=50_000_000,
            unexplained_paise=50_000_000,
            established=(),
            missing="full settlement missing",
            next_step="escalate",
            partial=None,
            settled=None,
        )

        blocker = Blocker(
            kind=BlockerKind.UNRESOLVED_MATERIAL_AMOUNT,
            ref_id="EX-MAT-BLOCK",
            reason="unresolved exposure exceeds materiality threshold",
            exposure_paise=50_000_000,
        )
        verdict = PeriodVerdict(
            period_id="P-1",
            decision=ReadinessDecision.BLOCKED,
            reasons=("material exposure blocker",),
            material_exposure_paise=50_000_000,
            carry_forward=(),
            blockers=("EX-MAT-BLOCK",),
            structured_blockers=(blocker,),
        )

        queue = build_review_queue(
            exceptions=[ex_immaterial, ex_material_blocker],
            verdict=verdict,
            period_id="P-1",
        )

        assert len(queue.items) == 2
        # The material blocker MUST be first
        top_item = queue.items[0]
        assert top_item.exception_id == "EX-MAT-BLOCK"
        assert top_item.is_material_blocker is True
        assert "HARD_BLOCKER: UNRESOLVED_MATERIAL_AMOUNT" in top_item.close_impact

        # Blocker items query
        blockers = queue.get_blocker_items()
        assert len(blockers) == 1
        assert blockers[0].exception_id == "EX-MAT-BLOCK"

    def test_ambiguous_cases(self) -> None:
        """Ambiguous settlements must be flagged and routed appropriately."""
        ex_ambiguous = Exception_(
            id="EX-AMB-01",
            settlement_id="SETTLE-AMB",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.MEDIUM,
            amount_paise=200_000,
            unexplained_paise=50_000,
            established=("3 explanations satisfy amount",),
            missing="order-level reference",
            next_step="supply order reference",
            partial=None,
            settled=None,
        )

        queue = build_review_queue(
            exceptions=[ex_ambiguous],
            period_id="P-1",
        )

        assert len(queue.items) == 1
        item = queue.items[0]
        assert item.is_ambiguous is True
        assert "AMBIGUOUS_SETTLEMENT" in item.close_impact

        amb_items = queue.get_ambiguous_items()
        assert len(amb_items) == 1
        assert amb_items[0].exception_id == "EX-AMB-01"

    def test_carry_forward_cases(self) -> None:
        """Carry forward items must be explicitly recognized and authorized."""
        ex_cf = Exception_(
            id="EX-CF-01",
            settlement_id="SETTLE-CF",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=1_000,
            established=(),
            missing="",
            next_step="wait for next cycle",
            partial=None,
            settled=None,
        )
        cf_item = CarryForwardItem(
            exception_id="EX-CF-01",
            settlement_id="SETTLE-CF",
            exposure_paise=1_000,
            reason="TIMING_MISMATCH",
            age_days=2,
            severity="LOW",
            close_impact="Immaterial residual within threshold",
            next_step="wait for next cycle",
            evidence="settlement SETTLE-CF",
        )
        verdict = PeriodVerdict(
            period_id="P-1",
            decision=ReadinessDecision.READY_WITH_CARRY_FORWARD,
            reasons=("carry forward approved",),
            material_exposure_paise=0,
            carry_forward=("EX-CF-01",),
            blockers=(),
            carry_forward_items=(cf_item,),
        )

        queue = build_review_queue(
            exceptions=[ex_cf],
            verdict=verdict,
            period_id="P-1",
        )

        assert len(queue.items) == 1
        item = queue.items[0]
        assert item.is_carry_forward is True
        assert "CARRY_FORWARD_ELIGIBLE" in item.close_impact

        cf_list = queue.get_carry_forward_items()
        assert len(cf_list) == 1
        assert cf_list[0].exception_id == "EX-CF-01"

    def test_deterministic_ordering_permutation_invariance(self) -> None:
        """Permuting input exceptions must produce the exact same deterministic review queue."""
        exs = [
            Exception_(
                id=f"EX-{i:03d}",
                settlement_id=f"S-{i}",
                reason=ReasonCode.TIMING_MISMATCH if i % 2 == 0 else ReasonCode.MISSING_TRANSACTION,
                severity=Severity.HIGH if i == 5 else Severity.LOW,
                amount_paise=10_000 * i,
                unexplained_paise=500 * i,
                established=(),
                missing="",
                next_step="",
                partial=None,
                settled=None,
            )
            for i in range(1, 10)
        ]

        q1 = build_review_queue(exceptions=exs, period_id="P-DET")
        q2 = build_review_queue(exceptions=list(reversed(exs)), period_id="P-DET")
        q3 = build_review_queue(exceptions=sorted(exs, key=lambda e: e.amount_paise), period_id="P-DET")

        order1 = [it.exception_id for it in q1.items]
        order2 = [it.exception_id for it in q2.items]
        order3 = [it.exception_id for it in q3.items]

        assert order1 == order2 == order3
        scores1 = [it.priority_score for it in q1.items]
        scores2 = [it.priority_score for it in q2.items]
        assert scores1 == scores2

    def test_auditability_valid_action_recording(self) -> None:
        """Human action recording must update item status and append tamper-evident audit record."""
        ex = Exception_(
            id="EX-ACT-01",
            settlement_id="SETTLE-001",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.MEDIUM,
            amount_paise=50_000,
            unexplained_paise=2_000,
            established=(),
            missing="unexplained fee residual",
            next_step="check fee adjustment",
            partial=None,
            settled=None,
        )

        queue = build_review_queue(exceptions=[ex], period_id="P-AUDIT")
        assert len(queue.items) == 1
        assert queue.items[0].current_status == ReviewItemStatus.PENDING
        assert len(queue.audit_log) == 0

        # Action: Approve manual adjustment
        new_queue = queue.record_action(
            exception_id="EX-ACT-01",
            action_type=HumanActionType.APPROVE_MANUAL_ADJUSTMENT,
            reviewer="lead.controller@company.com",
            justification="Approved ₹20 fee adjustment per payment gateway invoice #9921",
            evidence_ref="INV-9921",
            timestamp="2026-09-04T12:00:00Z",
        )

        # Original queue must be unmutated (immutability guarantee)
        assert queue.items[0].current_status == ReviewItemStatus.PENDING
        assert len(queue.audit_log) == 0

        # New queue must reflect actioned status and audit trail
        assert new_queue.items[0].current_status == ReviewItemStatus.ACTIONED
        assert len(new_queue.audit_log) == 1

        record = new_queue.audit_log[0]
        assert record.exception_id == "EX-ACT-01"
        assert record.reviewer == "lead.controller@company.com"
        assert record.action_type == HumanActionType.APPROVE_MANUAL_ADJUSTMENT
        assert record.previous_status == ReviewItemStatus.PENDING
        assert record.new_status == ReviewItemStatus.ACTIONED
        assert record.evidence_ref == "INV-9921"
        assert len(record.action_hash) == 64  # Valid SHA-256

        # History lookup
        actions = new_queue.get_actions_for_item("EX-ACT-01")
        assert len(actions) == 1
        assert actions[0] == record

    def test_action_types_and_status_transitions(self) -> None:
        """Verify different action types produce appropriate status transitions."""
        ex = Exception_(
            id="EX-TRANS-01",
            settlement_id="SETTLE-001",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=10_000,
            unexplained_paise=500,
            established=(),
            missing="",
            next_step="",
            partial=None,
            settled=None,
        )
        queue = build_review_queue(exceptions=[ex], period_id="P-1")

        # 1. Defer review -> DEFERRED
        q_def = queue.record_action(
            exception_id="EX-TRANS-01",
            action_type=HumanActionType.DEFER_REVIEW,
            reviewer="analyst@company.com",
            justification="Deferring 24h for bank settlement file",
        )
        assert q_def.items[0].current_status == ReviewItemStatus.DEFERRED

        # 2. Assign reviewer -> IN_REVIEW
        q_rev = queue.record_action(
            exception_id="EX-TRANS-01",
            action_type=HumanActionType.ASSIGN_REVIEWER,
            reviewer="specialist@company.com",
            justification="Assigned to specialist for dispute verification",
        )
        assert q_rev.items[0].current_status == ReviewItemStatus.IN_REVIEW
        assert q_rev.items[0].assigned_reviewer == "specialist@company.com"

        # 3. Gateway dispute -> ACTIONED
        q_act = queue.record_action(
            exception_id="EX-TRANS-01",
            action_type=HumanActionType.SUBMIT_GATEWAY_DISPUTE,
            reviewer="ops@company.com",
            justification="Filing dispute ticket #8841 with gateway",
        )
        assert q_act.items[0].current_status == ReviewItemStatus.ACTIONED

    def test_never_silently_resolve_and_validation(self) -> None:
        """The queue must reject any human action lacking explicit reviewer or justification."""
        ex = Exception_(
            id="EX-SAFE-01",
            settlement_id="SETTLE-001",
            reason=ReasonCode.MISSING_TRANSACTION,
            severity=Severity.HIGH,
            amount_paise=100_000,
            unexplained_paise=100_000,
            established=(),
            missing="missing",
            next_step="find",
            partial=None,
            settled=None,
        )
        queue = build_review_queue(exceptions=[ex], period_id="P-1")

        # Empty reviewer
        with pytest.raises(ValueError, match="Explicit reviewer is required"):
            queue.record_action(
                exception_id="EX-SAFE-01",
                action_type=HumanActionType.APPROVE_MANUAL_ADJUSTMENT,
                reviewer="",
                justification="Some justification",
            )

        # Whitespace-only justification
        with pytest.raises(ValueError, match="Explicit justification is required"):
            queue.record_action(
                exception_id="EX-SAFE-01",
                action_type=HumanActionType.APPROVE_MANUAL_ADJUSTMENT,
                reviewer="controller@company.com",
                justification="   ",
            )

        # Non-existent exception
        with pytest.raises(ValueError, match="not found in review queue"):
            queue.record_action(
                exception_id="EX-DOES-NOT-EXIST",
                action_type=HumanActionType.APPROVE_MANUAL_ADJUSTMENT,
                reviewer="controller@company.com",
                justification="Valid justification",
            )

    def test_financial_truth_non_mutation(self) -> None:
        """Human review actions must never mutate underlying exceptions or financial truth."""
        ex = Exception_(
            id="EX-MUT-01",
            settlement_id="SETTLE-001",
            reason=ReasonCode.MISSING_TRANSACTION,
            severity=Severity.HIGH,
            amount_paise=250_000,
            unexplained_paise=250_000,
            established=("established fact",),
            missing="missing capture",
            next_step="request re-export",
            partial=None,
            settled=None,
        )
        settle = Settlement(
            settlement_id="SETTLE-001",
            settled_on=datetime.date(2026, 9, 1),
            net_paise=250_000,
            utr="UTR9999",
        )

        queue = build_review_queue(
            exceptions=[ex],
            settlements=[settle],
            period_id="P-MUT",
        )

        # Action the item in the review queue
        actioned_queue = queue.record_action(
            exception_id="EX-MUT-01",
            action_type=HumanActionType.APPROVE_MANUAL_ADJUSTMENT,
            reviewer="lead.controller@company.com",
            justification="Approved adjustment in ops tracking system",
        )

        # Assert queue item status is ACTIONED
        assert actioned_queue.items[0].current_status == ReviewItemStatus.ACTIONED

        # CRITICAL: Underlying Exception_ remains 100% identical and unmutated
        assert ex.id == "EX-MUT-01"
        assert ex.unexplained_paise == 250_000
        assert ex.amount_paise == 250_000
        assert ex.severity == Severity.HIGH
        assert ex.missing == "missing capture"

        # CRITICAL: Underlying Settlement remains 100% identical and unmutated
        assert settle.net_paise == 250_000
        assert settle.settlement_id == "SETTLE-001"
        assert settle.utr == "UTR9999"

    def test_rendered_output_and_serialization(self) -> None:
        """Verify queue ASCII table rendering and dictionary serialization."""
        ex1 = Exception_(
            id="EX-R1",
            settlement_id="S-1",
            reason=ReasonCode.DATA_QUALITY,
            severity=Severity.HIGH,
            amount_paise=100_000,
            unexplained_paise=100_000,
            established=(),
            missing="malformed record",
            next_step="check export",
            partial=None,
            settled=None,
        )
        ex2 = Exception_(
            id="EX-R2",
            settlement_id="S-2",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=200,
            established=(),
            missing="",
            next_step="",
            partial=None,
            settled=None,
        )

        queue = build_review_queue(exceptions=[ex1, ex2], period_id="P-RENDER")
        rendered = queue.render()

        assert "CLOSEPILOT HUMAN REVIEW QUEUE" in rendered
        assert "EX-R1" in rendered
        assert "EX-R2" in rendered
        assert "Score" in rendered
        assert "Exposure" in rendered

        d = queue.to_dict()
        assert d["period_id"] == "P-RENDER"
        assert d["total_items"] == 2
        assert d["pending_count"] == 2
        assert len(d["items"]) == 2
