"""Tests for the Close Readiness Controller (attest.close).

Verifies the Close Controller kernel:
    decide_period(period, findings, judgements, exceptions, materiality) -> PeriodVerdict

Ensures the three period-level decisions are reachable and adhere to safety invariants:
    - READY_TO_CLOSE: Zero unresolved material exposure, zero blockers.
    - READY_WITH_CARRY_FORWARD: Unresolved exposure is strictly below materiality,
      every carry-forward exception ID is explicitly named, zero blockers.
    - BLOCKED: Material exposure, compromised search spaces, policy blocks, or high severity.

Enforces rules from AGENTS.md:
    - Kernel outputs are read, never modified.
    - Uses calibration/synthetic seeds, never the held-out seed.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from attest.exceptions import (
    Exception_,
    ReasonCode,
    Severity,
    classify,
)
from attest.model import Settlement
from attest.policy import Decision, Judgement, RiskModel, decide
from attest.searchspace import Integrity, Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict

from attest.close.certificate import (
    CloseCertificate,
    compute_evidence_hash,
    issue_certificate,
)
from attest.close.exposure import (
    CurrencyMismatchError,
    ExposureItem,
    ExposureKind,
    PeriodExposure,
    assess_exposure,
)
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import (
    Blocker,
    BlockerKind,
    CarryForwardItem,
    PeriodVerdict,
    ReadinessDecision,
    decide_period,
)

_TODAY = date(2026, 9, 1)


# --------------------------------------------------------------------------
# Fixture helpers
# --------------------------------------------------------------------------

def _settlement(sid: str, net: int, settled_on: date | None = None) -> Settlement:
    return Settlement(
        settlement_id=sid,
        settled_on=settled_on or _TODAY,
        net_paise=net,
        utr=f"UTR_{sid}",
    )


def _proven_finding(sid: str, order_ids: tuple[str, ...], net: int) -> Finding:
    sp = SearchSpace(universe=100, members=frozenset(order_ids))
    sp.reductions.append(Reduction("test", 50, True, "candidate prune"))
    proof = Proof(
        settlement_id=sid,
        order_ids=order_ids,
        gross_paise=net,
        fee_paise=0,
        tax_paise=0,
        adjustment_paise=0,
        net_paise=net,
        residual_paise=0,
        tolerance_paise=0,
    )
    return Finding(
        settlement_id=sid,
        verdict=Verdict.PROVEN,
        proofs=(proof,),
        space=sp,
        layer="L3-dp/r0",
    )


def _ambiguous_finding(sid: str, net: int) -> Finding:
    p1 = Proof(sid, ("o1", "o2"), net, 0, 0, 0, net, 0, 0)
    p2 = Proof(sid, ("o1", "o3"), net, 0, 0, 0, net, 0, 0)
    sp = SearchSpace(universe=100, members=frozenset(("o1", "o2", "o3")))
    return Finding(
        settlement_id=sid,
        verdict=Verdict.AMBIGUOUS,
        proofs=(p1, p2),
        space=sp,
        layer="L3-dp/r0",
        exhaustive=True,
    )


def _compromised_finding(sid: str, net: int) -> Finding:
    sp = SearchSpace(universe=100, members=frozenset(("o1",)), known_loss=1)
    proof = Proof(sid, ("o1",), net, 0, 0, 0, net, 0, 0)
    return Finding(
        settlement_id=sid,
        verdict=Verdict.PROVEN,
        proofs=(proof,),
        space=sp,
        layer="L3-dp/r0",
    )


def _auto_post_judgement() -> Judgement:
    return Judgement(
        decision=Decision.AUTO_POST,
        expected_loss_paise=500,
        p_error=0.005,
        reasons=("expected loss below review cost",),
    )


def _block_judgement(reason: str = "unmeasured policy") -> Judgement:
    return Judgement(
        decision=Decision.BLOCK,
        expected_loss_paise=None,
        p_error=None,
        reasons=(reason,),
    )


def _review_judgement(reason: str = "manual review required") -> Judgement:
    return Judgement(
        decision=Decision.REVIEW,
        expected_loss_paise=35_000,
        p_error=0.05,
        reasons=(reason,),
    )


# --------------------------------------------------------------------------
# Test Period grouping
# --------------------------------------------------------------------------

class TestPeriodGrouping:
    def test_period_initialization_and_contains(self) -> None:
        p = Period(
            period_id="2026-08",
            settlement_ids=("s1", "s2"),
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )
        assert p.contains("s1")
        assert p.contains("s2")
        assert not p.contains("s3")

    def test_invalid_date_range_raises(self) -> None:
        with pytest.raises(ValueError, match="precedes start"):
            Period(
                period_id="invalid",
                settlement_ids=(),
                start=date(2026, 8, 31),
                end=date(2026, 8, 1),
            )

    def test_from_settlements(self) -> None:
        s1 = _settlement("s1", 1000)
        s2 = _settlement("s2", 2000)
        p = Period.from_settlements("P1", [s1, s2])
        assert p.settlement_ids == ("s1", "s2")
        assert p.period_id == "P1"

    def test_from_date_range(self) -> None:
        s1 = _settlement("s1", 1000, settled_on=date(2026, 8, 10))
        s2 = _settlement("s2", 2000, settled_on=date(2026, 8, 20))
        s3 = _settlement("s3", 3000, settled_on=date(2026, 9, 5))
        p = Period.from_date_range("AUG-2026", [s1, s2, s3], date(2026, 8, 1), date(2026, 8, 31))
        assert p.settlement_ids == ("s1", "s2")

    def test_filtering_helpers(self) -> None:
        p = Period(period_id="P1", settlement_ids=("s1",))
        s1 = _settlement("s1", 1000)
        s2 = _settlement("s2", 2000)
        assert p.filter_settlements([s1, s2]) == [s1]

        f1 = _proven_finding("s1", ("o1",), 1000)
        f2 = _proven_finding("s2", ("o2",), 2000)
        assert p.filter_findings([f1, f2]) == [f1]


# --------------------------------------------------------------------------
# Test Exposure Engine (Hardened)
# --------------------------------------------------------------------------

class TestExposureEngine:
    def test_one_exception(self) -> None:
        """1. One exception correctly reflects financial exposure."""
        s = _settlement("s1", 100_000)
        f = _ambiguous_finding("s1", 100_000)
        ex = Exception_(
            id="EX-001",
            settlement_id="s1",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.MEDIUM,
            amount_paise=100_000,
            unexplained_paise=25_000,
            established=(),
            missing="reference",
            next_step="confirm order",
            partial=None,
        )
        exp = assess_exposure([f], [ex], [s])
        assert exp.total_exposure_paise == 100_000
        assert exp.total_value_paise == 100_000
        assert exp.unresolved_count == 1
        assert exp.verified_count == 0
        assert len(exp.items) == 1
        assert exp.net_unresolved_exposure_paise == 100_000
        assert exp.gross_contested_claim_exposure_paise == 200_000
        assert exp.items[0].exposure_paise == 200_000

    def test_multiple_independent_exceptions(self) -> None:
        """2. Multiple independent exceptions aggregate exactly in integer paise."""
        s1 = _settlement("s1", 50_000)
        s2 = _settlement("s2", 80_000)
        s3 = _settlement("s3", 120_000)

        f1 = _ambiguous_finding("s1", 50_000)
        f2 = _ambiguous_finding("s2", 80_000)
        f3 = _proven_finding("s3", ("o3",), 120_000)

        ex1 = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=10_000,
            established=(), missing="", next_step="", partial=None,
        )
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.MEDIUM, amount_paise=80_000, unexplained_paise=35_000,
            established=(), missing="", next_step="", partial=None,
        )

        exp = assess_exposure([f1, f2, f3], [ex1, ex2], [s1, s2, s3])
        assert exp.total_exposure_paise == 130_000
        assert exp.total_value_paise == 250_000
        assert exp.verified_value_paise == 120_000
        assert exp.verified_value_paise + exp.net_unresolved_exposure_paise == exp.total_value_paise
        assert exp.gross_contested_claim_exposure_paise == 260_000
        assert exp.verified_count == 1
        assert exp.unresolved_count == 2

    def test_duplicate_finding(self) -> None:
        """3. Duplicate findings for the same settlement must never multiply exposure."""
        s = _settlement("s1", 50_000)
        f = _ambiguous_finding("s1", 50_000)
        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=15_000,
            established=(), missing="", next_step="", partial=None,
        )

        # Pass 3 identical findings
        exp = assess_exposure([f, f, f], [ex], [s])
        assert exp.total_settlements == 1
        assert exp.total_exposure_paise == 50_000
        assert exp.total_value_paise == 50_000
        assert len(exp.items) == 1

    def test_duplicate_exception_reference(self) -> None:
        """4. Duplicate exception references do not double-count the underlying exposure."""
        s = _settlement("s1", 50_000)
        f = _ambiguous_finding("s1", 50_000)
        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=20_000,
            established=(), missing="", next_step="", partial=None,
        )

        # Pass duplicate exception objects
        exp = assess_exposure([f], [ex, ex, ex], [s])
        assert exp.total_exposure_paise == 50_000
        assert len(exp.items) == 1

    def test_negative_adjustment(self) -> None:
        """5. Negative adjustments/residuals are measured as absolute financial risk."""
        s = _settlement("s1", 50_000)
        f = _ambiguous_finding("s1", 50_000)
        # Exception carrying signed/negative residual
        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.REFUND_MISMATCH,
            severity=Severity.MEDIUM, amount_paise=50_000, unexplained_paise=-12_000,
            established=(), missing="refund offset", next_step="reconcile refund", partial=None,
        )

        exp = assess_exposure([f], [ex], [s])
        # Risk must be non-negative magnitude of unverified money
        assert exp.total_exposure_paise == 50_000
        assert exp.net_unresolved_exposure_paise == 50_000
        assert exp.gross_contested_claim_exposure_paise == 100_000
        assert exp.items[0].exposure_paise == 100_000

    def test_zero_amount(self) -> None:
        """6. Zero-value exceptions contribute zero to total exposure."""
        s = _settlement("s1", 50_000)
        f = _proven_finding("s1", ("o1",), 50_000)
        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.SEARCH_SPACE_UNCERTAIN,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=0,
            established=(), missing="window verification", next_step="widen window", partial=None,
        )

        exp = assess_exposure([f], [ex], [s])
        assert exp.total_exposure_paise == 0
        assert exp.total_value_paise == 50_000

    def test_large_amount(self) -> None:
        """7. Pure integer arithmetic handles massive transaction scale without float overflow."""
        # ₹1,000 Crore period
        large_val = 1_000_000_000_000
        large_exp = 50_000_000_000
        s = _settlement("s1", large_val)
        f = _ambiguous_finding("s1", large_val)
        ex = Exception_(
            id="EX-LARGE", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.HIGH, amount_paise=large_val, unexplained_paise=large_exp,
            established=(), missing="", next_step="", partial=None,
        )

        exp = assess_exposure([f], [ex], [s])
        assert exp.total_value_paise == large_val
        assert exp.total_exposure_paise == large_val
        assert isinstance(exp.total_exposure_paise, int)

    def test_currency_mismatch(self) -> None:
        """8. Currency mismatch raises CurrencyMismatchError as a safety violation."""
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class USDSettlement:
            settlement_id: str
            settled_on: date
            net_paise: int
            utr: str | None = None
            currency: str = "USD"

        s_usd = USDSettlement("s_usd", _TODAY, 10_000)
        f = _ambiguous_finding("s_usd", 10_000)

        with pytest.raises(CurrencyMismatchError, match="Currency mismatch: expected INR, got USD"):
            assess_exposure([f], [], [s_usd], currency="INR")

    def test_mixed_positive_negative_exposure(self) -> None:
        """9. Mixed positive and negative errors across settlements do NOT net to zero."""
        s1 = _settlement("s1", 50_000)
        s2 = _settlement("s2", 50_000)

        f1 = _ambiguous_finding("s1", 50_000)
        f2 = _ambiguous_finding("s2", 50_000)

        # Settlement 1 has +₹50 discrepancy, Settlement 2 has -₹50 discrepancy
        ex1 = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=5_000,
            established=(), missing="", next_step="", partial=None,
        )
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW, amount_paise=50_000, unexplained_paise=-5_000,
            established=(), missing="", next_step="", partial=None,
        )

        exp = assess_exposure([f1, f2], [ex1, ex2], [s1, s2])
        # Crucial: 5,000 + 5,000 = 10,000 paise (both are risk!). Must NOT net to 0!
        assert exp.total_exposure_paise == 100_000

    def test_repeated_evaluation(self) -> None:
        """10. Repeated evaluations are 100% deterministic and invariant."""
        s = _settlement("s1", 75_000)
        f = _ambiguous_finding("s1", 75_000)
        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.MEDIUM, amount_paise=75_000, unexplained_paise=25_000,
            established=(), missing="", next_step="", partial=None,
        )

        first = assess_exposure([f], [ex], [s])
        for _ in range(100):
            nxt = assess_exposure([f], [ex], [s])
            assert first == nxt

    def test_reordered_inputs(self) -> None:
        """11. Reordering input collections yields identical exposure results."""
        s1 = _settlement("s1", 20_000)
        s2 = _settlement("s2", 30_000)
        s3 = _settlement("s3", 50_000)

        f1 = _ambiguous_finding("s1", 20_000)
        f2 = _ambiguous_finding("s2", 30_000)
        f3 = _ambiguous_finding("s3", 50_000)

        ex1 = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.DATA_QUALITY, severity=Severity.LOW, amount_paise=20_000, unexplained_paise=5_000, established=(), missing="", next_step="", partial=None)
        ex2 = Exception_(id="EX-2", settlement_id="s2", reason=ReasonCode.DATA_QUALITY, severity=Severity.LOW, amount_paise=30_000, unexplained_paise=15_000, established=(), missing="", next_step="", partial=None)
        ex3 = Exception_(id="EX-3", settlement_id="s3", reason=ReasonCode.DATA_QUALITY, severity=Severity.LOW, amount_paise=50_000, unexplained_paise=25_000, established=(), missing="", next_step="", partial=None)

        order_a = assess_exposure([f1, f2, f3], [ex1, ex2, ex3], [s1, s2, s3])
        order_b = assess_exposure([f3, f1, f2], [ex2, ex3, ex1], [s3, s1, s2])

        assert order_a.total_exposure_paise == order_b.total_exposure_paise
        assert order_a.total_value_paise == order_b.total_value_paise
        assert [i.settlement_id for i in order_a.items] == [i.settlement_id for i in order_b.items]

    def test_multiple_findings_for_one_exception(self) -> None:
        """12. Multiple findings for the same settlement with one exception are not multiplied."""
        s = _settlement("s1", 100_000)
        f_rung0 = _ambiguous_finding("s1", 100_000)
        f_rung1 = _ambiguous_finding("s1", 100_000)

        ex = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=100_000, unexplained_paise=20_000,
            established=(), missing="", next_step="", partial=None,
        )

        exp = assess_exposure([f_rung0, f_rung1], [ex], [s])
        assert exp.total_settlements == 1
        assert exp.total_exposure_paise == 100_000
        assert len(exp.items) == 1


# --------------------------------------------------------------------------
# Test Materiality Policy (Hardened)
# --------------------------------------------------------------------------

class TestMaterialityPolicy:
    def test_percentage_threshold(self) -> None:
        """1. Percentage / basis-point scaling without hard-coded assumptions."""
        # 50 bps = 0.50%
        b50 = MaterialityBound(threshold_bps=50, floor_paise=0, ceiling_paise=100_000_000)
        assert b50.max_allowable_exposure_paise(10_000_000) == 50_000  # ₹1,00,000 * 0.5% = ₹500

        # 250 bps = 2.50%
        b250 = MaterialityBound(threshold_bps=250, floor_paise=0, ceiling_paise=100_000_000)
        assert b250.max_allowable_exposure_paise(10_000_000) == 250_000  # ₹1,00,000 * 2.5% = ₹2,500

        # 10 bps = 0.10%
        b10 = MaterialityBound(threshold_bps=10, floor_paise=0, ceiling_paise=100_000_000)
        assert b10.max_allowable_exposure_paise(10_000_000) == 10_000  # ₹1,00,000 * 0.1% = ₹100

    def test_absolute_floor(self) -> None:
        """2. Absolute floor clamps small percentages on low period values."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        # 1% of ₹500 (50,000 paise) is ₹5 (500 paise), which is below ₹100 (10,000 paise) floor
        assert bound.max_allowable_exposure_paise(50_000) == 10_000
        assessment = bound.assess(5_000, 50_000)
        assert assessment.governing_factor == "FLOOR"
        assert not assessment.is_material

    def test_absolute_ceiling(self) -> None:
        """3. Absolute ceiling clamps percentage exposure on high period values."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        # 1% of ₹50,00,000 (500,000,000 paise) is ₹50,000 (5,000,000 paise), below ceiling
        assert bound.max_allowable_exposure_paise(500_000_000) == 5_000_000

        # 1% of ₹5,00,00,000 (5,000,000,000 paise) is ₹5,00,000, capped by ceiling ₹1,00,000 (10,000,000 paise)
        assert bound.max_allowable_exposure_paise(5_000_000_000) == 10_000_000
        assessment = bound.assess(15_000_000, 5_000_000_000)
        assert assessment.governing_factor == "CEILING"
        assert assessment.is_material

    def test_zero_value_period(self) -> None:
        """4. Zero-value period defaults safely to floor without division by zero."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        assert bound.max_allowable_exposure_paise(0) == 10_000
        assert bound.max_allowable_exposure_paise(-1000) == 10_000
        assert not bound.is_material(5_000, 0)
        assert bound.is_material(15_000, 0)
        assert "zero-value period" in bound.explain_threshold(0)

    def test_very_large_values(self) -> None:
        """5. Integer arithmetic handles high transaction volumes without float overflow."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=100_000_000_000)
        # ₹1,000 Crore = 10,000,000,000 Rupees = 1,000,000,000,000 Paise
        large_total = 1_000_000_000_000
        expected = large_total * 100 // 10_000  # ₹10 Crore in paise
        assert bound.max_allowable_exposure_paise(large_total) == expected
        assert isinstance(bound.max_allowable_exposure_paise(large_total), int)

    def test_exact_threshold_boundary(self) -> None:
        """6. Residual exactly equal to threshold is IMMATERIAL (exceeding is required)."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        total = 10_000_000  # ₹1,00,000 total -> allowable is ₹1,000 (100,000 paise)
        allowable = bound.max_allowable_exposure_paise(total)
        assert allowable == 100_000
        assert not bound.is_material(100_000, total)
        assessment = bound.assess(100_000, total)
        assert not assessment.is_material
        assert "IMMATERIAL" in assessment.explanation

    def test_just_below_threshold(self) -> None:
        """7. Residual 1 paisa below allowable threshold is IMMATERIAL."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        total = 10_000_000
        allowable = bound.max_allowable_exposure_paise(total)
        assert not bound.is_material(allowable - 1, total)

    def test_just_above_threshold(self) -> None:
        """8. Residual 1 paisa above allowable threshold is MATERIAL."""
        bound = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        total = 10_000_000
        allowable = bound.max_allowable_exposure_paise(total)
        assert bound.is_material(allowable + 1, total)
        assessment = bound.assess(allowable + 1, total)
        assert assessment.is_material
        assert "MATERIAL" in assessment.explanation

    def test_changed_policy_produces_changed_version(self) -> None:
        """9. Every parameter modification alters the content-addressed version hash."""
        base = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_000)
        diff_bps = MaterialityBound(threshold_bps=101, floor_paise=10_000, ceiling_paise=10_000_000)
        diff_floor = MaterialityBound(threshold_bps=100, floor_paise=10_001, ceiling_paise=10_000_000)
        diff_ceiling = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000_001)

        versions = {base.version, diff_bps.version, diff_floor.version, diff_ceiling.version}
        assert len(versions) == 4, "All 4 distinct policies must have unique version hashes"
        assert base.version.startswith("materiality_")

    def test_deterministic_repeated_evaluation(self) -> None:
        """10. Repeated evaluations are 100% deterministic and invariant."""
        bound = MaterialityBound(threshold_bps=150, floor_paise=25_000, ceiling_paise=5_000_000)
        total = 8_450_231
        exposure = 126_753

        res_first = bound.assess(exposure, total)
        for _ in range(100):
            res_next = bound.assess(exposure, total)
            assert res_first == res_next
            assert res_first.version == res_next.version

    def test_invalid_parameters_rejected(self) -> None:
        """Validation guards against negative bounds and inverted floor/ceiling."""
        with pytest.raises(ValueError, match="threshold_bps must be non-negative"):
            MaterialityBound(threshold_bps=-1)
        with pytest.raises(ValueError, match="floor_paise must be non-negative"):
            MaterialityBound(floor_paise=-10)
        with pytest.raises(ValueError, match="cannot be less than floor_paise"):
            MaterialityBound(floor_paise=50_000, ceiling_paise=40_000)


# --------------------------------------------------------------------------
# Test Close Readiness Controller
# --------------------------------------------------------------------------

class TestCloseReadinessController:
    def test_ready_to_close_when_all_proven(self) -> None:
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        findings = [
            _proven_finding("s1", ("o1",), 50_000),
            _proven_finding("s2", ("o2",), 75_000),
        ]
        judgements = {
            "s1": _auto_post_judgement(),
            "s2": _auto_post_judgement(),
        }
        exceptions: list[Exception_] = []
        materiality = MaterialityBound()

        verdict = decide_period(p, findings, judgements, exceptions, materiality)

        assert verdict.decision is ReadinessDecision.READY_TO_CLOSE
        assert verdict.material_exposure_paise == 0
        assert verdict.carry_forward == ()
        assert verdict.blockers == ()
        assert "READY_TO_CLOSE" in verdict.to_json()["decision"]
        assert "AUG-2026" in verdict.explain()

    def test_ready_with_carry_forward_for_immaterial_exception(self) -> None:
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        findings = [
            _proven_finding("s1", ("o1",), 10_000_000),
            _ambiguous_finding("s2", 5_000),
        ]
        judgements = {
            "s1": _auto_post_judgement(),
            "s2": _review_judgement("ambiguous candidates"),
        }
        # Immaterial exception: ₹25 unexplained residual
        ex2 = Exception_(
            id="EX-002",
            settlement_id="s2",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW,
            amount_paise=5_000,
            unexplained_paise=2_500,
            established=(),
            missing="reference",
            next_step="confirm order",
            partial=None,
        )
        exceptions = [ex2]
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, findings, judgements, exceptions, materiality)

        assert verdict.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert verdict.material_exposure_paise == 0
        assert verdict.carry_forward == ("EX-002",)
        assert verdict.blockers == ()

    def test_blocked_when_exposure_exceeds_materiality(self) -> None:
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        findings = [
            _proven_finding("s1", ("o1",), 100_000),
            _ambiguous_finding("s2", 100_000),
        ]
        judgements = {
            "s1": _auto_post_judgement(),
            "s2": _review_judgement(),
        }
        # Material exception: ₹800 unexplained on a ₹2,000 total period (allowable is ₹100 floor)
        ex2 = Exception_(
            id="EX-002",
            settlement_id="s2",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.MEDIUM,
            amount_paise=100_000,
            unexplained_paise=80_000,
            established=(),
            missing="adjustment",
            next_step="find fee adjustment",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, findings, judgements, [ex2], materiality)

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.material_exposure_paise == 100_000
        assert "EX-002" in verdict.blockers

    def test_blocked_when_search_space_is_compromised(self) -> None:
        """COMPROMISED search space must block close regardless of monetary amount."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        findings = [_compromised_finding("s1", 10_000)]
        judgements = {"s1": _review_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, findings, judgements, [], materiality)

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert len(verdict.blockers) > 0
        assert any("COMPROMISED" in r for r in verdict.reasons)

    def test_blocked_when_policy_decision_is_block(self) -> None:
        """A settlement blocked by action policy must block the period close."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        findings = [_proven_finding("s1", ("o1",), 10_000)]
        judgements = {"s1": _block_judgement("unmeasured error rate")}
        materiality = MaterialityBound()

        verdict = decide_period(p, findings, judgements, [], materiality)

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert len(verdict.blockers) > 0
        assert any("BLOCKED by policy" in r for r in verdict.reasons)

    def test_blocked_on_high_severity_exception(self) -> None:
        """High severity exceptions (e.g. data quality) block close even if paise is small."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        findings = [_ambiguous_finding("s1", 5_000)]
        judgements = {"s1": _review_judgement()}
        ex = Exception_(
            id="EX-HQ-001",
            settlement_id="s1",
            reason=ReasonCode.DATA_QUALITY,
            severity=Severity.HIGH,
            amount_paise=5_000,
            unexplained_paise=100,  # ₹1 residual, but HIGH severity
            established=(),
            missing="corrupted export",
            next_step="re-export data",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, findings, judgements, [ex], materiality)

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert "EX-HQ-001" in verdict.blockers
        assert any("HIGH severity" in r for r in verdict.reasons)

    def test_only_period_settlements_are_considered(self) -> None:
        """Settlements outside the period must not influence this period's close."""
        p = Period(period_id="P-CLEAN", settlement_ids=("s1",))
        f1 = _proven_finding("s1", ("o1",), 50_000)
        f_outside = _compromised_finding("s_outside", 10_000)  # COMPROMISED, but outside!

        judgements = {
            "s1": _auto_post_judgement(),
            "s_outside": _block_judgement(),
        }
        verdict = decide_period(p, [f1, f_outside], judgements, [], MaterialityBound())

        assert verdict.decision is ReadinessDecision.READY_TO_CLOSE
        assert verdict.blockers == ()


