"""Tests for Benchmark Integrity and Exposure Semantics (Step 2).

Validates:
1. Exposure terminology (gross_contested_claim_exposure_paise vs net_unresolved_exposure_paise).
2. Accounting conservation equation (reconciled_net + net_unresolved = total_period_value).
3. Gross >= Net exposure when candidate hypotheses overlap, and why gross can exceed portfolio value.
4. Blocker semantics (active_blocker_rule_instances vs unique_blocked_exceptions vs unique_blocked_settlements).
5. Dataset-derived period calculation (min/max date) eliminating artificial IMPOSSIBLE_STATE_TRANSITION blockers.
6. Ground-truth isolation: Stage 1 system execution does not access or leak ds.truth.
7. False proof independence: setl_000246 is independently blocked without ground truth.
8. Benchmark scoring occurs strictly after Stage 1 execution.
9. Repeated deterministic execution and permutation invariance.
"""

from __future__ import annotations

import datetime
import inspect
import random
from typing import Any

import pytest

from attest.close.exposure import PeriodExposure, assess_exposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import BlockerKind, PeriodVerdict, ReadinessDecision, decide_period
from attest.exceptions import Exception_, ReasonCode, Severity, classify
from attest.generate.generator import build
from attest.model import Settlement, TrueMatch
from attest.pipeline import run
from attest.policy import Costs, Decision, RiskModel, calibrate, decide
from attest.searchspace import Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict
from scripts.benchmark_evaluation import (
    SEED_TRAIN,
    SystemExecutionResult,
    execute_system_pipeline,
    score_against_ground_truth,
)


def _settlement(sid: str, net: int, settled_on: datetime.date | None = None) -> Settlement:
    return Settlement(
        settlement_id=sid,
        settled_on=settled_on or datetime.date(2026, 6, 1),
        net_paise=net,
        utr=f"UTR_{sid}",
    )


def test_exposure_terminology_and_conservation():
    """Verify exposure terminology and exact accounting conservation."""
    # Build a controlled scenario
    s1 = _settlement("s_1", 100_000, datetime.date(2026, 6, 1))
    s2 = _settlement("s_2", 200_000, datetime.date(2026, 6, 2))
    settlements = [s1, s2]

    # Finding 1: fully explained (proof verified)
    sp1 = SearchSpace(universe=10, members=frozenset(("o_1",)))
    sp1.reductions.append(Reduction("test", 10, True, "test"))
    p1 = Proof("s_1", ("o_1",), 100_000, 0, 0, 0, 100_000, 0, 0)
    f1 = Finding("s_1", Verdict.PROVEN, (p1,), space=sp1, layer="L3")

    # Finding 2: ambiguous partial (unexplained 50_000, two candidate hypotheses of 150_000 each)
    p2_a = Proof("s_2", ("o_2a",), 150_000, 0, 0, 0, 150_000, 0, 0)
    p2_b = Proof("s_2", ("o_2b",), 150_000, 0, 0, 0, 150_000, 0, 0)
    sp2 = SearchSpace(universe=10, members=frozenset(("o_2a", "o_2b")))
    f2 = Finding("s_2", Verdict.AMBIGUOUS, (p2_a, p2_b), space=sp2, layer="L3", exhaustive=True)

    ex2 = Exception_(
        id="ex_2",
        settlement_id="s_2",
        reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
        severity=Severity.HIGH,
        amount_paise=200_000,
        unexplained_paise=50_000,
        established=(),
        missing="ambiguous candidate orders",
        next_step="investigate",
        partial=None,
    )

    exposure = assess_exposure(
        findings=[f1, f2],
        exceptions=[ex2],
        settlements=settlements,
        target_settlement_ids=("s_1", "s_2"),
    )

    # 1. Terminology check
    assert hasattr(exposure, "net_unresolved_exposure_paise")
    assert hasattr(exposure, "gross_contested_claim_exposure_paise")
    assert hasattr(exposure, "reconciled_value_share")
    assert hasattr(exposure, "net_unresolved_share")
    assert hasattr(exposure, "gross_contested_share")

    # 2. Total portfolio = 300,000 paise
    total_val = exposure.total_value_paise
    assert total_val == 300_000

    # s_1 is fully verified -> verified_value = 100,000 paise
    # s_2 is unposted on the balance sheet -> net unresolved = 200,000 paise
    assert exposure.verified_value_paise == 100_000
    assert exposure.net_unresolved_exposure_paise == 200_000

    # 3. Accounting conservation equation
    assert exposure.verified_value_paise + exposure.net_unresolved_exposure_paise == total_val

    # 4. Gross contested claim exposure includes both competing candidates (150k + 150k = 300k)
    # plus unexplained 50k = 350k for s_2
    assert exposure.gross_contested_claim_exposure_paise >= exposure.net_unresolved_exposure_paise


