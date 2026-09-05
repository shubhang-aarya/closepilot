"""CLOSEPILOT — Empirical Benchmark & Evaluation Suite.

Evaluates the complete system against the canonical synthetic dataset:
- STAGE 1 (System Execution): Operates strictly on financial records without ds.truth.
- STAGE 2 (Ground-Truth Scoring): Evaluates system decisions against ground truth.
- Measures all 13 financial and operational dimensions requested by Buildathon evaluation.
- Outputs comprehensive metrics, failure cases, safety proofs, and comparison.
"""

from __future__ import annotations

import datetime
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from attest.close.certificate import CloseCertificate, issue_certificate
from attest.close.exposure import PeriodExposure, assess_exposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import BlockerKind, PeriodVerdict, ReadinessDecision, decide_period
from attest.eval.harness import Timer, evaluate
from attest.exceptions import Exception_, classify
from attest.generate.generator import build
from attest.model import Settlement, TrueMatch
from attest.money import rupees
from attest.pipeline import run
from attest.policy import Costs, Decision, Judgement, RiskModel, calibrate, decide
from closepilot.lineage import build_lineage
from closepilot.predictor import predict_batch
from closepilot.review_queue import build_review_queue
from closepilot.simulator import CloseSimulator, ScenarioType

SEED_TRAIN = 20260821
_CACHED_RISK_MODEL: RiskModel | None = None


@dataclass
class SystemExecutionResult:
    """STAGE 1 OUTPUT — Produced autonomously without any ground truth."""

    period: Period
    findings: list[Any]
    exceptions: list[Exception_]
    judgements: dict[str, Judgement]
    verdict: PeriodVerdict
    exposure: PeriodExposure
    certificate: CloseCertificate
    predictions: list[Any]
    lineage: Any
    review_queue: Any
    sim_baseline: Any
    sim_cf: Any
    sim_wait: Any
    is_permutation_invariant: bool
    is_idempotent: bool
    timings: dict[str, float]
    # Inputs & predictions for Stage 2 scoring
    settlements: list[Settlement]
    orders: list[Any]
    credits: list[Any]
    preds: list[Any]
    pools: dict[str, Any]
    materiality: MaterialityBound


