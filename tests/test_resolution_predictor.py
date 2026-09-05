"""Tests for ClosePilot Resolution Predictor (Phase 2A).

Verifies statistical resolution predictions:
- Deterministic and reproducible scoring
- Feature extraction across Exception_, CarryForwardItem, and dict models
- Boundary cases (zero exposure, extreme values, missing optional attributes)
- Blocker and high-exposure routing
- Hazard-specific routing and horizons
- Zero mutation of financial truth, readiness, or ledger state
"""

from __future__ import annotations

from datetime import date

import pytest

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement

from closepilot.predictor import (
    ConfidenceTier,
    ResolutionFeatures,
    ResolutionPrediction,
    ResolutionRouting,
    extract_features,
    predict_batch,
    predict_resolution,
)
from attest.close.readiness import CarryForwardItem


def _sample_settlement(sid: str = "s1", net: int = 100_000) -> Settlement:
    return Settlement(
        settlement_id=sid,
        settled_on=date(2026, 8, 10),
        net_paise=net,
        utr=f"UTR_{sid}",
    )


def _sample_exception(
    eid: str = "EX-01",
    sid: str = "s1",
    reason: ReasonCode = ReasonCode.TIMING_MISMATCH,
    severity: Severity = Severity.LOW,
    amount: int = 100_000,
    unexplained: int = 2_000,
    missing: str = "calendar sync",
) -> Exception_:
    return Exception_(
        id=eid,
        settlement_id=sid,
        reason=reason,
        severity=severity,
        amount_paise=amount,
        unexplained_paise=unexplained,
        established=(),
        missing=missing,
        next_step="await payout",
        partial=None,
    )