# --------------------------------------------------------------------------
# Integration test with synthetic engine run (Calibration seed)
# --------------------------------------------------------------------------

class TestSyntheticIntegration:
    def test_integration_on_calibration_run(self) -> None:
        """Test close controller over a small calibration run (seed 20260821).

        Never runs the held-out seed per AGENTS.md.
        """
        from attest.generate.generator import build
        from attest.pipeline import run

        # Small 10-settlement slice
        ds = build(n_settlements=10, seed=20260821)
        _, _, findings = run(ds.settlements, ds.orders)
        assert len(findings) == 10

        # Build period over all 10 settlements
        period = Period.from_settlements("CALIB-TEST", ds.settlements)

        # Risk model & policy
        risk = RiskModel()
        judgements: dict[str, Judgement] = {}
        for s, f in zip(ds.settlements, findings):
            judgements[s.settlement_id] = decide(f, s, risk)

        # Exceptions
        exceptions: list[Exception_] = []
        for i, (s, f) in enumerate(zip(ds.settlements, findings), start=1):
            ex = classify(f, s, ds.orders, seq=i)
            if ex is not None:
                exceptions.append(ex)

        materiality = MaterialityBound(threshold_bps=100)
        verdict = decide_period(period, findings, judgements, exceptions, materiality)

        # Verdict must be one of the three valid decisions
        assert verdict.decision in (
            ReadinessDecision.READY_TO_CLOSE,
            ReadinessDecision.READY_WITH_CARRY_FORWARD,
            ReadinessDecision.BLOCKED,
        )
        assert verdict.period_id == "CALIB-TEST"
        assert len(verdict.reasons) > 0