def execute_system_pipeline(
    settlements: list[Settlement],
    orders: list[Any],
    credits: list[Any],
    seed: int,
    n: int,
) -> SystemExecutionResult:
    """STAGE 1 — SYSTEM EXECUTION.

    CRITICAL ARCHITECTURAL SAFETY GUARANTEE:
    This function accepts ONLY synthetic financial records (settlements, orders, credits).
    It has ZERO ACCESS to ground truth (ds.truth).
    All matching, exception classification, policy judgements, exposure calculations,
    readiness verdicts, resolution predictions, and close certificates are produced
    autonomously by the engine.
    """
    timings: dict[str, float] = {}

    # 0. Canonical input ordering ensures complete permutation invariance
    settlements = sorted(settlements, key=lambda s: s.settlement_id)
    orders = sorted(orders, key=lambda o: o.order_id)

    # 1. Pipeline Matching
    t_match_start = time.perf_counter()
    preds, pools, findings = run(settlements, orders)
    timings["reconciliation_solver_sec"] = time.perf_counter() - t_match_start

    # 2. Exception Classification
    settle_by_id = {s.settlement_id: s for s in settlements}
    exceptions = [
        e for i, f in enumerate(findings, start=1)
        if (e := classify(f, settle_by_id[f.settlement_id], pools.get(f.settlement_id, []), i)) is not None
    ]

    # 3. Dynamic Period Range derived deterministically from dataset's actual transactions
    settlement_dates = [s.settled_on for s in settlements if s.settled_on is not None]
    period_start = min(settlement_dates) if settlement_dates else datetime.date(2026, 1, 1)
    period_end = max(settlement_dates) if settlement_dates else datetime.date(2026, 12, 31)

    period = Period(
        period_id=f"P-{seed}-{n}",
        start=period_start,
        end=period_end,
        settlement_ids=tuple(s.settlement_id for s in settlements),
    )

    materiality = MaterialityBound(
        threshold_bps=50,  # 50 bps (0.50%)
        floor_paise=50_000,
        ceiling_paise=1_000_000,
    )

    # 4. Action Policy Calibration (Trained on separate independent seeds — ZERO access to current dataset truth)
    global _CACHED_RISK_MODEL
    if _CACHED_RISK_MODEL is None:
        cal_seeds = [111111, 222222]
        fits = {}
        for idx, s_seed in enumerate(cal_seeds):
            cal = build(60, seed=s_seed)
            _, _, cf = run(cal.settlements, cal.orders)
            fits[idx] = (cf, {t.settlement_id: set(t.order_ids) for t in cal.truth})
        _CACHED_RISK_MODEL = calibrate(fits)
    risk_model = _CACHED_RISK_MODEL

    costs = Costs()
    judgements = {
        f.settlement_id: decide(f, settle_by_id[f.settlement_id], risk_model, costs)
        for f in findings
    }

    # 5. Close Controller Evaluation
    t_ctrl_start = time.perf_counter()
    verdict = decide_period(
        period=period,
        findings=findings,
        judgements=judgements,
        exceptions=exceptions,
        materiality=materiality,
        settlements=settlements,
    )
    timings["close_controller_eval_sec"] = time.perf_counter() - t_ctrl_start

    # 6. Exposure Engine
    exposure = assess_exposure(
        findings=findings,
        exceptions=exceptions,
        settlements=settlements,
        target_settlement_ids=period.settlement_ids,
        judgements=judgements,
    )

    # 7. Certificate Issuance
    t_cert_start = time.perf_counter()
    cert = issue_certificate(
        verdict=verdict,
        period=period,
        materiality=materiality,
        reconciled_value_paise=exposure.verified_value_paise,
        period_value_paise=exposure.total_value_paise,
        unresolved_exposure_paise=exposure.net_unresolved_exposure_paise,
        policy_version=materiality.version,
        issued_at="2026-08-31T23:59:59Z",
    )
    timings["certificate_issue_sec"] = time.perf_counter() - t_cert_start

    # Idempotence check
    cert_2 = issue_certificate(
        verdict=verdict,
        period=period,
        materiality=materiality,
        reconciled_value_paise=exposure.verified_value_paise,
        period_value_paise=exposure.total_value_paise,
        unresolved_exposure_paise=exposure.net_unresolved_exposure_paise,
        policy_version=materiality.version,
        issued_at="2026-08-31T23:59:59Z",
    )
    is_idempotent = (cert.evidence_hash == cert_2.evidence_hash)

    # 8. Resolution Predictor
    t_pred_start = time.perf_counter()
    predictions = predict_batch(exceptions, settlements=settlements)
    timings["prediction_batch_sec"] = time.perf_counter() - t_pred_start

    # 9. Counterfactual Simulator
    t_sim_start = time.perf_counter()
    simulator = CloseSimulator(
        period=period,
        findings=findings,
        judgements=judgements,
        exceptions=exceptions,
        materiality=materiality,
        settlements=settlements,
    )
    sim_baseline = simulator.simulate_close_now()
    sim_cf = simulator.simulate_carry_forward_immaterial()
    sim_wait = simulator.simulate_wait_predicted(horizon_days=3)
    timings["simulator_suite_sec"] = time.perf_counter() - t_sim_start

    # 10. Financial Lineage
    t_lineage_start = time.perf_counter()
    lineage = build_lineage(
        period=period,
        verdict=verdict,
        findings=findings,
        exceptions=exceptions,
        exposure=exposure,
        materiality=materiality,
        settlements=settlements,
        orders=orders,
        bank_credits=credits,
    )
    timings["lineage_graph_sec"] = time.perf_counter() - t_lineage_start

    # 11. Human Review Queue
    t_queue_start = time.perf_counter()
    queue = build_review_queue(
        exceptions=exceptions,
        verdict=verdict,
        exposure=exposure,
        materiality=materiality,
        predictions=predictions,
        settlements=settlements,
        period_id=period.period_id,
    )
    timings["review_queue_sec"] = time.perf_counter() - t_queue_start

    # 12. Permutation Invariance
    shuffled_exceptions = list(exceptions)
    random.Random(42).shuffle(shuffled_exceptions)
    verdict_permuted = decide_period(
        period=period,
        findings=findings,
        judgements=judgements,
        exceptions=shuffled_exceptions,
        materiality=materiality,
        settlements=settlements,
    )
    is_permutation_invariant = (
        verdict.decision == verdict_permuted.decision
        and verdict.material_exposure_paise == verdict_permuted.material_exposure_paise
        and len(verdict.blockers) == len(verdict_permuted.blockers)
        and len(verdict.carry_forward) == len(verdict_permuted.carry_forward)
    )

    return SystemExecutionResult(
        period=period,
        findings=findings,
        exceptions=exceptions,
        judgements=judgements,
        verdict=verdict,
        exposure=exposure,
        certificate=cert,
        predictions=predictions,
        lineage=lineage,
        review_queue=queue,
        sim_baseline=sim_baseline,
        sim_cf=sim_cf,
        sim_wait=sim_wait,
        is_permutation_invariant=is_permutation_invariant,
        is_idempotent=is_idempotent,
        timings=timings,
        settlements=settlements,
        orders=orders,
        credits=credits,
        preds=preds,
        pools=pools,
        materiality=materiality,
    )