class TestResolutionPredictor:
    """Test suite for ClosePilot Resolution Predictor."""

    def test_deterministic_output(self) -> None:
        """1. Prediction is 100% deterministic and reproducible across repeated runs."""
        s = _sample_settlement()
        ex = _sample_exception()
        feats1 = extract_features(ex, settlement=s, age_days=2)
        feats2 = extract_features(ex, settlement=s, age_days=2)

        pred1 = predict_resolution(feats1)
        pred2 = predict_resolution(feats2)

        assert pred1.probability == pred2.probability
        assert pred1.expected_horizon_days == pred2.expected_horizon_days
        assert pred1.confidence == pred2.confidence
        assert pred1.recommended_routing == pred2.recommended_routing
        assert pred1.to_dict() == pred2.to_dict()

    def test_repeated_evaluation_idempotence(self) -> None:
        """2. 50 repeated evaluations produce bit-for-bit identical outputs."""
        s = _sample_settlement()
        ex = _sample_exception(reason=ReasonCode.REFUND_MISMATCH, unexplained=1_500)
        feats = extract_features(ex, settlement=s, age_days=1)
        base = predict_resolution(feats)

        for _ in range(50):
            p = predict_resolution(feats)
            assert p.probability == base.probability
            assert p.confidence_score == base.confidence_score
            assert p.expected_horizon_days == base.expected_horizon_days

    def test_boundary_cases(self) -> None:
        """3. Boundary cases: age=0, massive age, probability bounded to [0.01, 0.99]."""
        s = _sample_settlement()
        ex = _sample_exception(reason=ReasonCode.DATA_QUALITY, severity=Severity.HIGH, unexplained=100_000)

        # Extremely hard exception, very stale (60 days old)
        feats_stale = extract_features(ex, settlement=s, age_days=60)
        pred_stale = predict_resolution(feats_stale)
        assert 0.01 <= pred_stale.probability <= 0.99
        assert pred_stale.probability <= 0.05
        assert pred_stale.expected_horizon_days >= 14

        # Fresh timing mismatch (0 days old)
        ex_fresh = _sample_exception(reason=ReasonCode.TIMING_MISMATCH, severity=Severity.LOW, unexplained=100)
        feats_fresh = extract_features(ex_fresh, settlement=s, age_days=0)
        pred_fresh = predict_resolution(feats_fresh)
        assert 0.01 <= pred_fresh.probability <= 0.99
        assert pred_fresh.probability >= 0.85
        assert pred_fresh.expected_horizon_days <= 3

    def test_zero_exposure(self) -> None:
        """4. Zero exposure residual: handles 0 paise cleanly without divide-by-zero."""
        s = _sample_settlement()
        ex = _sample_exception(unexplained=0)
        feats = extract_features(ex, settlement=s, age_days=1)

        assert feats.exposure_paise == 0
        assert feats.exposure_ratio == 0.0

        pred = predict_resolution(feats)
        assert pred.probability > 0.50
        assert pred.features.exposure_paise == 0

    def test_high_exposure_routing(self) -> None:
        """5. High exposure residual (> Rs 10,000 = 1,000,000 paise) routes to MANUAL_AUDIT."""
        s = _sample_settlement(net=5_000_000)
        ex = _sample_exception(unexplained=1_500_000)  # Rs 15,000
        feats = extract_features(ex, settlement=s, age_days=1)
        pred = predict_resolution(feats)

        assert pred.recommended_routing is ResolutionRouting.MANUAL_AUDIT
        assert "High exposure" in pred.rationale
        assert pred.probability < 0.90  # Large exposure dampens probability

    def test_blocker_and_high_severity_exceptions(self) -> None:
        """6. Blocker exceptions (HIGH severity, Chargeback, Data Quality) route accordingly."""
        s = _sample_settlement()

        # High severity -> MANUAL_AUDIT
        ex_high = _sample_exception(severity=Severity.HIGH, unexplained=10_000)
        p_high = predict_resolution(extract_features(ex_high, s))
        assert p_high.recommended_routing is ResolutionRouting.MANUAL_AUDIT

        # Chargeback -> ESCALATE_FINANCE_DISPUTE
        ex_cb = _sample_exception(reason=ReasonCode.CHARGEBACK, severity=Severity.LOW, unexplained=5_000)
        p_cb = predict_resolution(extract_features(ex_cb, s))
        assert p_cb.recommended_routing is ResolutionRouting.ESCALATE_FINANCE_DISPUTE
        assert p_cb.expected_horizon_days >= 20

        # Data quality -> DATA_OPS_CORRECTION
        ex_dq = _sample_exception(reason=ReasonCode.DATA_QUALITY, severity=Severity.LOW, unexplained=5_000)
        p_dq = predict_resolution(extract_features(ex_dq, s))
        assert p_dq.recommended_routing is ResolutionRouting.DATA_OPS_CORRECTION
        assert p_dq.probability <= 0.20

    def test_missing_features_and_dict_compatibility(self) -> None:
        """7. Missing features: works seamlessly with dict input with minimal keys."""
        min_dict = {
            "exception_id": "EX-MIN",
            "settlement_id": "s_min",
        }
        feats = extract_features(min_dict)
        assert feats.exception_id == "EX-MIN"
        assert feats.settlement_id == "s_min"
        assert feats.exposure_paise == 0
        assert feats.age_days == 0
        assert feats.reason_code == ReasonCode.UNKNOWN_ADJUSTMENT.value

        pred = predict_resolution(feats)
        assert 0.01 <= pred.probability <= 0.99
        assert pred.recommended_routing is not None

    def test_carry_forward_item_feature_extraction(self) -> None:
        """8. Works seamlessly with CarryForwardItem instances."""
        cf = CarryForwardItem(
            exception_id="EX-CF-99",
            settlement_id="s1",
            exposure_paise=1_500,
            reason=ReasonCode.TIMING_MISMATCH.value,
            age_days=2,
            severity=Severity.LOW.value,
            close_impact="immaterial exposure within allowable threshold",
            next_step="await next payout cycle",
            evidence="missing UTR_s1 in gateway ledger",
        )
        s = _sample_settlement()
        feats = extract_features(cf, settlement=s)

        assert feats.exception_id == "EX-CF-99"
        assert feats.settlement_id == "s1"
        assert feats.exposure_paise == 1_500
        assert feats.age_days == 2
        assert feats.has_missing_evidence_ref is True  # Detected 'utr' in evidence

        pred = predict_resolution(feats)
        assert pred.probability >= 0.80
        assert pred.recommended_routing is ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE

    def test_hazard_specific_priors_and_decay(self) -> None:
        """9. Verification of priors across key hazard families."""
        s = _sample_settlement()

        # Timing mismatch resolves much faster than unknown adjustment
        p_timing = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.TIMING_MISMATCH), s, age_days=1))
        p_adj = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.UNKNOWN_ADJUSTMENT), s, age_days=1))
        p_amb = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS), s, age_days=1))

        assert p_timing.probability > p_adj.probability > p_amb.probability

        # Age decay test: probability monotonically decreases with age
        p_age1 = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.TIMING_MISMATCH), s, age_days=1))
        p_age7 = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.TIMING_MISMATCH), s, age_days=7))
        p_age25 = predict_resolution(extract_features(_sample_exception(reason=ReasonCode.TIMING_MISMATCH), s, age_days=25))

        assert p_age1.probability > p_age7.probability > p_age25.probability

    def test_batch_prediction_ordering(self) -> None:
        """10. Batch prediction sorts lowest resolution probability first (highest operational risk first)."""
        s = _sample_settlement()
        ex1 = _sample_exception("EX-TIMING", reason=ReasonCode.TIMING_MISMATCH, unexplained=1_000)
        ex2 = _sample_exception("EX-CHARGEBACK", reason=ReasonCode.CHARGEBACK, unexplained=5_000)
        ex3 = _sample_exception("EX-REFUND", reason=ReasonCode.REFUND_MISMATCH, unexplained=2_000)

        preds = predict_batch([ex1, ex2, ex3], settlements={"s1": s}, age_days=2)
        assert len(preds) == 3

        # Lowest probability first: CHARGEBACK < REFUND < TIMING
        assert preds[0].exception_id == "EX-CHARGEBACK"
        assert preds[1].exception_id == "EX-REFUND"
        assert preds[2].exception_id == "EX-TIMING"

    def test_immutable_safety_contract(self) -> None:
        """11. The predictor never mutates input objects or financial state."""
        s = _sample_settlement()
        ex = _sample_exception()

        orig_amount = ex.amount_paise
        orig_unexplained = ex.unexplained_paise
        orig_net = s.net_paise

        pred = predict_resolution(extract_features(ex, s))

        # Inputs remain completely unmodified
        assert ex.amount_paise == orig_amount
        assert ex.unexplained_paise == orig_unexplained
        assert s.net_paise == orig_net
        assert pred.features.exposure_paise == orig_unexplained
