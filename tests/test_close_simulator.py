"""Tests for ClosePilot Counterfactual Close Simulator (Phase 2B).

Verifies the Close Simulation Engine:
    CloseSimulator & simulate_close()

Guarantees Verified:
1. NON-MUTATION: Source ledgers, findings, exceptions, judgements, and settlements
   remain 100% untouched throughout all simulations.
2. AUTHORITATIVE CONTROLLER: Decisions are evaluated strictly through the hardened
   `attest.close.readiness.decide_period` kernel.
3. STATE DISTINCTION: Every outcome explicitly differentiates ACTUAL from HYPOTHETICAL.
4. 5 CANONICAL SCENARIOS:
   - Close now (actual baseline)
   - Resolve selected exception(s)
   - Carry forward immaterial exceptions
   - Remove/resolve hypothetical blocker(s)
   - Wait for predicted resolutions
5. SAFETY INVARIANTS:
   - Material exceptions can never carry forward.
   - Waiving a blocker when material exposure remains stays BLOCKED.
   - All deltas (exposure, blockers, carry-forward) are mathematically exact.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement
from attest.policy import Decision, Judgement, RiskModel
from attest.searchspace import Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict

from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import BlockerKind, ReadinessDecision, decide_period
from closepilot.simulator import (
    CloseSimulator,
    ScenarioType,
    SimulationOutcome,
    SimulationReport,
    SimulationScenario,
    SimulationState,
    simulate_close,
)

_TODAY = date(2026, 9, 1)


# --------------------------------------------------------------------------
# Fixture Helpers
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


def _policy_ok(sid: str) -> Judgement:
    return Judgement(
        decision=Decision.AUTO_POST,
        expected_loss_paise=500,
        p_error=0.005,
        reasons=("auto approved",),
    )


def _policy_block(sid: str, reason: str = "risk alert") -> Judgement:
    return Judgement(
        decision=Decision.BLOCK,
        expected_loss_paise=None,
        p_error=None,
        reasons=(reason,),
    )


def _exception(
    eid: str,
    sid: str,
    unexplained: int,
    total: int,
    reason: ReasonCode = ReasonCode.UNKNOWN_ADJUSTMENT,
    severity: Severity = Severity.LOW,
) -> Exception_:
    return Exception_(
        id=eid,
        settlement_id=sid,
        reason=reason,
        severity=severity,
        amount_paise=total,
        unexplained_paise=unexplained,
        established=(),
        missing=f"Missing ref for {sid}",
        next_step="Manual audit",
        partial=None,
    )


# --------------------------------------------------------------------------
# Test Cases
# --------------------------------------------------------------------------

class TestCloseSimulator:
    """Core test suite for Counterfactual Close Simulation Engine."""

    def test_source_state_remains_strictly_unmodified(self) -> None:
        """Prove that simulating scenarios never mutates source financial state."""
        s1 = _settlement("S1", 100_000)
        s2 = _settlement("S2", 200_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        f2 = _proven_finding("S2", ("O2",), 200_000)
        j1 = _policy_ok("S1")
        j2 = _policy_block("S2")
        e2 = _exception("EX2", "S2", 50_000, 200_000, ReasonCode.TIMING_MISMATCH, Severity.MEDIUM)

        findings_src = [f1, f2]
        judgements_src = {"S1": j1, "S2": j2}
        exceptions_src = [e2]
        settlements_src = [s1, s2]
        period = Period(period_id="P_MUTATION_CHECK", settlement_ids=("S1", "S2"), start=_TODAY, end=_TODAY)
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=100_000)

        # Snapshots for deep comparison
        findings_before = copy.deepcopy(findings_src)
        judgements_before = copy.deepcopy(judgements_src)
        exceptions_before = copy.deepcopy(exceptions_src)
        settlements_before = copy.deepcopy(settlements_src)

        simulator = CloseSimulator(
            period=period,
            findings=findings_src,
            judgements=judgements_src,
            exceptions=exceptions_src,
            materiality=materiality,
            settlements=settlements_src,
        )

        # Run multiple diverse counterfactual simulations
        res_outcome = simulator.simulate_resolve_exceptions(["EX2"])
        blk_outcome = simulator.simulate_clear_blocker(ref_ids=["S2"])
        wait_outcome = simulator.simulate_wait_predicted(horizon_days=3)
        cf_outcome = simulator.simulate_carry_forward_immaterial()
        report = simulator.run_standard_suite()

        # 1. Cryptographic checksum check built into simulator
        assert simulator.verify_source_unmodified(
            current_findings=findings_src,
            current_judgements=judgements_src,
            current_exceptions=exceptions_src,
            current_settlements=settlements_src,
        ), "Source data checksum mismatch after simulations!"

        # 2. Strict deep equality check
        assert findings_src == findings_before
        assert judgements_src == judgements_before
        assert exceptions_src == exceptions_before
        assert settlements_src == settlements_before

        # 3. Collection lengths and IDs unchanged
        assert len(findings_src) == 2
        assert len(judgements_src) == 2
        assert len(exceptions_src) == 1
        assert len(settlements_src) == 2

    def test_actual_vs_hypothetical_state_distinction(self) -> None:
        """Verify explicit taxonomy distinguishing ACTUAL from HYPOTHETICAL state."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        e1 = _exception("EX1", "S1", 10_000, 100_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)
        period = Period(period_id="P_STATE_CHECK", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=500, ceiling_paise=50_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        baseline = simulator.simulate_close_now()
        hypo = simulator.simulate_resolve_exceptions(["EX1"])

        assert baseline.state_type is SimulationState.ACTUAL
        assert hypo.state_type is SimulationState.HYPOTHETICAL
        assert baseline.scenario_type is ScenarioType.CLOSE_NOW
        assert hypo.scenario_type is ScenarioType.RESOLVE_EXCEPTIONS

        # Check in serialized dict
        assert baseline.to_dict()["state_type"] == "ACTUAL"
        assert hypo.to_dict()["state_type"] == "HYPOTHETICAL"

    def test_scenario_01_close_now_matches_authoritative_controller(self) -> None:
        """Scenario 1 (Close Now) reproduces authoritative decide_period verdict."""
        s1 = _settlement("S1", 500_000)
        f1 = _proven_finding("S1", ("O1",), 500_000)
        period = Period(period_id="P_CLOSE_NOW", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=50_000)
        judgements = {"S1": _policy_ok("S1")}

        authoritative = decide_period(
            period=period,
            findings=[f1],
            judgements=judgements,
            exceptions=[],
            materiality=materiality,
            settlements=[s1],
        )

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements=judgements,
            exceptions=[],
            materiality=materiality,
            settlements=[s1],
        )

        outcome = simulator.simulate_close_now()
        assert outcome.projected_verdict == authoritative.decision
        assert outcome.unresolved_exposure_paise == 0
        assert outcome.material_exposure_paise == authoritative.material_exposure_paise
        assert outcome.blockers == authoritative.blockers
        assert outcome.delta_unresolved_exposure_paise == 0
        assert outcome.delta_blocker_count == 0
        assert outcome.is_closeable is True

    def test_scenario_02_resolve_selected_exceptions(self) -> None:
        """Scenario 2: Resolving a material exception transitions BLOCKED to READY_TO_CLOSE."""
        s1 = _settlement("S1", 100_000)
        s2 = _settlement("S2", 200_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        f2 = _proven_finding("S2", ("O2",), 200_000)
        # S2 has a material exception of ₹50,000 (exceeding ₹2,000 threshold)
        e2 = _exception("EX_MAT", "S2", 50_000, 200_000, ReasonCode.UNKNOWN_ADJUSTMENT, Severity.HIGH)

        period = Period(period_id="P_RES_EXC", settlement_ids=("S1", "S2"))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=2_000, ceiling_paise=2_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1, f2],
            judgements={"S1": _policy_ok("S1"), "S2": _policy_ok("S2")},
            exceptions=[e2],
            materiality=materiality,
            settlements=[s1, s2],
        )

        # Actual baseline is BLOCKED
        assert simulator.actual_baseline.projected_verdict is ReadinessDecision.BLOCKED
        assert simulator.actual_baseline.unresolved_exposure_paise == 50_000
        assert simulator.actual_baseline.is_closeable is False

        # Simulate resolving EX_MAT
        outcome = simulator.simulate_resolve_exceptions(["EX_MAT"])
        assert outcome.projected_verdict is ReadinessDecision.READY_TO_CLOSE
        assert outcome.unresolved_exposure_paise == 0
        assert outcome.delta_unresolved_exposure_paise == -50_000
        assert outcome.delta_blocker_count < 0
        assert outcome.verdict_transition == "BLOCKED → READY_TO_CLOSE"
        assert outcome.resolved_exception_ids == ("EX_MAT",)
        assert outcome.is_closeable is True

    def test_scenario_03_carry_forward_immaterial_exceptions(self) -> None:
        """Scenario 3: Qualifying immaterial exceptions authorized for carry-forward."""
        s1 = _settlement("S1", 1_000_000)
        f1 = _proven_finding("S1", ("O1",), 1_000_000)
        # ₹5,000 unexplained is below 1% (₹10,000) threshold
        e1 = _exception("EX_IMMAT", "S1", 5_000, 1_000_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)

        period = Period(period_id="P_CF_IMMAT", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=50_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        outcome = simulator.simulate_carry_forward_immaterial()
        assert outcome.projected_verdict is ReadinessDecision.READY_WITH_CARRY_FORWARD
        assert outcome.carry_forward_count == 1
        assert outcome.carry_forward_value_paise == 5_000
        assert outcome.unresolved_exposure_paise == 5_000
        assert outcome.is_closeable is True

    def test_scenario_03_material_exception_cannot_carry_forward(self) -> None:
        """Safety invariant: A material exception CANNOT carry forward."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        # ₹25,000 exceeds ₹1,000 threshold
        e1 = _exception("EX_MAT", "S1", 25_000, 100_000, ReasonCode.MISSING_TRANSACTION, Severity.HIGH)

        period = Period(period_id="P_CF_MAT", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        outcome = simulator.simulate_carry_forward_immaterial()
        # MUST REMAIN BLOCKED!
        assert outcome.projected_verdict is ReadinessDecision.BLOCKED
        assert outcome.carry_forward_count == 0
        assert outcome.is_closeable is False

    def test_scenario_04_clear_hypothetical_blocker_enables_close(self) -> None:
        """Scenario 4: Clearing an isolated policy blocker enables close."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        # Policy blocked
        j1 = _policy_block("S1", "AML manual review required")

        period = Period(period_id="P_CLR_BLK", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=10_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": j1},
            exceptions=[],
            materiality=materiality,
            settlements=[s1],
        )

        assert simulator.actual_baseline.projected_verdict is ReadinessDecision.BLOCKED
        assert simulator.actual_baseline.blocker_count >= 1

        # Clear policy blocker
        outcome = simulator.simulate_clear_blocker(ref_ids=["S1"])
        assert outcome.projected_verdict is ReadinessDecision.READY_TO_CLOSE
        assert outcome.blocker_count == 0
        assert outcome.delta_blocker_count == -1
        assert outcome.verdict_transition == "BLOCKED → READY_TO_CLOSE"
        assert outcome.is_closeable is True

    def test_scenario_04_clearing_blocker_does_not_bypass_material_exposure(self) -> None:
        """Safety invariant: Waiving a blocker when material exposure remains stays BLOCKED."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        j1 = _policy_block("S1", "KYC check")
        # In addition to policy block, there is an unresolved material exception
        e1 = _exception("EX_MAT", "S1", 30_000, 100_000, ReasonCode.UNKNOWN_ADJUSTMENT, Severity.HIGH)

        period = Period(period_id="P_BLK_AND_MAT", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": j1},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        # Clear only the policy blocker
        outcome = simulator.simulate_clear_blocker(ref_ids=["S1"])
        # Verdict MUST STILL BE BLOCKED due to material exposure!
        assert outcome.projected_verdict is ReadinessDecision.BLOCKED
        assert outcome.is_closeable is False
        assert any(b.kind is BlockerKind.UNRESOLVED_MATERIAL_AMOUNT for b in outcome.structured_blockers)

    def test_scenario_05_wait_predicted_resolutions(self) -> None:
        """Scenario 5: High-probability timing mismatch predicts resolution at T+3d."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        # Timing mismatch: high natural clearance prior (p ~ 0.88, horizon = 3d)
        e1 = _exception("EX_TIMING", "S1", 20_000, 100_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)

        period = Period(period_id="P_WAIT_PRED", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        # Baseline: BLOCKED (20,000 > 1,000)
        assert simulator.actual_baseline.projected_verdict is ReadinessDecision.BLOCKED

        # Wait T+3d: Timing mismatch clears naturally
        outcome = simulator.simulate_wait_predicted(horizon_days=3, min_probability=0.70)
        assert outcome.projected_verdict is ReadinessDecision.READY_TO_CLOSE
        assert outcome.unresolved_exposure_paise == 0
        assert "EX_TIMING" in outcome.resolved_exception_ids
        assert outcome.is_closeable is True

    def test_scenario_05_low_probability_chargeback_does_not_clear_early(self) -> None:
        """Scenario 5: Low-probability chargeback dispute does not clear at T+3d."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        # Chargeback: low natural clearance prior (p ~ 0.18, horizon = 30d)
        e1 = _exception("EX_CB", "S1", 20_000, 100_000, ReasonCode.CHARGEBACK, Severity.HIGH)

        period = Period(period_id="P_WAIT_CB", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        # Wait T+3d: Chargeback does NOT clear
        outcome = simulator.simulate_wait_predicted(horizon_days=3, min_probability=0.70)
        assert outcome.projected_verdict is ReadinessDecision.BLOCKED
        assert "EX_CB" not in outcome.resolved_exception_ids
        assert outcome.unresolved_exposure_paise == 20_000
        assert outcome.is_closeable is False

    def test_standard_suite_and_simulation_report(self) -> None:
        """Test batch execution of standard suite, recommendation, and report rendering."""
        s1 = _settlement("S1", 500_000)
        s2 = _settlement("S2", 500_000)
        f1 = _proven_finding("S1", ("O1",), 500_000)
        f2 = _proven_finding("S2", ("O2",), 500_000)
        e1 = _exception("EX1", "S1", 15_000, 500_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)
        e2 = _exception("EX2", "S2", 20_000, 500_000, ReasonCode.UNKNOWN_ADJUSTMENT, Severity.MEDIUM)

        period = Period(period_id="P_SUITE", settlement_ids=("S1", "S2"))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=5_000, ceiling_paise=5_000)

        report = simulate_close(
            period=period,
            findings=[f1, f2],
            judgements={"S1": _policy_ok("S1"), "S2": _policy_ok("S2")},
            exceptions=[e1, e2],
            materiality=materiality,
            settlements=[s1, s2],
        )

        assert isinstance(report, SimulationReport)
        assert len(report.scenarios) >= 3
        assert report.actual_baseline.state_type is SimulationState.ACTUAL

        # Test ASCII render
        rendered = report.render()
        assert "CLOSEPILOT — COUNTERFACTUAL CLOSE SIMULATION REPORT" in rendered
        assert "[ACTUAL STATE]" in rendered
        assert "HYPOTHETICAL SCENARIOS" in rendered
        assert "RECOMMENDED OPERATIONAL ACTION" in rendered

        # Test JSON serialization
        d = report.to_dict()
        assert d["period_id"] == "P_SUITE"
        assert d["actual_baseline"]["state_type"] == "ACTUAL"
        assert all(s["state_type"] == "HYPOTHETICAL" for s in d["scenarios"])

    def test_deterministic_repeated_simulation(self) -> None:
        """Repeated simulations produce identical results with zero drift."""
        s1 = _settlement("S1", 100_000)
        f1 = _proven_finding("S1", ("O1",), 100_000)
        e1 = _exception("EX1", "S1", 10_000, 100_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)
        period = Period(period_id="P_IDEMPOTENT", settlement_ids=("S1",))
        materiality = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        simulator = CloseSimulator(
            period=period,
            findings=[f1],
            judgements={"S1": _policy_ok("S1")},
            exceptions=[e1],
            materiality=materiality,
            settlements=[s1],
        )

        outcomes = [simulator.simulate_wait_predicted(3) for _ in range(5)]
        first = outcomes[0]
        for subsequent in outcomes[1:]:
            assert subsequent.projected_verdict == first.projected_verdict
            assert subsequent.unresolved_exposure_paise == first.unresolved_exposure_paise
            assert subsequent.material_exposure_paise == first.material_exposure_paise
            assert subsequent.blockers == first.blockers
            assert subsequent.resolved_exception_ids == first.resolved_exception_ids