def score_against_ground_truth(
    sys_res: SystemExecutionResult,
    truth: list[TrueMatch],
    t_match: float,
) -> dict[str, Any]:
    """STAGE 2 — GROUND-TRUTH SCORING.

    Evaluates the Stage 1 system execution outputs against true matches.
    Ground truth is strictly read-only and never modifies system decisions.
    """
    total_settlements = len(sys_res.settlements)
    total_portfolio_paise = sys_res.exposure.total_value_paise

    rep = evaluate(sys_res.settlements, truth, sys_res.preds, sys_res.pools, t_match)
    truth_by_id = {t.settlement_id: set(t.order_ids) for t in truth}
    preds_by_id = {p.settlement_id: set(p.order_ids) if p.order_ids else None for p in sys_res.preds}

    exact_matches: list[str] = []
    false_proofs: list[str] = []
    declined: list[str] = []

    for sid, truth_orders in truth_by_id.items():
        pred_orders = preds_by_id.get(sid)
        if pred_orders is None:
            declined.append(sid)
        elif pred_orders == truth_orders:
            exact_matches.append(sid)
        else:
            false_proofs.append(sid)

    proven_count = len(exact_matches) + len(false_proofs)
    reconciliation_accuracy = len(exact_matches) / total_settlements
    proof_precision = len(exact_matches) / max(1, proven_count)
    false_proof_rate = len(false_proofs) / max(1, proven_count)

    # Safety: check if any false proof was auto-posted or allowed to close
    unsafe_auto_resolutions = 0
    for sid in false_proofs:
        j = sys_res.judgements.get(sid)
        if j is not None and j.decision is Decision.AUTO_POST:
            unsafe_auto_resolutions += 1
        if sid in sys_res.verdict.carry_forward:
            unsafe_auto_resolutions += 1

    safe_resolution_rate = len(exact_matches) / total_settlements
    unsafe_auto_resolution_rate = unsafe_auto_resolutions / total_settlements

    # Exposure & Conservation Law Verification
    reconciled_net = sys_res.exposure.verified_value_paise
    net_unresolved = sys_res.exposure.net_unresolved_exposure_paise
    gross_contested = sys_res.exposure.gross_contested_claim_exposure_paise
    conservation_holds = (reconciled_net + net_unresolved == total_portfolio_paise)
    gross_ge_net = (gross_contested >= net_unresolved)

    # Blocker metrics
    active_blocker_instances = sys_res.verdict.active_blocker_rule_instances
    unique_blocked_ex = sys_res.verdict.unique_blocked_exceptions
    unique_blocked_setl = sys_res.verdict.unique_blocked_settlements
    blocker_breakdown = sys_res.verdict.blocker_rule_breakdown

    # Predictions
    high_conf_preds = [p for p in sys_res.predictions if p.probability >= 0.70]
    avg_pred_prob = (
        sum(p.probability for p in sys_res.predictions) / len(sys_res.predictions)
        if sys_res.predictions else 0.0
    )

    t_overhead = sum(v for k, v in sys_res.timings.items() if k != "reconciliation_solver_sec")

    results = {
        "evaluation_protocol": {
            "stage_1_ground_truth_isolation": True,
            "stage_2_scoring_read_only": True,
            "seed": SEED_TRAIN,
            "period_derived_start": sys_res.period.start.isoformat() if sys_res.period.start else None,
            "period_derived_end": sys_res.period.end.isoformat() if sys_res.period.end else None,
        },
        "dataset": {
            "n_settlements": total_settlements,
            "n_orders": len(sys_res.orders),
            "n_credits": len(sys_res.credits),
            "total_value_paise": total_portfolio_paise,
            "total_value_rupees": rupees(total_portfolio_paise),
        },
        "ground_truth_reconciliation_scoring": {
            "exact_matches": len(exact_matches),
            "matching_accuracy": reconciliation_accuracy,
            "proof_precision": proof_precision,
            "false_proof_rate": false_proof_rate,
            "false_proof_count": len(false_proofs),
            "false_proof_ids": false_proofs,
            "declined_count": len(declined),
            "pair_precision": rep.precision,
            "pair_recall": rep.recall,
            "reconciled_value_paise": reconciled_net,
            "reconciled_value_rupees": rupees(reconciled_net),
            "reconciled_value_share": sys_res.exposure.reconciled_value_share,
        },
        "close_readiness_controller_system_output": {
            "verdict": sys_res.verdict.decision.value,
            "is_blocked": sys_res.verdict.decision == ReadinessDecision.BLOCKED,
            "primary_economic_metric": "net_unresolved_exposure_paise",
            "net_unresolved_exposure_paise": net_unresolved,
            "net_unresolved_exposure_rupees": rupees(net_unresolved),
            "net_unresolved_exposure_pct": sys_res.exposure.net_unresolved_share * 100,
            "gross_contested_claim_exposure_paise": gross_contested,
            "gross_contested_claim_exposure_rupees": rupees(gross_contested),
            "gross_contested_claim_exposure_pct": sys_res.exposure.gross_contested_share * 100,
            "accounting_conservation_holds": conservation_holds,
            "materiality_threshold_paise": sys_res.materiality.max_allowable_exposure_paise(total_portfolio_paise),
            "materiality_threshold_rupees": rupees(sys_res.materiality.max_allowable_exposure_paise(total_portfolio_paise)),
            "material_exposure_paise": sys_res.verdict.material_exposure_paise,
            "material_exposure_rupees": rupees(sys_res.verdict.material_exposure_paise),
            "active_blocker_rule_instances": active_blocker_instances,
            "unique_blocked_exceptions": unique_blocked_ex,
            "unique_blocked_settlements": unique_blocked_setl,
            "blocker_rule_breakdown": blocker_breakdown,
            "carry_forward_count": len(sys_res.verdict.carry_forward_items),
            "carry_forward_exposure_paise": sys_res.verdict.get_carry_forward_total_paise(),
            "carry_forward_exposure_rupees": rupees(sys_res.verdict.get_carry_forward_total_paise()),
            "safe_resolution_rate": safe_resolution_rate,
            "unsafe_auto_resolution_rate": unsafe_auto_resolution_rate,
            "unsafe_auto_resolutions": unsafe_auto_resolutions,
        },
        "reproducibility_and_integrity": {
            "permutation_invariant": sys_res.is_permutation_invariant,
            "idempotent": sys_res.is_idempotent,
            "certificate_id": sys_res.certificate.certificate_id,
            "evidence_hash": sys_res.certificate.evidence_hash,
            "policy_version": sys_res.certificate.materiality_policy_version,
        },
        "resolution_predictor": {
            "total_predictions": len(sys_res.predictions),
            "high_confidence_resolutions": len(high_conf_preds),
            "avg_probability": avg_pred_prob,
        },
        "lineage_and_governance": {
            "lineage_nodes": len(sys_res.lineage.nodes),
            "lineage_edges": len(sys_res.lineage.edges),
            "review_queue_depth": len(sys_res.review_queue.items),
            "top_priority_item": sys_res.review_queue.items[0].exception_id if sys_res.review_queue.items else None,
            "top_priority_score": sys_res.review_queue.items[0].priority_score if sys_res.review_queue.items else None,
        },
        "performance_and_latency": {
            "reconciliation_solver_sec": sys_res.timings["reconciliation_solver_sec"],
            "close_controller_eval_sec": sys_res.timings["close_controller_eval_sec"],
            "certificate_issue_sec": sys_res.timings["certificate_issue_sec"],
            "prediction_batch_sec": sys_res.timings["prediction_batch_sec"],
            "simulator_suite_sec": sys_res.timings["simulator_suite_sec"],
            "lineage_graph_sec": sys_res.timings["lineage_graph_sec"],
            "review_queue_sec": sys_res.timings["review_queue_sec"],
            "total_closepilot_overhead_sec": t_overhead,
            "settlements_per_sec": total_settlements / max(0.001, t_overhead),
        },
    }

    return results