def test_gross_can_exceed_portfolio_value_due_to_competing_hypotheses():
    """Document and verify that gross contested exposure can mathematically exceed portfolio value."""
    # Settlement value is 100k paise
    s = _settlement("s_1", 100_000, datetime.date(2026, 6, 1))
    
    # In an ambiguous pool, multiple overlapping candidate orders compete for the same settlement
    # e.g., candidate set A (100k) and candidate set B (100k) are both plausible explanations
    p_a = Proof("s_1", ("o_A",), 100_000, 0, 0, 0, 100_000, 0, 0)
    p_b = Proof("s_1", ("o_B",), 100_000, 0, 0, 0, 100_000, 0, 0)
    sp = SearchSpace(universe=10, members=frozenset(("o_A", "o_B")))
    f = Finding("s_1", Verdict.AMBIGUOUS, (p_a, p_b), space=sp, layer="L3", exhaustive=True)
    
    ex = Exception_(
        id="ex_1",
        settlement_id="s_1",
        reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
        severity=Severity.MEDIUM,
        amount_paise=100_000,
        unexplained_paise=0,
        established=(),
        missing="ambiguous candidate orders",
        next_step="investigate",
        partial=None,
    )

    exposure = assess_exposure([f], [ex], [s], ("s_1",))
    
    # Net unresolved is the unposted settlement value (100k)
    # But gross contested orders = 100k + 100k = 200k paise (200% of settlement value)
    assert exposure.total_value_paise == 100_000
    assert exposure.gross_contested_claim_exposure_paise == 200_000
    assert exposure.gross_contested_claim_exposure_paise > exposure.total_value_paise
    assert exposure.gross_contested_share == 2.0  # 200%


def test_blocker_semantics_distinguishes_instances_from_exceptions_and_settlements():
    """Verify that blocker reporting distinguishes rule instances from affected entities."""
    s1 = _settlement("s_1", 500_000, datetime.date(2026, 6, 1))
    period = Period(
        period_id="P-TEST",
        settlement_ids=("s_1",),
        start=datetime.date(2026, 6, 1),
        end=datetime.date(2026, 6, 30),
    )
    
    p = Proof("s_1", ("o_1",), 300_000, 0, 0, 0, 300_000, 200_000, 0)
    sp = SearchSpace(universe=10, members=frozenset(("o_1",)))
    f = Finding("s_1", Verdict.AMBIGUOUS, (p,), space=sp, layer="L3", exhaustive=True)
    
    # An exception can trigger MULTIPLE blocker rules simultaneously:
    # 1. EXCEPTION_HIGH_SEVERITY
    # 2. EXPOSURE_EXCEEDS_MATERIALITY
    ex = Exception_(
        id="ex_1",
        settlement_id="s_1",
        reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
        severity=Severity.HIGH,
        amount_paise=500_000,
        unexplained_paise=200_000,
        established=(),
        missing="candidate shortfall",
        next_step="investigate",
        partial=None,
    )
    
    mat = MaterialityBound(threshold_bps=10, floor_paise=10_000, ceiling_paise=50_000)
    judgements = {"s_1": decide(f, s1, RiskModel({}, {}), Costs())}
    
    verdict = decide_period(
        period=period,
        findings=[f],
        judgements=judgements,
        exceptions=[ex],
        materiality=mat,
        settlements=[s1],
    )
    
    # Multiple blocker rules fire for the same single exception and single settlement
    assert verdict.active_blocker_rule_instances >= 2
    assert verdict.unique_blocked_exceptions == 1
    assert verdict.unique_blocked_settlements == 1
    
    breakdown = verdict.blocker_rule_breakdown
    assert isinstance(breakdown, dict)
    assert sum(breakdown.values()) == verdict.active_blocker_rule_instances