# --------------------------------------------------------------------------
# Step 4: Test Verdict Safety Gate (Adversarial Combinations & Locked Semantics)
# --------------------------------------------------------------------------

class TestVerdictSafetyGate:
    """Rigorous adversarial tests for ClosePilot verdict safety gate.

    Verifies locked semantics:
        READY_TO_CLOSE: Zero unresolved material exposure + zero blockers + all invariants pass.
        READY_WITH_CARRY_FORWARD: Unresolved exposure exists + strictly below materiality +
                                  zero blockers + all invariants pass + every carry-forward explicitly named.
        BLOCKED: Material unresolved exposure OR blocker OR failed invariant OR compromised integrity.

    CRITICAL RULE:
        Materiality may downgrade an economic exception to carry-forward.
        Materiality may NEVER override a hard safety blocker.
        LOW VALUE + HARD BLOCKER = BLOCKED.
    """

    def test_material_exposure_plus_blocker(self) -> None:
        """1. Material exposure + blocker => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)

        f1 = _compromised_finding("s1", 100_000)  # Blocker: COMPROMISED search space
        f2 = _ambiguous_finding("s2", 100_000)

        # Exception has ₹800 unexplained residual (> ₹100 floor threshold)
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.MEDIUM, amount_paise=100_000, unexplained_paise=80_000,
            established=(), missing="", next_step="", partial=None,
        )
        judgements = {"s1": _auto_post_judgement(), "s2": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1, f2], judgements, [ex2], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.carry_forward == ()
        assert verdict.has_blocker_kind(BlockerKind.COMPROMISED_INTEGRITY)
        assert verdict.has_blocker_kind(BlockerKind.UNRESOLVED_MATERIAL_AMOUNT)
        assert verdict.material_exposure_paise == 200_000

    def test_immaterial_exposure_plus_blocker(self) -> None:
        """2. Immaterial exposure + blocker => BLOCKED (CRITICAL: materiality cannot override blocker)."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)

        f1 = _proven_finding("s1", ("o1",), 100_000)
        f2 = _ambiguous_finding("s2", 100_000)

        # Immaterial exception: ₹25 unexplained (allowable is ₹100 floor)
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=100_000, unexplained_paise=2_500,
            established=(), missing="", next_step="", partial=None,
        )
        # BUT s1 is policy-blocked!
        judgements = {"s1": _block_judgement("regulatory sanction"), "s2": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=200_000)

        verdict = decide_period(p, [f1, f2], judgements, [ex2], materiality, settlements=[s1, s2])

        # LOW VALUE + HARD BLOCKER = BLOCKED!
        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.carry_forward == ()
        assert verdict.has_blocker_kind(BlockerKind.POLICY_BLOCKED)
        assert not verdict.has_blocker_kind(BlockerKind.UNRESOLVED_MATERIAL_AMOUNT)

    def test_material_exposure_plus_valid_evidence(self) -> None:
        """3. Material exposure + valid evidence => BLOCKED (materiality alone blocks)."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)

        f1 = _proven_finding("s1", ("o1",), 100_000)
        f2 = _ambiguous_finding("s2", 100_000)

        # Material exception: ₹800 unexplained residual (> ₹100 floor)
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.MEDIUM, amount_paise=100_000, unexplained_paise=80_000,
            established=(), missing="", next_step="", partial=None,
        )
        # Valid judgements, no policy blocks
        judgements = {"s1": _auto_post_judgement(), "s2": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1, f2], judgements, [ex2], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.UNRESOLVED_MATERIAL_AMOUNT)
        assert verdict.material_exposure_paise == 100_000
        assert verdict.carry_forward == ()

    def test_immaterial_exposure_plus_valid_evidence(self) -> None:
        """4. Immaterial exposure + valid evidence => READY_WITH_CARRY_FORWARD."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)

        f1 = _proven_finding("s1", ("o1",), 100_000)
        f2 = _ambiguous_finding("s2", 100_000)

        # Immaterial exception: ₹25 unexplained residual (< ₹100 floor)
        ex2 = Exception_(
            id="EX-002", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=100_000, unexplained_paise=2_500,
            established=(), missing="", next_step="", partial=None,
        )
        judgements = {"s1": _auto_post_judgement(), "s2": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=200_000)

        verdict = decide_period(p, [f1, f2], judgements, [ex2], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert verdict.carry_forward == ("EX-002",)
        assert verdict.blockers == ()
        assert verdict.structured_blockers == ()
        assert verdict.material_exposure_paise == 0

    def test_zero_exposure_plus_blocker(self) -> None:
        """5. Zero exposure + blocker => BLOCKED (even ₹0 exposure cannot close with blocker)."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 100_000)

        # Fully proven with ₹0 unverified exposure, BUT search space is COMPROMISED!
        f1 = _compromised_finding("s1", 100_000)
        judgements = {"s1": _auto_post_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f1], judgements, [], materiality, settlements=[s1])

        # ZERO exposure + HARD BLOCKER = BLOCKED!
        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.COMPROMISED_INTEGRITY)
        assert verdict.carry_forward == ()

    def test_multiple_immaterial_exposures_whose_aggregate_becomes_material(self) -> None:
        """6. Multiple immaterial exposures whose aggregate becomes material => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2", "s3"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)
        s3 = _settlement("s3", 100_000)

        f1 = _ambiguous_finding("s1", 100_000)
        f2 = _ambiguous_finding("s2", 100_000)
        f3 = _ambiguous_finding("s3", 100_000)

        # Allowable threshold is floor ₹100 (10,000 paise).
        # Individually: each is ₹40 (4,000 paise) < ₹100 floor (immaterial on its own).
        ex1 = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=4_000, established=(), missing="", next_step="", partial=None)
        ex2 = Exception_(id="EX-2", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=4_000, established=(), missing="", next_step="", partial=None)
        ex3 = Exception_(id="EX-3", settlement_id="s3", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=4_000, established=(), missing="", next_step="", partial=None)

        # Aggregate exposure: 4,000 * 3 = 12,000 paise (₹120) > 10,000 paise (₹100) threshold!
        judgements = {"s1": _review_judgement(), "s2": _review_judgement(), "s3": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1, f2, f3], judgements, [ex1, ex2, ex3], materiality, settlements=[s1, s2, s3])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.UNRESOLVED_MATERIAL_AMOUNT)
        assert verdict.material_exposure_paise == 300_000
        assert verdict.carry_forward == ()

    def test_contradictory_evidence_conflicting_findings(self) -> None:
        """7. Contradictory evidence (multiple conflicting findings for same settlement) => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 50_000)

        f_proven = _proven_finding("s1", ("o1",), 50_000)
        # Conflicting finding claiming s1 is ambiguous
        f_ambig = _ambiguous_finding("s1", 50_000)

        judgements = {"s1": _auto_post_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f_proven, f_ambig], judgements, [], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.CONTRADICTORY_EVIDENCE)
        assert any("conflicting verdicts" in b.reason for b in verdict.structured_blockers)

    def test_contradictory_evidence_unverified_contradiction(self) -> None:
        """8. Contradicted finding with zero explained value => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 50_000)

        # Finding with Verdict.CONTRADICTED
        sp = SearchSpace(universe=50, members=frozenset(("o1",)))
        f = Finding(
            settlement_id="s1",
            verdict=Verdict.CONTRADICTED,
            proofs=(),
            space=sp,
            layer="L3-dp/r0",
        )
        ex = Exception_(
            id="EX-CONTRA",
            settlement_id="s1",
            reason=ReasonCode.NO_VALID_ASSIGNMENT,
            severity=Severity.HIGH,
            amount_paise=50_000,
            unexplained_paise=50_000,
            established=(),
            missing="everything",
            next_step="investigate",
            partial=None,
        )
        judgements = {"s1": _review_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f], judgements, [ex], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.CONTRADICTORY_EVIDENCE)
        assert "EX-CONTRA" in verdict.blockers

    def test_ambiguous_material_settlement(self) -> None:
        """9. Ambiguous material settlement individually exceeding allowable threshold => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 100_000)
        f1 = _ambiguous_finding("s1", 100_000)

        # Exceeds ₹100 floor threshold
        ex1 = Exception_(
            id="EX-001", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.MEDIUM, amount_paise=100_000, unexplained_paise=50_000,
            established=(), missing="", next_step="", partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1], {"s1": _review_judgement()}, [ex1], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.AMBIGUOUS_MATERIAL_SETTLEMENT)

    def test_duplicate_affecting_ledger_value_double_spending(self) -> None:
        """10. Duplicate order claims across proven settlements (double-spending) => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 50_000)
        s2 = _settlement("s2", 50_000)

        # Both proven settlements claim the SAME order "o1"!
        f1 = _proven_finding("s1", ("o1",), 50_000)
        f2 = _proven_finding("s2", ("o1",), 50_000)

        judgements = {"s1": _auto_post_judgement(), "s2": _auto_post_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f1, f2], judgements, [], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.DUPLICATE_LEDGER_IMPACT)
        assert any("order o1 is claimed by multiple proven settlements" in b.reason for b in verdict.structured_blockers)

    def test_impossible_state_transition_boundary_violation(self) -> None:
        """11. Settlement settled outside period date boundary => BLOCKED."""
        p = Period(
            period_id="AUG-2026",
            settlement_ids=("s1",),
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )
        # s1 settled in September!
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 9, 15))
        f1 = _proven_finding("s1", ("o1",), 50_000)

        judgements = {"s1": _auto_post_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f1], judgements, [], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.IMPOSSIBLE_STATE_TRANSITION)
        assert any("outside period range" in b.reason for b in verdict.structured_blockers)

    def test_failed_invariant_unpostable_proven_finding(self) -> None:
        """12. Finding marked PROVEN but postable is False => BLOCKED (invariant failed)."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 50_000)

        # Create finding that claims PROVEN, but proof order is NOT in search space members!
        sp = SearchSpace(universe=50, members=frozenset(("valid_order",)))
        sp.reductions.append(Reduction("test", 25, True, "candidate prune"))
        proof = Proof("s1", ("foreign_order",), 50_000, 0, 0, 0, 50_000, 0, 0)

        f_invalid = Finding(
            settlement_id="s1",
            verdict=Verdict.PROVEN,
            proofs=(proof,),
            space=sp,
            layer="L3-dp/r0",
        )
        assert not f_invalid.postable  # Invariant violated!

        judgements = {"s1": _auto_post_judgement()}
        materiality = MaterialityBound()

        verdict = decide_period(p, [f_invalid], judgements, [], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.FAILED_INVARIANT)
        assert any("failed posting invariant" in b.reason for b in verdict.structured_blockers)

    def test_compromised_integrity_blocks(self) -> None:
        """13. Compromised search space blocks even with valid judgements."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 10_000)
        f1 = _compromised_finding("s1", 10_000)

        verdict = decide_period(p, [f1], {"s1": _auto_post_judgement()}, [], MaterialityBound(), settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.COMPROMISED_INTEGRITY)

    def test_machine_readable_and_traceable_blockers(self) -> None:
        """14. Blocker records are structured, traceable, and serialized to JSON cleanly."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 50_000)
        f1 = _compromised_finding("s1", 50_000)

        verdict = decide_period(p, [f1], {"s1": _block_judgement("policy refusal")}, [], MaterialityBound(), settlements=[s1])

        assert verdict.has_blocker_kind(BlockerKind.COMPROMISED_INTEGRITY)
        assert verdict.has_blocker_kind(BlockerKind.POLICY_BLOCKED)

        comp_blockers = verdict.get_blockers_by_kind(BlockerKind.COMPROMISED_INTEGRITY)
        assert len(comp_blockers) == 1
        assert comp_blockers[0].ref_id == "s1"
        assert comp_blockers[0].to_dict()["kind"] == "COMPROMISED_INTEGRITY"

        data = verdict.to_json()
        assert "structured_blockers" in data
        assert any(b["kind"] == "POLICY_BLOCKED" for b in data["structured_blockers"])

    def test_unresolved_material_amount_explicit(self) -> None:
        """15. Explicit test for UNRESOLVED_MATERIAL_AMOUNT blocker kind."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 10_000_000)
        f1 = _ambiguous_finding("s1", 10_000_000)
        ex = Exception_(
            id="EX-MAT", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW, amount_paise=10_000_000, unexplained_paise=500_000,
            established=(), missing="", next_step="", partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=100_000)

        verdict = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.UNRESOLVED_MATERIAL_AMOUNT)
        assert verdict.material_exposure_paise == 10_000_000

    def test_failed_invariant_proof_arithmetic_mismatch(self) -> None:
        """16. Proof arithmetic mismatch (gross - fee - tax + adj != net) => BLOCKED."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 100_000)

        sp = SearchSpace(universe=10, members=frozenset(("o1",)))
        sp.reductions.append(Reduction("test", 5, True, "candidate prune"))
        # Bad proof arithmetic: gross 100_000, fee 0, tax 0, adj 0, but net claimed is 90_000!
        bad_proof = Proof("s1", ("o1",), 100_000, 0, 0, 0, 90_000, 0, 0)
        f = Finding(
            settlement_id="s1",
            verdict=Verdict.PROVEN,
            proofs=(bad_proof,),
            space=sp,
            layer="L3-dp/r0",
        )

        verdict = decide_period(p, [f], {"s1": _auto_post_judgement()}, [], MaterialityBound(), settlements=[s1])

        assert verdict.decision is ReadinessDecision.BLOCKED
        assert verdict.has_blocker_kind(BlockerKind.FAILED_INVARIANT)
        assert any("arithmetic mismatch" in b.reason for b in verdict.structured_blockers)


# --------------------------------------------------------------------------
# Step 5: Test Carry-Forward Ledger (Operational Transparency & Rich Metadata)
# --------------------------------------------------------------------------

class TestCarryForwardLedger:
    """Tests for the ClosePilot carry-forward ledger.

    Verifies:
        - Every carry-forward item exposes complete required metadata:
          exception ID, financial exposure, reason, age, severity, close impact, evidence/reference.
        - The output answers controller questions:
          "What remains unresolved?", "How much money is exposed?",
          "Why is it allowed to carry forward?", "What should happen next?"
        - Material exceptions cannot appear as carry-forward.
        - Blockers cannot appear as carry-forward.
        - Ordering is deterministic (largest exposure first, then exception ID).
        - IDs remain traceable to underlying evidence.
    """

    def test_every_carry_forward_has_complete_required_metadata(self) -> None:
        """1. Every carry-forward item exposes all required operational fields."""
        p = Period(
            period_id="AUG-2026",
            settlement_ids=("s1", "s2"),
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )
        s1 = _settlement("s1", 100_000, settled_on=date(2026, 8, 15))
        s2 = _settlement("s2", 100_000, settled_on=date(2026, 8, 25))

        f1 = _proven_finding("s1", ("o1",), 100_000)
        f2 = _ambiguous_finding("s2", 100_000)

        # Immaterial exception: ₹25 unexplained residual
        ex2 = Exception_(
            id="EX-002",
            settlement_id="s2",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW,
            amount_paise=100_000,
            unexplained_paise=2_500,
            established=("o10", "o11"),
            missing="bank reference confirmation",
            next_step="confirm order identifier",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=200_000)
        judgements = {"s1": _auto_post_judgement(), "s2": _review_judgement()}

        verdict = decide_period(p, [f1, f2], judgements, [ex2], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert len(verdict.carry_forward_items) == 1

        item = verdict.carry_forward_items[0]

        # 1. Exception ID
        assert item.exception_id == "EX-002"
        # 2. Financial exposure
        assert item.exposure_paise == 2_500
        # 3. Reason
        assert item.reason == "MULTIPLE_VALID_ASSIGNMENTS"
        # 4. Age (period end Aug 31 - settlement date Aug 25 = 6 days)
        assert item.age_days == 6
        # 5. Severity
        assert item.severity == "LOW"
        # 6. Close impact (explaining why it is permitted to carry forward)
        assert "within allowable policy threshold" in item.close_impact
        assert "authorized for carry-forward" in item.close_impact
        # 7. Next step (actionable work item)
        assert item.next_step == "confirm order identifier"
        # 8. Evidence/reference
        assert "missing: bank reference confirmation" in item.evidence
        assert "established: o10, o11" in item.evidence
        assert "UTR: UTR_s2" in item.evidence

        # Check serialization and dictionary keys
        d = item.to_dict()
        assert d["exception_id"] == "EX-002"
        assert d["exposure_paise"] == 2_500
        assert d["reason"] == "MULTIPLE_VALID_ASSIGNMENTS"
        assert d["age_days"] == 6
        assert d["severity"] == "LOW"
        assert "close_impact" in d
        assert "next_step" in d
        assert "evidence" in d

        # Check single-line summary
        summary = item.summary()
        assert "EX-002" in summary
        assert "₹25.00" in summary
        assert "confirm order identifier" in summary

    def test_material_exceptions_cannot_appear_as_carry_forward(self) -> None:
        """2. Material exceptions must NEVER appear as carry-forward."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 100_000)
        f1 = _ambiguous_finding("s1", 100_000)

        # Material exception: ₹800 unexplained (> ₹100 floor)
        ex_material = Exception_(
            id="EX-MAT",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.MEDIUM,
            amount_paise=100_000,
            unexplained_paise=80_000,
            established=(),
            missing="adjustment record",
            next_step="request fee adjustment report",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1], {"s1": _review_judgement()}, [ex_material], materiality, settlements=[s1])

        # Material exposure blocks the close completely
        assert verdict.decision is ReadinessDecision.BLOCKED
        # Crucial: carry_forward and carry_forward_items are strictly EMPTY
        assert verdict.carry_forward == ()
        assert verdict.carry_forward_items == ()
        assert verdict.get_carry_forward_by_id("EX-MAT") is None
        assert "EX-MAT" in verdict.blockers

    def test_blockers_cannot_appear_as_carry_forward(self) -> None:
        """3. Exceptions that are hard blockers must NEVER appear as carry-forward."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)

        f1 = _proven_finding("s1", ("o1",), 100_000)
        f2 = _ambiguous_finding("s2", 100_000)

        # Immaterial exception: ₹25
        ex_immaterial = Exception_(
            id="EX-IMM", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW, amount_paise=100_000, unexplained_paise=2_500,
            established=(), missing="", next_step="confirm", partial=None,
        )
        # BUT s1 is policy-blocked!
        judgements = {"s1": _block_judgement("compliance hold"), "s2": _review_judgement()}
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        verdict = decide_period(p, [f1, f2], judgements, [ex_immaterial], materiality, settlements=[s1, s2])

        assert verdict.decision is ReadinessDecision.BLOCKED
        # When BLOCKED, carry-forward is forbidden
        assert verdict.carry_forward == ()
        assert verdict.carry_forward_items == ()

    def test_ordering_is_deterministic(self) -> None:
        """4. Carry-forward items are sorted deterministically by exposure descending, then ID."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1", "s2", "s3"))
        s1 = _settlement("s1", 100_000)
        s2 = _settlement("s2", 100_000)
        s3 = _settlement("s3", 100_000)

        f1 = _ambiguous_finding("s1", 100_000)
        f2 = _ambiguous_finding("s2", 100_000)
        f3 = _ambiguous_finding("s3", 100_000)

        # Three immaterial exceptions with distinct amounts:
        # EX-LOW: ₹10 (1,000 paise)
        # EX-HIGH: ₹50 (5,000 paise)
        # EX-MID: ₹25 (2,500 paise)
        ex_low = Exception_(id="EX-LOW", settlement_id="s1", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=1_000, established=(), missing="", next_step="", partial=None)
        ex_high = Exception_(id="EX-HIGH", settlement_id="s2", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=5_000, established=(), missing="", next_step="", partial=None)
        ex_mid = Exception_(id="EX-MID", settlement_id="s3", reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS, severity=Severity.LOW, amount_paise=100_000, unexplained_paise=2_500, established=(), missing="", next_step="", partial=None)

        materiality = MaterialityBound(threshold_bps=100, floor_paise=300_000)  # Total 300,000, allowable 300,000; aggregate unposted value is immaterial
        judgements = {"s1": _review_judgement(), "s2": _review_judgement(), "s3": _review_judgement()}

        # Evaluate with inputs in random/scrambled order
        v1 = decide_period(p, [f1, f2, f3], judgements, [ex_low, ex_high, ex_mid], materiality, settlements=[s1, s2, s3])
        v2 = decide_period(p, [f3, f1, f2], judgements, [ex_high, ex_mid, ex_low], materiality, settlements=[s3, s1, s2])
        v3 = decide_period(p, [f2, f3, f1], judgements, [ex_mid, ex_low, ex_high], materiality, settlements=[s2, s3, s1])

        # All permutations must produce identical sorted order: EX-HIGH (5,000), EX-MID (2,500), EX-LOW (1,000)
        expected_ids = ("EX-HIGH", "EX-MID", "EX-LOW")
        assert v1.carry_forward == expected_ids
        assert v2.carry_forward == expected_ids
        assert v3.carry_forward == expected_ids

        assert [item.exception_id for item in v1.carry_forward_items] == list(expected_ids)
        assert [item.exposure_paise for item in v1.carry_forward_items] == [5_000, 2_500, 1_000]

    def test_ids_remain_traceable_to_underlying_evidence(self) -> None:
        """5. Every carry-forward item traces back to its source settlement and evidence."""
        p = Period(period_id="AUG-2026", settlement_ids=("s1",))
        s1 = _settlement("s1", 50_000)
        f1 = _ambiguous_finding("s1", 50_000)

        ex = Exception_(
            id="EX-TRACE-01",
            settlement_id="s1",
            reason=ReasonCode.REFUND_MISMATCH,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=1_500,
            established=("order_alpha", "order_beta"),
            missing="refund transaction note ARN_98765",
            next_step="inspect gateway refund ledger",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=100_000)

        verdict = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], materiality, settlements=[s1])

        assert verdict.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD

        # Trace by ID
        item = verdict.get_carry_forward_by_id("EX-TRACE-01")
        assert item is not None
        assert item.settlement_id == "s1"
        assert item.exposure_paise == 1_500
        assert "ARN_98765" in item.evidence
        assert "order_alpha" in item.evidence
        assert "UTR_s1" in item.evidence

        # Total carry-forward exposure helper
        assert verdict.get_carry_forward_total_paise() == 1_500

        # Human-readable explanation contains carry-forward ledger
        explained = verdict.explain()
        assert "CARRY-FORWARD LEDGER (1 item(s)" in explained
        assert "EX-TRACE-01" in explained
        assert "inspect gateway refund ledger" in explained
        assert "ARN_98765" in explained