def run_benchmark(n: int = 250, seed: int = SEED_TRAIN) -> dict[str, Any]:
    print(f"=== CLOSEPILOT BENCHMARK EVALUATION (N={n}, Seed={seed}) ===")

    # 1. Dataset Generation
    t_gen_start = time.perf_counter()
    ds = build(n, seed=seed)
    t_gen = time.perf_counter() - t_gen_start
    print(f"Dataset generated in {t_gen:.2f}s: {len(ds.settlements)} settlements, {len(ds.orders)} orders")

    # STAGE 1 — SYSTEM EXECUTION (ZERO ds.truth access)
    print("\n--- STAGE 1: SYSTEM EXECUTION (GROUND-TRUTH ISOLATED) ---")
    sys_res = execute_system_pipeline(
        settlements=ds.settlements,
        orders=ds.orders,
        credits=ds.credits,
        seed=seed,
        n=n,
    )
    print(f"  Derived Period: {sys_res.period.start} → {sys_res.period.end}")
    print(f"  Verdict: {sys_res.verdict.decision.value}")
    print(f"  Primary Exposure (Net Unresolved): {rupees(sys_res.exposure.net_unresolved_exposure_paise)} ({sys_res.exposure.net_unresolved_share:.2%})")
    print(f"  Diagnostic Exposure (Gross Contested Claims): {rupees(sys_res.exposure.gross_contested_claim_exposure_paise)} ({sys_res.exposure.gross_contested_share:.2%})")
    print(f"  Active Blocker Rule Instances: {sys_res.verdict.active_blocker_rule_instances}")
    print(f"  Affected Blocked Exceptions: {sys_res.verdict.unique_blocked_exceptions}")
    print(f"  Affected Blocked Settlements: {sys_res.verdict.unique_blocked_settlements}")
    print(f"  Blocker Rule Breakdown: {sys_res.verdict.blocker_rule_breakdown}")
    print(f"  Certificate Hash: {sys_res.certificate.evidence_hash[:16]}...")

    # STAGE 2 — GROUND-TRUTH SCORING
    print("\n--- STAGE 2: GROUND-TRUTH SCORING ---")
    results = score_against_ground_truth(
        sys_res=sys_res,
        truth=ds.truth,
        t_match=sys_res.timings["reconciliation_solver_sec"],
    )
    scoring = results["ground_truth_reconciliation_scoring"]
    print(f"  Exact Matches: {scoring['exact_matches']} ({scoring['matching_accuracy']:.1%})")
    print(f"  Proof Precision: {scoring['proof_precision']:.4f}")
    print(f"  False Proofs: {scoring['false_proof_count']}")
    print(f"  Unsafe Auto-Resolutions: {results['close_readiness_controller_system_output']['unsafe_auto_resolutions']} (Rate: {results['close_readiness_controller_system_output']['unsafe_auto_resolution_rate']:.2%})")
    print(f"  Accounting Conservation Law: {results['close_readiness_controller_system_output']['accounting_conservation_holds']} (Reconciled Net + Net Unresolved == Total Portfolio)")

    return results


if __name__ == "__main__":
    res = run_benchmark(250, SEED_TRAIN)
    out_path = Path(__file__).resolve().parents[1] / "data" / "benchmark_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=2))
    print(f"\nBenchmark results written to: {out_path}")