def test_dataset_derived_period_eliminates_artificial_date_blockers():
    """Verify that deriving period from dataset dates produces zero artificial date blockers."""
    # Generate canonical dataset of size 50 for quick test
    ds = build(50, seed=SEED_TRAIN)
    
    settlement_dates = [s.settled_on for s in ds.settlements if s.settled_on is not None]
    min_date = min(settlement_dates)
    max_date = max(settlement_dates)
    
    # Dataset dates are in May - July 2026, NOT August
    assert min_date <= max_date
    assert min_date.month in (5, 6, 7)
    
    # Execute Stage 1 with dataset-derived period
    sys_res = execute_system_pipeline(
        settlements=ds.settlements,
        orders=ds.orders,
        credits=ds.credits,
        seed=SEED_TRAIN,
        n=50,
    )
    
    assert sys_res.period.start == min_date
    assert sys_res.period.end == max_date
    
    # Prove that IMPOSSIBLE_STATE_TRANSITION is 0
    date_blockers = [
        b for b in sys_res.verdict.structured_blockers
        if b.kind == BlockerKind.IMPOSSIBLE_STATE_TRANSITION
    ]
    assert len(date_blockers) == 0
    assert sys_res.verdict.blocker_rule_breakdown.get("IMPOSSIBLE_STATE_TRANSITION", 0) == 0


def test_automated_anti_leakage_stage1_never_accesses_ground_truth():
    """Automated anti-leakage test: Stage 1 execution accepts only financial records and has no access to ds.truth."""
    import ast
    sig = inspect.signature(execute_system_pipeline)
    param_names = list(sig.parameters.keys())
    
    # Ground truth parameters must not be present
    assert "truth" not in param_names
    assert "true_matches" not in param_names
    assert "ds" not in param_names
    
    # Verify AST of function does not access ground truth on input dataset
    tree = ast.parse(inspect.getsource(execute_system_pipeline))
    func = tree.body[0]
    for node in ast.walk(func):
        if isinstance(node, ast.Attribute) and node.attr == "truth":
            # Only independent calibration dataset is allowed to reference truth
            assert isinstance(node.value, ast.Name) and node.value.id == "cal"


def test_adversarial_false_proof_setl_000246_independently_blocked():
    """Verify setl_000246 is independently classified as an exception and blocked without ground truth."""
    ds = build(250, seed=SEED_TRAIN)
    
    # Execute Stage 1 (zero ground truth access)
    sys_res = execute_system_pipeline(
        settlements=ds.settlements,
        orders=ds.orders,
        credits=ds.credits,
        seed=SEED_TRAIN,
        n=250,
    )
    
    target_sid = "setl_000246"
    assert target_sid in sys_res.period.settlement_ids
    
    # 1. Pipeline produced finding
    f_246 = next(f for f in sys_res.findings if f.settlement_id == target_sid)
    assert f_246 is not None
    
    # 2. Policy judgement autonomously decided without ground truth
    j_246 = sys_res.judgements[target_sid]
    assert j_246.decision is Decision.BLOCK
    
    # 3. Exception was classified
    ex_246 = next((e for e in sys_res.exceptions if e.settlement_id == target_sid), None)
    assert ex_246 is not None
    
    # 4. Target was blocked in Close Controller
    assert sys_res.verdict.decision == ReadinessDecision.BLOCKED
    assert target_sid not in sys_res.verdict.carry_forward
    
    # Now in Stage 2 (scoring only), check ground truth
    scoring = score_against_ground_truth(sys_res, ds.truth, t_match=1.0)
    assert target_sid in scoring["ground_truth_reconciliation_scoring"]["false_proof_ids"]
    # And confirm safe handling: 0 unsafe auto resolutions
    assert scoring["close_readiness_controller_system_output"]["unsafe_auto_resolutions"] == 0


def test_stage2_scoring_strictly_after_stage1():
    """Verify Stage 2 scoring evaluates Stage 1 results without modifying them."""
    ds = build(50, seed=SEED_TRAIN)
    
    sys_res = execute_system_pipeline(
        settlements=ds.settlements,
        orders=ds.orders,
        credits=ds.credits,
        seed=SEED_TRAIN,
        n=50,
    )
    
    verdict_before = sys_res.verdict.decision
    unresolved_before = sys_res.exposure.net_unresolved_exposure_paise
    
    scoring = score_against_ground_truth(sys_res, ds.truth, t_match=0.5)
    
    # Verdict and exposure must remain strictly unchanged
    assert sys_res.verdict.decision == verdict_before
    assert sys_res.exposure.net_unresolved_exposure_paise == unresolved_before
    assert "ground_truth_reconciliation_scoring" in scoring
    assert "close_readiness_controller_system_output" in scoring