# --------------------------------------------------------------------------
# Close Certificate Tests (Step 6)
# --------------------------------------------------------------------------

class TestCloseCertificate:
    """Test suite for ClosePilot Close Certificate auditability, sensitivity, and determinism."""

    @pytest.fixture
    def sample_context(self):
        p = Period(
            period_id="AUG-2026",
            settlement_ids=("s1",),
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )
        s1 = _settlement("s1", 2_000, settled_on=date(2026, 8, 15))
        f1 = _ambiguous_finding("s1", 2_000)
        ex = Exception_(
            id="EX-CF-01",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=2_000,
            unexplained_paise=2_000,
            established=(),
            missing=None,
            next_step="apply ledger rounding adjustment",
            partial=None,
        )
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        judgements = {"s1": _review_judgement()}
        verdict = decide_period(p, [f1], judgements, [ex], materiality, settlements=[s1])
        return p, s1, f1, ex, materiality, judgements, verdict

    def test_certificate_contains_all_required_fields(self, sample_context) -> None:
        """1. Certificate must contain all 13 required decision-relevant fields directly or via references."""
        p, s1, f1, ex, materiality, judgements, verdict = sample_context

        cert = issue_certificate(
            verdict=verdict,
            period=p,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
            policy_version="policy_v2026_q3",
            engine_version="closepilot_v1",
        )

        # 1. period
        assert cert.period_id == "AUG-2026"
        assert cert.period_start == "2026-08-01"
        assert cert.period_end == "2026-08-31"

        # 2. verdict
        assert cert.verdict == "READY_WITH_CARRY_FORWARD"

        # 3. period value
        assert cert.period_value_paise == 100_000

        # 4. reconciled value
        assert cert.reconciled_value_paise == 98_000

        # 5. unresolved exposure
        assert cert.unresolved_exposure_paise == 2_000

        # 6. material exposure
        assert cert.material_exposure_paise == 0

        # 7. effective materiality threshold
        assert cert.effective_materiality_threshold_paise == 10_000

        # 8. materiality policy / version
        assert cert.materiality_policy_version == materiality.version
        assert cert.materiality_threshold_bps == 100

        # 9. blocker IDs / reasons
        assert cert.blocker_ids == ()
        assert cert.blocker_reasons == ()
        assert cert.structured_blockers == ()

        # 10. carry-forward exceptions
        assert cert.carry_forward_ids == ("EX-CF-01",)
        assert len(cert.carry_forward_items) == 1
        assert cert.carry_forward_items[0]["exception_id"] == "EX-CF-01"
        assert cert.carry_forward_items[0]["exposure_paise"] == 2_000

        # 11. invariant results
        assert len(cert.invariants) >= 1
        assert any("verified_value + exposure" in inv or "reconciled_value + exposure" in inv for inv in cert.invariants)

        # 12. evidence hash
        assert len(cert.evidence_hash) == 64
        assert cert.verify_evidence_hash() is True

        # 13. timestamp
        assert cert.issued_at is not None
        assert cert.certificate_id.startswith("CERT-AUG-2026-")

        # Serialization & rendering
        json_data = cert.to_json()
        assert json_data["period"]["period_id"] == "AUG-2026"
        assert json_data["evidence_hash"] == cert.evidence_hash
        rendered = cert.render()
        assert "CLOSEPILOT CLOSE CERTIFICATE" in rendered
        assert "EX-CF-01" in rendered

    def test_evidence_hash_changes_on_verdict_change(self) -> None:
        """2. Changing verdict changes the evidence hash."""
        args = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_TO_CLOSE",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 100_000,
            "unresolved_exposure_paise": 0,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": (),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**args)

        args_mod = dict(args)
        args_mod["verdict"] = "READY_WITH_CARRY_FORWARD"
        h_mod1 = compute_evidence_hash(**args_mod)

        args_mod["verdict"] = "BLOCKED"
        h_mod2 = compute_evidence_hash(**args_mod)

        assert h_base != h_mod1
        assert h_base != h_mod2
        assert h_mod1 != h_mod2

    def test_evidence_hash_changes_on_exposure_change(self) -> None:
        """3. Changing unresolved or material exposure changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_WITH_CARRY_FORWARD",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 98_000,
            "unresolved_exposure_paise": 2_000,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": ({"exception_id": "EX-1", "exposure_paise": 2_000},),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Modify unresolved exposure
        args_unresolved = dict(base_kwargs)
        args_unresolved["unresolved_exposure_paise"] = 2_001
        h_unres = compute_evidence_hash(**args_unresolved)
        assert h_base != h_unres

        # Modify material exposure
        args_material = dict(base_kwargs)
        args_material["material_exposure_paise"] = 1_000
        h_mat = compute_evidence_hash(**args_material)
        assert h_base != h_mat

    def test_evidence_hash_changes_on_materiality_change(self) -> None:
        """4. Changing materiality threshold, floor, ceiling, or version changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_TO_CLOSE",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 100_000,
            "unresolved_exposure_paise": 0,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": (),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Alter threshold_bps
        args_bps = dict(base_kwargs)
        args_bps["materiality_threshold_bps"] = 200
        assert compute_evidence_hash(**args_bps) != h_base

        # Alter effective threshold paise
        args_thresh = dict(base_kwargs)
        args_thresh["effective_materiality_threshold_paise"] = 12_000
        assert compute_evidence_hash(**args_thresh) != h_base

        # Alter floor
        args_floor = dict(base_kwargs)
        args_floor["materiality_floor_paise"] = 5_000
        assert compute_evidence_hash(**args_floor) != h_base

        # Alter ceiling
        args_ceil = dict(base_kwargs)
        args_ceil["materiality_ceiling_paise"] = 50_000
        assert compute_evidence_hash(**args_ceil) != h_base

    def test_evidence_hash_changes_on_blocker_change(self) -> None:
        """5. Changing blockers changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "BLOCKED",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 0,
            "unresolved_exposure_paise": 100_000,
            "material_exposure_paise": 100_000,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": ({"reference_id": "s1", "reason": "compromised", "kind": "INTEGRITY_COMPROMISED", "exposure_paise": 100_000},),
            "carry_forward_items": (),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Modify blocker reason
        args_mod1 = dict(base_kwargs)
        args_mod1["structured_blockers"] = ({"reference_id": "s1", "reason": "search space altered", "kind": "INTEGRITY_COMPROMISED", "exposure_paise": 100_000},)
        assert compute_evidence_hash(**args_mod1) != h_base

        # Modify blocker reference ID
        args_mod2 = dict(base_kwargs)
        args_mod2["structured_blockers"] = ({"reference_id": "s2", "reason": "compromised", "kind": "INTEGRITY_COMPROMISED", "exposure_paise": 100_000},)
        assert compute_evidence_hash(**args_mod2) != h_base

        # Modify blocker kind
        args_mod3 = dict(base_kwargs)
        args_mod3["structured_blockers"] = ({"reference_id": "s1", "reason": "compromised", "kind": "POLICY_BLOCK", "exposure_paise": 100_000},)
        assert compute_evidence_hash(**args_mod3) != h_base

    def test_evidence_hash_changes_on_carry_forward_change(self) -> None:
        """6. Changing carry-forward items changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_WITH_CARRY_FORWARD",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 98_000,
            "unresolved_exposure_paise": 2_000,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": ({"exception_id": "EX-01", "settlement_id": "s1", "exposure_paise": 2_000, "reason": "rounding"},),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Modify exposure of carry forward item
        args_mod1 = dict(base_kwargs)
        args_mod1["carry_forward_items"] = ({"exception_id": "EX-01", "settlement_id": "s1", "exposure_paise": 2_001, "reason": "rounding"},)
        assert compute_evidence_hash(**args_mod1) != h_base

        # Modify exception ID
        args_mod2 = dict(base_kwargs)
        args_mod2["carry_forward_items"] = ({"exception_id": "EX-99", "settlement_id": "s1", "exposure_paise": 2_000, "reason": "rounding"},)
        assert compute_evidence_hash(**args_mod2) != h_base

        # Add a second carry forward item
        args_mod3 = dict(base_kwargs)
        args_mod3["carry_forward_items"] = (
            {"exception_id": "EX-01", "settlement_id": "s1", "exposure_paise": 2_000, "reason": "rounding"},
            {"exception_id": "EX-02", "settlement_id": "s2", "exposure_paise": 500, "reason": "fee"},
        )
        assert compute_evidence_hash(**args_mod3) != h_base

    def test_evidence_hash_changes_on_invariant_result_change(self) -> None:
        """7. Changing invariant results changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_TO_CLOSE",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 100_000,
            "unresolved_exposure_paise": 0,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": (),
            "invariants": ("inv_A_passed", "inv_B_passed"),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Alter an invariant string
        args_mod1 = dict(base_kwargs)
        args_mod1["invariants"] = ("inv_A_passed", "inv_B_failed")
        assert compute_evidence_hash(**args_mod1) != h_base

        # Add an invariant
        args_mod2 = dict(base_kwargs)
        args_mod2["invariants"] = ("inv_A_passed", "inv_B_passed", "inv_C_passed")
        assert compute_evidence_hash(**args_mod2) != h_base

    def test_evidence_hash_changes_on_policy_version_change(self) -> None:
        """8. Changing policy version or engine version changes the evidence hash."""
        base_kwargs = {
            "period_id": "AUG-2026",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "verdict": "READY_TO_CLOSE",
            "period_value_paise": 100_000,
            "reconciled_value_paise": 100_000,
            "unresolved_exposure_paise": 0,
            "material_exposure_paise": 0,
            "effective_materiality_threshold_paise": 10_000,
            "materiality_policy_version": "mat_v1",
            "materiality_threshold_bps": 100,
            "materiality_floor_paise": 10_000,
            "materiality_ceiling_paise": 0,
            "structured_blockers": (),
            "carry_forward_items": (),
            "invariants": ("inv_1",),
            "policy_version": "policy_v1",
            "engine_version": "closepilot_v1",
        }
        h_base = compute_evidence_hash(**base_kwargs)

        # Alter policy_version
        args_pol = dict(base_kwargs)
        args_pol["policy_version"] = "policy_v2_strict"
        assert compute_evidence_hash(**args_pol) != h_base

        # Alter materiality_policy_version
        args_mat_ver = dict(base_kwargs)
        args_mat_ver["materiality_policy_version"] = "mat_v2"
        assert compute_evidence_hash(**args_mat_ver) != h_base

        # Alter engine_version
        args_eng = dict(base_kwargs)
        args_eng["engine_version"] = "closepilot_v2"
        assert compute_evidence_hash(**args_eng) != h_base

    def test_deterministic_serialization_same_financial_state_same_policy(self, sample_context) -> None:
        """9. Same financial state + same policy = identical evidence hash, even across different issuance timestamps/IDs."""
        p, s1, f1, ex, materiality, judgements, verdict = sample_context

        # Issue first certificate at T1 with ID1
        cert1 = issue_certificate(
            verdict=verdict,
            period=p,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
            policy_version="policy_v1",
            engine_version="closepilot_v1",
            issued_at="2026-09-01T12:00:00+00:00",
            certificate_id="CERT-FIRST-001",
        )

        # Issue second certificate at T2 with ID2
        cert2 = issue_certificate(
            verdict=verdict,
            period=p,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
            policy_version="policy_v1",
            engine_version="closepilot_v1",
            issued_at="2026-09-04T18:45:10+00:00",
            certificate_id="CERT-SECOND-999",
        )

        # Nondeterministic issuance fields differ:
        assert cert1.issued_at != cert2.issued_at
        assert cert1.certificate_id != cert2.certificate_id

        # BUT evidence hashes must be 100% identical!
        assert cert1.evidence_hash == cert2.evidence_hash
        assert cert1.verify_evidence_hash() is True
        assert cert2.verify_evidence_hash() is True

    def test_evidence_hash_tamper_detection(self, sample_context) -> None:
        """10. Modifying any field on a signed certificate causes verification to fail."""
        p, s1, f1, ex, materiality, judgements, verdict = sample_context

        cert = issue_certificate(
            verdict=verdict,
            period=p,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
        )
        assert cert.verify_evidence_hash() is True

        # Tampering with verdict
        tampered_verdict = dataclasses.replace(cert, verdict="READY_TO_CLOSE")
        assert tampered_verdict.verify_evidence_hash() is False

        # Tampering with period value
        tampered_value = dataclasses.replace(cert, period_value_paise=200_000)
        assert tampered_value.verify_evidence_hash() is False

        # Tampering with unresolved exposure
        tampered_exposure = dataclasses.replace(cert, unresolved_exposure_paise=0)
        assert tampered_exposure.verify_evidence_hash() is False

        # Tampering with policy version
        tampered_policy = dataclasses.replace(cert, policy_version="forged_policy")
        assert tampered_policy.verify_evidence_hash() is False

        # Tampering with carry-forward items
        tampered_cf = dataclasses.replace(cert, carry_forward_items=())
        assert tampered_cf.verify_evidence_hash() is False

    def test_closepilot_package_certificate_tamper_detection_and_determinism(self) -> None:
        """11. attest.close.certificate is tamper-evident and deterministic across distinct certificate IDs."""
        from attest.close.certificate import issue_certificate
        from attest.close.materiality import MaterialityBound
        from attest.close.period import Period
        from attest.close.readiness import CarryForwardItem, PeriodVerdict, ReadinessDecision
        from attest.exceptions import ReasonCode, Severity

        cp_period = Period("AUG-2026", settlement_ids=("s1",), start=date(2026, 8, 1), end=date(2026, 8, 31))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        verdict = PeriodVerdict(
            period_id="AUG-2026",
            decision=ReadinessDecision.READY_WITH_CARRY_FORWARD,
            reasons=("Ready with carry forward",),
            material_exposure_paise=0,
            blockers=(),
            carry_forward=("s1",),
            carry_forward_items=(
                CarryForwardItem(
                    exception_id="EX-001",
                    settlement_id="s1",
                    exposure_paise=2_000,
                    reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS.value,
                    age_days=1,
                    severity=Severity.LOW.value,
                    close_impact="immaterial",
                    next_step="investigate",
                    evidence="evidence",
                ),
            ),
            net_unresolved_exposure_paise=2_000,
            gross_contested_claim_exposure_paise=2_000,
        )

        cert1 = issue_certificate(
            verdict=verdict,
            period=cp_period,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
            unresolved_exposure_paise=2_000,
            policy_version=materiality.version,
            certificate_id="CERT-CP-1",
            issued_at="2026-09-01T00:00:00+00:00",
        )
        cert2 = issue_certificate(
            verdict=verdict,
            period=cp_period,
            materiality=materiality,
            reconciled_value_paise=98_000,
            period_value_paise=100_000,
            unresolved_exposure_paise=2_000,
            policy_version=materiality.version,
            certificate_id="CERT-CP-2",
            issued_at="2026-09-02T00:00:00+00:00",
        )

        # Deterministic evidence hash regardless of certificate_id or issuance time
        assert cert1.evidence_hash == cert2.evidence_hash
        assert cert1.verify_evidence_hash() is True
        assert cert2.verify_evidence_hash() is True

        # Tampering detected
        tampered = dataclasses.replace(cert1, reconciled_value_paise=100_000)
        assert tampered.verify_evidence_hash() is False


# --------------------------------------------------------------------------
# Step 7: Adversarial Quality Gate (22 Safety & Determinism Cases)
# --------------------------------------------------------------------------

class TestAdversarialQualityGate:
    """Rigorous adversarial quality gate proving safety, determinism, and permutation invariance."""

    def test_case_01_zero_exceptions(self) -> None:
        """1. Zero exceptions: all settlements verified -> READY_TO_CLOSE."""
        p = Period("P-ZERO-EX", ("s1", "s2"), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        s2 = _settlement("s2", 50_000, settled_on=date(2026, 8, 15))
        f1 = _proven_finding("s1", ("o1",), 50_000)
        f2 = _proven_finding("s2", ("o2",), 50_000)
        judgements = {"s1": _auto_post_judgement(), "s2": _auto_post_judgement()}
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        v = decide_period(p, [f1, f2], judgements, [], mat, settlements=[s1, s2])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=100_000, period_value_paise=100_000)

        assert v.decision is ReadinessDecision.READY_TO_CLOSE
        assert v.material_exposure_paise == 0
        assert v.blockers == ()
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_02_one_immaterial_exception(self) -> None:
        """2. One immaterial exception: unresolved below threshold -> READY_WITH_CARRY_FORWARD."""
        p = Period("P-ONE-IMM", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 2_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 2_000)
        ex = Exception_(
            id="EX-01",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=2_000,
            unexplained_paise=2_000,
            established=(),
            missing="receipt",
            next_step="request receipt",
            partial=None,
        )
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=2_000)

        assert v.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert v.material_exposure_paise == 0
        assert v.get_carry_forward_total_paise() == 2_000
        assert v.blockers == ()
        assert v.carry_forward == ("EX-01",)
        assert cert.verify_evidence_hash() is True

    def test_case_03_one_material_exception(self) -> None:
        """3. One material exception: unresolved exceeds threshold -> BLOCKED."""
        p = Period("P-ONE-MAT", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 15_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 15_000)
        ex = Exception_(
            id="EX-MAT",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=15_000,
            unexplained_paise=15_000,  # exceeds 10,000 threshold
            established=(),
            missing=None,
            next_step="investigate discrepancy",
            partial=None,
        )
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=15_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert v.material_exposure_paise == 15_000
        assert len(v.blockers) > 0
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_04_many_immaterial_exceptions(self) -> None:
        """4. Many immaterial exceptions whose sum is still immaterial -> READY_WITH_CARRY_FORWARD."""
        p = Period("P-MANY-IMM", ("s1", "s2", "s3", "s4", "s5"), date(2026, 8, 1), date(2026, 8, 31))
        settlements = [_settlement(f"s{i}", 1_000, settled_on=date(2026, 8, 10)) for i in range(1, 6)]
        findings = [_ambiguous_finding(f"s{i}", 1_000) for i in range(1, 6)]
        judgements = {f"s{i}": _review_judgement() for i in range(1, 6)}
        exceptions = [
            Exception_(
                id=f"EX-0{i}",
                settlement_id=f"s{i}",
                reason=ReasonCode.UNKNOWN_ADJUSTMENT,
                severity=Severity.LOW,
                amount_paise=1_000,
                unexplained_paise=1_000,
                established=(),
                missing=None,
                next_step="review",
                partial=None,
            )
            for i in range(1, 6)
        ]
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)  # total 5,000 < 10,000
        v = decide_period(p, findings, judgements, exceptions, mat, settlements=settlements)
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=5_000)

        assert v.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert v.material_exposure_paise == 0
        assert v.get_carry_forward_total_paise() == 5_000
        assert len(v.carry_forward) == 5
        assert v.blockers == ()
        assert cert.verify_evidence_hash() is True

    def test_case_05_aggregate_immaterial_exceptions_becoming_material(self) -> None:
        """5. Aggregate of individually immaterial exceptions exceeding materiality -> BLOCKED."""
        p = Period("P-AGG-MAT", ("s1", "s2", "s3", "s4", "s5", "s6"), date(2026, 8, 1), date(2026, 8, 31))
        settlements = [_settlement(f"s{i}", 2_000, settled_on=date(2026, 8, 10)) for i in range(1, 7)]
        findings = [_ambiguous_finding(f"s{i}", 2_000) for i in range(1, 7)]
        judgements = {f"s{i}": _review_judgement() for i in range(1, 7)}
        exceptions = [
            Exception_(
                id=f"EX-0{i}",
                settlement_id=f"s{i}",
                reason=ReasonCode.UNKNOWN_ADJUSTMENT,
                severity=Severity.LOW,
                amount_paise=2_000,
                unexplained_paise=2_000,  # 6 * 2,000 = 12,000 > 10,000 threshold
                established=(),
                missing=None,
                next_step="review",
                partial=None,
            )
            for i in range(1, 7)
        ]
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, findings, judgements, exceptions, mat, settlements=settlements)
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=12_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert v.material_exposure_paise == 12_000
        assert any(b.kind is BlockerKind.UNRESOLVED_MATERIAL_AMOUNT for b in v.structured_blockers)
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_06_material_blocker(self) -> None:
        """6. Material blocker: high severity exception on large amount -> BLOCKED."""
        p = Period("P-MAT-BLK", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 100_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 100_000)
        ex = Exception_(
            id="EX-HIGH",
            settlement_id="s1",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.HIGH,
            amount_paise=100_000,
            unexplained_paise=50_000,
            established=(),
            missing=None,
            next_step="freeze settlement",
            partial=None,
        )
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=50_000, period_value_paise=100_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert v.material_exposure_paise >= 50_000
        assert "EX-HIGH" in v.blockers
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_07_immaterial_blocker(self) -> None:
        """7. Immaterial blocker: LOW VALUE + HARD BLOCKER = BLOCKED (cannot carry forward)."""
        p = Period("P-IMM-BLK", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 500, settled_on=date(2026, 8, 10))
        f1 = _proven_finding("s1", ("o1",), 500)
        ex = Exception_(
            id="EX-IMM-BLK",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=500,
            unexplained_paise=500,
            established=(),
            missing=None,
            next_step="review",
            partial=None,
        )
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        # Policy issues Decision.BLOCK
        v = decide_period(p, [f1], {"s1": _block_judgement("policy block")}, [ex], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=500)

        assert v.decision is ReadinessDecision.BLOCKED
        assert any(b.kind is BlockerKind.POLICY_BLOCKED for b in v.structured_blockers)
        assert "s1" in v.blockers
        assert v.carry_forward == ()  # blocker must NEVER appear as carry-forward!
        assert cert.verify_evidence_hash() is True

    def test_case_08_contradictory_evidence(self) -> None:
        """8. Contradictory evidence: conflicting findings for same settlement -> BLOCKED."""
        p = Period("P-CONTRA", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        f1 = _proven_finding("s1", ("o1",), 50_000)
        f2 = _proven_finding("s1", ("o2",), 50_000)  # Contradicts f1!
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1, f2], {"s1": _auto_post_judgement()}, [], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=50_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert any(b.kind is BlockerKind.CONTRADICTORY_EVIDENCE for b in v.structured_blockers)
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_09_ambiguous_settlement(self) -> None:
        """9. Ambiguous settlement: within materiality -> CF; exceeding materiality -> BLOCKED."""
        p = Period("P-AMBIG", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 50_000)

        # 9a. Immaterial ambiguous
        ex_imm = Exception_(
            id="EX-AMB-IMM",
            settlement_id="s1",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=1_000,
            established=(),
            missing=None,
            next_step="review orders",
            partial=None,
        )
        mat = MaterialityBound(threshold_bps=100, floor_paise=100_000)
        v_imm = decide_period(p, [f1], {"s1": _review_judgement()}, [ex_imm], mat, settlements=[s1])
        assert v_imm.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert v_imm.carry_forward == ("EX-AMB-IMM",)

        # 9b. Material ambiguous
        ex_mat = Exception_(
            id="EX-AMB-MAT",
            settlement_id="s1",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=25_000,
            established=(),
            missing=None,
            next_step="review orders",
            partial=None,
        )
        mat_strict = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v_mat = decide_period(p, [f1], {"s1": _review_judgement()}, [ex_mat], mat_strict, settlements=[s1])
        assert v_mat.decision is ReadinessDecision.BLOCKED
        assert v_mat.carry_forward == ()
        assert len(v_mat.blockers) > 0

    def test_case_10_duplicate_financial_record(self) -> None:
        """10. Duplicate financial record (double spending an order across settlements) -> BLOCKED."""
        p = Period("P-DUP-REC", ("s1", "s2"), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        s2 = _settlement("s2", 50_000, settled_on=date(2026, 8, 15))
        # Both claim the same order 'o_shared'
        f1 = _proven_finding("s1", ("o_shared",), 50_000)
        f2 = _proven_finding("s2", ("o_shared",), 50_000)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1, f2], {"s1": _auto_post_judgement(), "s2": _auto_post_judgement()}, [], mat, settlements=[s1, s2])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=100_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert any(b.kind is BlockerKind.DUPLICATE_LEDGER_IMPACT for b in v.structured_blockers)
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_11_duplicate_finding(self) -> None:
        """11. Duplicate findings for same settlement: exposure counted once, not double counted."""
        f1 = _ambiguous_finding("s1", 50_000)
        f1_dup = _ambiguous_finding("s1", 50_000)
        ex = Exception_(
            id="EX-1",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=2_000,
            established=(),
            missing=None,
            next_step="review",
            partial=None,
        )
        pe = assess_exposure([f1, f1_dup], [ex, ex])
        assert pe.total_exposure_paise == 50_000  # not 100,000!
        assert len(pe.items) == 1

    def test_case_12_zero_value_period(self) -> None:
        """12. Zero-value period: clean period with zero settlements -> READY_TO_CLOSE."""
        p = Period("P-ZERO", (), date(2026, 8, 1), date(2026, 8, 31))
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [], {}, [], mat)
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=0)

        assert v.decision is ReadinessDecision.READY_TO_CLOSE
        assert v.material_exposure_paise == 0
        assert v.blockers == ()
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_13_negative_adjustment(self) -> None:
        """13. Negative adjustment: exposure is magnitude (positive integer paise)."""
        f = _ambiguous_finding("s1", 50_000)
        ex = Exception_(
            id="EX-NEG",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=-1_500,  # Negative adjustment
            established=(),
            missing=None,
            next_step="reverse adjustment",
            partial=None,
        )
        pe = assess_exposure([f], [ex])
        assert pe.total_exposure_paise == 50_000
        assert pe.net_unresolved_exposure_paise == 50_000
        assert pe.gross_contested_claim_exposure_paise == 100_000
        assert pe.items[0].exposure_paise == 100_000

    def test_case_14_very_large_amounts(self) -> None:
        """14. Very large amounts (Rs 1,000 Crore): exact integer arithmetic without precision loss."""
        large_val = 1_000_000_000_000  # 10^12 paise = Rs 100 Crore
        p = Period("P-LARGE", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", large_val, settled_on=date(2026, 8, 10))
        f1 = _proven_finding("s1", ("o1",), large_val)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _auto_post_judgement()}, [], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=large_val, period_value_paise=large_val)

        assert v.decision is ReadinessDecision.READY_TO_CLOSE
        assert cert.period_value_paise == large_val
        assert cert.verify_evidence_hash() is True

    def test_case_15_currency_mismatch(self) -> None:
        """15. Currency mismatch: incompatible currencies raise CurrencyMismatchError."""
        f1 = _ambiguous_finding("s1", 50_000)
        ex1 = Exception_(
            id="EX-INR",
            settlement_id="s1",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=50_000,
            unexplained_paise=1_000,
            established=(),
            missing=None,
            next_step="review",
            partial=None,
        )
        @dataclasses.dataclass(frozen=True)
        class USDSettlement:
            settlement_id: str
            settled_on: date
            net_paise: int
            utr: str | None = None
            currency: str = "USD"

        s_usd = USDSettlement("s_usd", date(2026, 8, 10), 50_000)
        with pytest.raises(CurrencyMismatchError):
            assess_exposure([f1], [ex1], settlements=[s_usd])

    def test_case_16_reordered_input(self) -> None:
        """16. Reordered input: permutation invariance across findings, judgements, exceptions, and settlements."""
        p = Period("P-PERM", ("s1", "s2", "s3"), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 30_000, settled_on=date(2026, 8, 10))
        s2 = _settlement("s2", 30_000, settled_on=date(2026, 8, 12))
        s3 = _settlement("s3", 30_000, settled_on=date(2026, 8, 15))
        f1 = _ambiguous_finding("s1", 30_000)
        f2 = _ambiguous_finding("s2", 30_000)
        f3 = _ambiguous_finding("s3", 30_000)
        ex1 = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=30_000, unexplained_paise=1_000, established=(), missing=None, next_step="review", partial=None)
        ex2 = Exception_(id="EX-2", settlement_id="s2", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=30_000, unexplained_paise=2_000, established=(), missing=None, next_step="review", partial=None)
        ex3 = Exception_(id="EX-3", settlement_id="s3", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=30_000, unexplained_paise=3_000, established=(), missing=None, next_step="review", partial=None)
        judgements = {"s1": _review_judgement(), "s2": _review_judgement(), "s3": _review_judgement()}
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        # Permutation 1
        v1 = decide_period(p, [f1, f2, f3], judgements, [ex1, ex2, ex3], mat, settlements=[s1, s2, s3])
        c1 = issue_certificate(v1, p, mat, reconciled_value_paise=84_000, period_value_paise=90_000)

        # Permutation 2: Reversed
        v2 = decide_period(p, [f3, f2, f1], judgements, [ex3, ex2, ex1], mat, settlements=[s3, s2, s1])
        c2 = issue_certificate(v2, p, mat, reconciled_value_paise=84_000, period_value_paise=90_000)

        # Permutation 3: Scrambled
        v3 = decide_period(p, [f2, f3, f1], judgements, [ex2, ex1, ex3], mat, settlements=[s2, s1, s3])
        c3 = issue_certificate(v3, p, mat, reconciled_value_paise=84_000, period_value_paise=90_000)

        assert v1.decision == v2.decision == v3.decision
        assert v1.carry_forward == v2.carry_forward == v3.carry_forward
        assert v1.blockers == v2.blockers == v3.blockers
        assert c1.evidence_hash == c2.evidence_hash == c3.evidence_hash

    def test_case_17_repeated_evaluation(self) -> None:
        """17. Repeated evaluation: strictly idempotent over 10 iterations."""
        p = Period("P-IDEMP", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 50_000)
        ex = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=50_000, unexplained_paise=1_000, established=(), missing=None, next_step="review", partial=None)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        base_v = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat, settlements=[s1])
        base_cert = issue_certificate(base_v, p, mat, reconciled_value_paise=49_000, period_value_paise=50_000)

        for _ in range(10):
            v = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat, settlements=[s1])
            cert = issue_certificate(v, p, mat, reconciled_value_paise=49_000, period_value_paise=50_000)
            assert v.decision == base_v.decision
            assert cert.evidence_hash == base_cert.evidence_hash

    def test_case_18_changed_materiality_policy(self) -> None:
        """18. Changed materiality policy: changing threshold changes readiness decision & hash."""
        p = Period("P-CHG-POL", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 5_000, settled_on=date(2026, 8, 10))
        f1 = _ambiguous_finding("s1", 5_000)
        ex = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=5_000, unexplained_paise=5_000, established=(), missing=None, next_step="review", partial=None)

        # Policy A: threshold 10,000 paise -> CF
        mat_a = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v_a = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat_a, settlements=[s1])
        cert_a = issue_certificate(v_a, p, mat_a, reconciled_value_paise=0, period_value_paise=5_000)

        # Policy B: threshold 2,000 paise -> BLOCKED
        mat_b = MaterialityBound(threshold_bps=20, floor_paise=2_000)
        v_b = decide_period(p, [f1], {"s1": _review_judgement()}, [ex], mat_b, settlements=[s1])
        cert_b = issue_certificate(v_b, p, mat_b, reconciled_value_paise=0, period_value_paise=5_000)

        assert v_a.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert v_b.decision is ReadinessDecision.BLOCKED
        assert cert_a.evidence_hash != cert_b.evidence_hash

    def test_case_19_changed_exception(self) -> None:
        """19. Changed exception: changing exception amount changes verdict from CF to BLOCKED and alters hash."""
        p = Period("P-CHG-EX", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s_low = _settlement("s1", 2_000, settled_on=date(2026, 8, 10))
        f_low = _ambiguous_finding("s1", 2_000)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        ex_low = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=2_000, unexplained_paise=2_000, established=(), missing=None, next_step="review", partial=None)
        v_low = decide_period(p, [f_low], {"s1": _review_judgement()}, [ex_low], mat, settlements=[s_low])
        cert_low = issue_certificate(v_low, p, mat, reconciled_value_paise=0, period_value_paise=2_000)

        s_high = _settlement("s1", 12_000, settled_on=date(2026, 8, 10))
        f_high = _ambiguous_finding("s1", 12_000)
        ex_high = Exception_(id="EX-1", settlement_id="s1", reason=ReasonCode.UNKNOWN_ADJUSTMENT, severity=Severity.LOW, amount_paise=12_000, unexplained_paise=12_000, established=(), missing=None, next_step="review", partial=None)
        v_high = decide_period(p, [f_high], {"s1": _review_judgement()}, [ex_high], mat, settlements=[s_high])
        cert_high = issue_certificate(v_high, p, mat, reconciled_value_paise=0, period_value_paise=12_000)

        assert v_low.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert v_high.decision is ReadinessDecision.BLOCKED
        assert cert_low.evidence_hash != cert_high.evidence_hash

    def test_case_20_failed_invariant(self) -> None:
        """20. Failed invariant: PROVEN finding marked postable=False -> BLOCKED."""
        p = Period("P-INV-FAIL", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        # Finding with empty layer -> postable is False
        sp = SearchSpace(universe=100, members=frozenset(("o1",)))
        proof = Proof(
            settlement_id="s1",
            order_ids=("o1",),
            gross_paise=50_000,
            fee_paise=0,
            tax_paise=0,
            adjustment_paise=0,
            net_paise=50_000,
            residual_paise=0,
            tolerance_paise=0,
        )
        f1 = Finding(
            settlement_id="s1",
            verdict=Verdict.PROVEN,
            proofs=(proof,),
            space=sp,
            layer="",  # Empty solver layer causes postable=False!
        )
        assert f1.postable is False

        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _auto_post_judgement()}, [], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=50_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert any(b.kind is BlockerKind.FAILED_INVARIANT for b in v.structured_blockers)
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_21_compromised_integrity(self) -> None:
        """21. Compromised integrity: search space integrity COMPROMISED -> BLOCKED."""
        p = Period("P-COMPR", ("s1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("s1", 50_000, settled_on=date(2026, 8, 10))
        f1 = _compromised_finding("s1", 50_000)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"s1": _auto_post_judgement()}, [], mat, settlements=[s1])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=0, period_value_paise=50_000)

        assert v.decision is ReadinessDecision.BLOCKED
        assert any(b.kind is BlockerKind.COMPROMISED_INTEGRITY for b in v.structured_blockers)
        assert v.carry_forward == ()
        assert cert.verify_evidence_hash() is True

    def test_case_22_impossible_state_transition(self) -> None:
        """22. Impossible state transition: settlements with settled_on outside period boundary."""
        p = Period("P-OUTSIDE", ("s_in",), date(2026, 8, 1), date(2026, 8, 31))
        s_in = _settlement("s_in", 50_000, settled_on=date(2026, 8, 10))
        s_out = _settlement("s_out", 50_000, settled_on=date(2026, 9, 15))  # Outside period!
        f_in = _proven_finding("s_in", ("o1",), 50_000)
        f_out = _compromised_finding("s_out", 50_000)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)

        # Outside finding is excluded from this period's close evaluation
        v = decide_period(p, [f_in, f_out], {"s_in": _auto_post_judgement(), "s_out": _block_judgement()}, [], mat, settlements=[s_in, s_out])
        cert = issue_certificate(v, p, mat, reconciled_value_paise=50_000, period_value_paise=50_000)

        assert v.decision is ReadinessDecision.READY_TO_CLOSE
        assert v.blockers == ()
        assert cert.verify_evidence_hash() is True

    def test_case_23_certificate_explicit_properties_and_conservation(self) -> None:
        """23. Certificate explicit property accessors and strict conservation law."""
        p = Period("P-CERT-AUDIT", ("setl_1",), date(2026, 8, 1), date(2026, 8, 31))
        s1 = _settlement("setl_1", 100_000, settled_on=date(2026, 8, 10))
        f1 = _proven_finding("setl_1", ("o1",), 100_000)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000)
        v = decide_period(p, [f1], {"setl_1": _auto_post_judgement()}, [], mat, settlements=[s1])

        cert = issue_certificate(
            v, p, mat,
            reconciled_value_paise=100_000,
            period_value_paise=100_000,
            unresolved_exposure_paise=0,
            gross_contested_claim_exposure_paise=15_000,
        )

        # Explicit semantic properties
        assert cert.total_period_value_paise == 100_000
        assert cert.verified_value_paise == 100_000
        assert cert.net_unresolved_exposure_paise == 0
        assert cert.gross_contested_claim_exposure_paise == 15_000
        assert cert.active_blocker_rule_instances == 0
        assert cert.unique_blocked_exceptions == 0
        assert cert.unique_blocked_settlements == 0

        # Conservation law
        assert cert.verified_value_paise + cert.net_unresolved_exposure_paise == cert.total_period_value_paise

        # Conservation wording in invariants
        assert any("verified_value + net_unresolved_exposure == total_value" in inv for inv in cert.invariants)

        # JSON representation contains explicit fields
        json_data = cert.to_json()
        assert json_data["values"]["total_period_value_paise"] == 100_000
        assert json_data["values"]["verified_value_paise"] == 100_000
        assert json_data["values"]["net_unresolved_exposure_paise"] == 0
        assert json_data["values"]["gross_contested_claim_exposure_paise"] == 15_000
        assert json_data["counts"]["active_blocker_rule_instances"] == 0
        assert json_data["counts"]["unique_blocked_exceptions"] == 0
        assert json_data["counts"]["unique_blocked_settlements"] == 0

        # Rendered text contains explicit headers
        rendered = cert.render()
        assert "Total Period Value" in rendered
        assert "Verified Value" in rendered
        assert "Net Unresolved Exp." in rendered
        assert "Gross Contested Claim: ₹150.00 (diagnostic)" in rendered
        assert "Active Blocker Rule Instances : 0" in rendered