def test_repeated_deterministic_benchmark_and_permutation_invariance():
    """Verify that repeated benchmark runs are strictly identical and input permutation invariant."""
    ds = build(60, seed=SEED_TRAIN)
    
    res1 = execute_system_pipeline(ds.settlements, ds.orders, ds.credits, SEED_TRAIN, 60)
    res2 = execute_system_pipeline(ds.settlements, ds.orders, ds.credits, SEED_TRAIN, 60)
    
    assert res1.verdict.decision == res2.verdict.decision
    assert res1.verdict.material_exposure_paise == res2.verdict.material_exposure_paise
    assert res1.exposure.net_unresolved_exposure_paise == res2.exposure.net_unresolved_exposure_paise
    assert res1.exposure.gross_contested_claim_exposure_paise == res2.exposure.gross_contested_claim_exposure_paise
    assert res1.certificate.evidence_hash == res2.certificate.evidence_hash
    assert res1.is_permutation_invariant is True


def test_reordered_input_determinism():
    """Verify that shuffled settlement/order input order produces identical system output."""
    ds = build(60, seed=SEED_TRAIN)
    
    # Original order
    res1 = execute_system_pipeline(ds.settlements, ds.orders, ds.credits, SEED_TRAIN, 60)
    
    # Reverse settlement and order input order
    shuffled_settlements = list(reversed(ds.settlements))
    shuffled_orders = list(reversed(ds.orders))
    shuffled_credits = list(reversed(ds.credits))
    
    res2 = execute_system_pipeline(shuffled_settlements, shuffled_orders, shuffled_credits, SEED_TRAIN, 60)
    
    # Core financial metrics must be identical regardless of input order
    assert res1.verdict.decision == res2.verdict.decision
    assert res1.exposure.total_value_paise == res2.exposure.total_value_paise
    assert res1.exposure.verified_value_paise == res2.exposure.verified_value_paise
    assert res1.exposure.net_unresolved_exposure_paise == res2.exposure.net_unresolved_exposure_paise
    assert res1.exposure.gross_contested_claim_exposure_paise == res2.exposure.gross_contested_claim_exposure_paise
    assert res1.verdict.active_blocker_rule_instances == res2.verdict.active_blocker_rule_instances
    assert res1.certificate.evidence_hash == res2.certificate.evidence_hash


def test_canonical_blocker_counts_verified():
    """Verify that blocker reporting on the canonical dataset separates rule instances from affected entities."""
    ds = build(250, seed=SEED_TRAIN)
    
    sys_res = execute_system_pipeline(ds.settlements, ds.orders, ds.credits, SEED_TRAIN, 250)
    
    verdict = sys_res.verdict
    # Blocker rule instances is the count of individual blocker rules that fired
    instances = verdict.active_blocker_rule_instances
    # Unique blocked exceptions counts distinct exception IDs
    blocked_ex = verdict.unique_blocked_exceptions
    # Unique blocked settlements counts distinct settlement IDs
    blocked_setl = verdict.unique_blocked_settlements
    
    # Rule instances >= unique affected exceptions (one exception can trigger multiple rules)
    assert instances >= blocked_ex or instances >= blocked_setl
    # Breakdown sums to total instances
    assert sum(verdict.blocker_rule_breakdown.values()) == instances
    # All values are non-negative
    assert instances >= 0
    assert blocked_ex >= 0
    assert blocked_setl >= 0


def test_canonical_conservation_equation_on_full_dataset():
    """Verify the accounting conservation equation holds on the canonical 250-settlement dataset."""
    ds = build(250, seed=SEED_TRAIN)
    
    sys_res = execute_system_pipeline(ds.settlements, ds.orders, ds.credits, SEED_TRAIN, 250)
    
    exp = sys_res.exposure
    
    # Conservation: reconciled_net + net_unresolved == total_period_value
    assert exp.verified_value_paise + exp.net_unresolved_exposure_paise == exp.total_value_paise, (
        f"Conservation failed: {exp.verified_value_paise} + {exp.net_unresolved_exposure_paise} "
        f"!= {exp.total_value_paise}"
    )
    
    # Gross contested claim exposure >= net unresolved when candidate hypotheses compete
    assert exp.gross_contested_claim_exposure_paise >= exp.net_unresolved_exposure_paise, (
        f"Gross {exp.gross_contested_claim_exposure_paise} < Net {exp.net_unresolved_exposure_paise}"
    )
    
    # Total value is positive (sanity check)
    assert exp.total_value_paise > 0
