"""CLOSEPILOT — Controller Dashboard Server (Phase 4).

Answers the single decisive question:
    "CAN I CLOSE?"

Downstream of the deterministic Close Controller.
Consumes:
- attest.close.readiness (PeriodVerdict, Blocker, CarryForwardItem)
- attest.close.exposure (PeriodExposure, ExposureItem)
- attest.close.materiality (MaterialityBound)
- closepilot.predictor (ResolutionPrediction)
- closepilot.simulator (simulate_close)
- closepilot.lineage (build_lineage)
- closepilot.review_queue (HumanReviewQueue, build_review_queue)
- closepilot.investigator (AIInvestigator)

Zero external dependencies — runs on Python stdlib ThreadingHTTPServer.
"""

from __future__ import annotations

import datetime
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from attest.close.exposure import (
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
from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import BankCredit, Method, Order, Settlement
from attest.money import rupees
from attest.policy import Decision, Judgement
from attest.verdict import Finding, Proof, Verdict

from closepilot.investigator import AIInvestigator, InvestigationToolRegistry
from closepilot.lineage import build_lineage
from closepilot.predictor import predict_batch
from closepilot.review_queue import (
    HumanActionType,
    HumanReviewQueue,
    build_review_queue,
)
from closepilot.simulator import (
    CloseSimulator,
    ScenarioType,
    SimulationScenario,
    simulate_close,
)

UI_DIR = Path(__file__).resolve().parent / "ui"


def create_demo_controller_state() -> dict[str, Any]:
    """Create a realistic deterministic demo state for the ClosePilot controller."""
    period = Period(
        period_id="P-2026-08",
        start=datetime.date(2026, 8, 1),
        end=datetime.date(2026, 8, 31),
        settlement_ids=(
            "setl_001", "setl_002", "setl_003", "setl_004", "setl_005",
            "setl_006", "setl_007", "setl_008", "setl_009", "setl_010",
        ),
    )

    settlements = [
        Settlement(settlement_id="setl_001", settled_on=datetime.date(2026, 8, 5), net_paise=1_500_000, utr="UTR-AXIS-001"),
        Settlement(settlement_id="setl_002", settled_on=datetime.date(2026, 8, 10), net_paise=2_200_000, utr="UTR-HDFC-002"),
        Settlement(settlement_id="setl_003", settled_on=datetime.date(2026, 8, 15), net_paise=850_000, utr="UTR-ICICI-003"),
        Settlement(settlement_id="setl_004", settled_on=datetime.date(2026, 8, 18), net_paise=150_000, utr="UTR-SBI-004"),
        Settlement(settlement_id="setl_005", settled_on=datetime.date(2026, 8, 22), net_paise=350_000, utr="UTR-YES-005"),
        Settlement(settlement_id="setl_006", settled_on=datetime.date(2026, 8, 25), net_paise=120_000, utr="UTR-KOTAK-006"),
        Settlement(settlement_id="setl_007", settled_on=datetime.date(2026, 8, 28), net_paise=45_000, utr="UTR-CITI-007"),
        Settlement(settlement_id="setl_008", settled_on=datetime.date(2026, 8, 29), net_paise=35_000, utr="UTR-IDFC-008"),
        Settlement(settlement_id="setl_009", settled_on=datetime.date(2026, 8, 30), net_paise=25_000, utr="UTR-PNB-009"),
        Settlement(settlement_id="setl_010", settled_on=datetime.date(2026, 8, 31), net_paise=27_702, utr="UTR-FED-010"),
    ]

    orders = [
        Order(order_id="ord_101", captured_on=datetime.date(2026, 8, 4), gross_paise=1_500_000, method=Method.UPI, customer_name="Customer 101", payment_id="pay_101"),
        Order(order_id="ord_102", captured_on=datetime.date(2026, 8, 9), gross_paise=2_200_000, method=Method.CARD, customer_name="Customer 102", payment_id="pay_102"),
        Order(order_id="ord_103", captured_on=datetime.date(2026, 8, 14), gross_paise=850_000, method=Method.NETBANKING, customer_name="Customer 103", payment_id="pay_103"),
        Order(order_id="ord_104", captured_on=datetime.date(2026, 8, 17), gross_paise=100_000, method=Method.UPI, customer_name="Customer 104", payment_id="pay_104"),
        Order(order_id="ord_105", captured_on=datetime.date(2026, 8, 21), gross_paise=300_000, method=Method.CARD, customer_name="Customer 105", payment_id="pay_105"),
        Order(order_id="ord_106", captured_on=datetime.date(2026, 8, 24), gross_paise=115_000, method=Method.UPI, customer_name="Customer 106", payment_id="pay_106"),
        Order(order_id="ord_107", captured_on=datetime.date(2026, 8, 27), gross_paise=40_000, method=Method.UPI, customer_name="Customer 107", payment_id="pay_107"),
    ]

    bank_credits = [
        BankCredit(txn_id="bc_001", value_date=datetime.date(2026, 8, 5), credit_paise=1_500_000, narration="CMS/UTR-AXIS-001/RAZORPAY PAYOUT"),
        BankCredit(txn_id="bc_002", value_date=datetime.date(2026, 8, 10), credit_paise=2_200_000, narration="CMS/UTR-HDFC-002/RAZORPAY PAYOUT"),
        BankCredit(txn_id="bc_004", value_date=datetime.date(2026, 8, 18), credit_paise=150_000, narration="CMS/UTR-SBI-004/PAYOUT"),
        BankCredit(txn_id="bc_005", value_date=datetime.date(2026, 8, 22), credit_paise=350_000, narration="CMS/UTR-YES-005/SPLIT SETTLEMENT"),
        BankCredit(txn_id="bc_006", value_date=datetime.date(2026, 8, 25), credit_paise=120_000, narration="CMS/UTR-KOTAK-006/PAYOUT NOTE: PLEASE VERIFY ADJUSTMENT"),
    ]

    # Exceptions
    exceptions = [
        Exception_(
            id="EX-00004",
            settlement_id="setl_004",
            reason=ReasonCode.MULTIPLE_VALID_ASSIGNMENTS,
            severity=Severity.HIGH,
            amount_paise=150_000,
            unexplained_paise=150_000,
            established=("2 candidate order combinations satisfy amount",),
            missing="order reference required to break tie",
            next_step="supply gateway order breakdown",
            partial=None,
            settled=None,
        ),
        Exception_(
            id="EX-00005",
            settlement_id="setl_005",
            reason=ReasonCode.MISSING_TRANSACTION,
            severity=Severity.HIGH,
            amount_paise=350_000,
            unexplained_paise=50_000,
            established=("order ord_105 explains 300000 paise",),
            missing="50000 paise capture record missing from export",
            next_step="re-export capture logs for 2026-08-21",
            partial=None,
            settled=None,
        ),
        Exception_(
            id="EX-00006",
            settlement_id="setl_006",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=120_000,
            unexplained_paise=5_000,
            established=("order ord_106 matches partially",),
            missing="T+2 settlement window cleared",
            next_step="confirm payout calendar",
            partial=None,
            settled=None,
        ),
        Exception_(
            id="EX-00007",
            settlement_id="setl_007",
            reason=ReasonCode.TIMING_MISMATCH,
            severity=Severity.LOW,
            amount_paise=45_000,
            unexplained_paise=5_000,
            established=("order ord_107 matches partially",),
            missing="T+2 timing gap",
            next_step="wait for next batch",
            partial=None,
            settled=None,
        ),
        Exception_(
            id="EX-00008",
            settlement_id="setl_008",
            reason=ReasonCode.UNKNOWN_ADJUSTMENT,
            severity=Severity.LOW,
            amount_paise=35_000,
            unexplained_paise=2_450,
            established=(),
            missing="unexplained fee correction of 2450 paise",
            next_step="check fee reversal statement",
            partial=None,
            settled=None,
        ),
    ]

    materiality = MaterialityBound(
        threshold_bps=100,  # 1.00%
        floor_paise=10_000,  # ₹100 floor
        ceiling_paise=10_000_000,  # ₹100,000 ceiling
    )

    # Findings
    findings = [
        Finding(settlement_id="setl_001", verdict=Verdict.PROVEN, proofs=(Proof(settlement_id="setl_001", order_ids=("ord_101",), gross_paise=1_500_000, fee_paise=0, tax_paise=0, adjustment_paise=0, net_paise=1_500_000, residual_paise=0, tolerance_paise=1),)),
        Finding(settlement_id="setl_002", verdict=Verdict.PROVEN, proofs=(Proof(settlement_id="setl_002", order_ids=("ord_102",), gross_paise=2_200_000, fee_paise=0, tax_paise=0, adjustment_paise=0, net_paise=2_200_000, residual_paise=0, tolerance_paise=1),)),
        Finding(settlement_id="setl_003", verdict=Verdict.PROVEN, proofs=(Proof(settlement_id="setl_003", order_ids=("ord_103",), gross_paise=850_000, fee_paise=0, tax_paise=0, adjustment_paise=0, net_paise=850_000, residual_paise=0, tolerance_paise=1),)),
        Finding(settlement_id="setl_004", verdict=Verdict.AMBIGUOUS, proofs=()),
        Finding(settlement_id="setl_005", verdict=Verdict.CONTRADICTED, proofs=()),
        Finding(settlement_id="setl_006", verdict=Verdict.AMBIGUOUS, proofs=()),
        Finding(settlement_id="setl_007", verdict=Verdict.AMBIGUOUS, proofs=()),
        Finding(settlement_id="setl_008", verdict=Verdict.AMBIGUOUS, proofs=()),
    ]

    judgements = {
        s.settlement_id: Judgement(
            decision=Decision.AUTO_POST if i < 3 else Decision.REVIEW,
            expected_loss_paise=0,
            p_error=0.01,
            reasons=("Demo policy evaluation",),
        )
        for i, s in enumerate(settlements)
    }

    # Evaluate authoritative close verdict
    verdict = decide_period(
        period=period,
        findings=findings,
        judgements=judgements,
        exceptions=exceptions,
        materiality=materiality,
        settlements=settlements,
    )

    # Predict resolutions
    predictions = predict_batch(exceptions, settlements=settlements)

    # Compute period exposure
    exposure = assess_exposure(
        findings=findings,
        exceptions=exceptions,
        settlements=settlements,
        target_settlement_ids=period.settlement_ids,
    )

    # Build lineage graph
    lineage = build_lineage(
        period=period,
        verdict=verdict,
        findings=findings,
        exceptions=exceptions,
        exposure=exposure,
        materiality=materiality,
        settlements=settlements,
        orders=orders,
        bank_credits=bank_credits,
    )

    # Build human review queue
    review_queue = build_review_queue(
        exceptions=exceptions,
        verdict=verdict,
        exposure=exposure,
        materiality=materiality,
        predictions=predictions,
        settlements=settlements,
        period_id=period.period_id,
    )

    # AI Investigator tools
    tools = InvestigationToolRegistry(
        settlements=settlements,
        exceptions=exceptions,
        orders=orders,
        bank_credits=bank_credits,
        verdict=verdict,
        lineage_graph=lineage,
    )
    investigator = AIInvestigator(tools)

    return {
        "period": period,
        "settlements": settlements,
        "orders": orders,
        "bank_credits": bank_credits,
        "exceptions": exceptions,
        "materiality": materiality,
        "findings": findings,
        "judgements": judgements,
        "verdict": verdict,
        "exposure": exposure,
        "predictions": predictions,
        "lineage": lineage,
        "review_queue": review_queue,
        "investigator": investigator,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving ClosePilot APIs and dashboard static files."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet logger for clean test execution

    def send_json(self, data: Any, status: int = 200) -> None:
        encoded = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        state: dict[str, Any] = self.server.controller_state  # type: ignore

        if path == "/api/closepilot/readiness":
            self._handle_readiness(state)
        elif path == "/api/closepilot/why-blocked":
            self._handle_why_blocked(state)
        elif path == "/api/closepilot/materiality":
            self._handle_materiality(state)
        elif path == "/api/closepilot/predictions":
            self._handle_predictions(state)
        elif path == "/api/closepilot/evidence":
            self._handle_evidence(state, query)
        elif path == "/api/closepilot/review-queue":
            self._handle_review_queue(state)
        else:
            self._handle_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        state: dict[str, Any] = self.server.controller_state  # type: ignore

        if path == "/api/closepilot/simulate":
            self._handle_simulate(state, payload)
        elif path == "/api/closepilot/review-action":
            self._handle_review_action(state, payload)
        elif path == "/api/closepilot/investigate":
            self._handle_investigate(state, payload)
        else:
            self.send_json({"error": f"Endpoint '{path}' not found"}, status=404)

    def _handle_readiness(self, state: dict[str, Any]) -> None:
        verdict: PeriodVerdict = state["verdict"]
        period: Period = state["period"]
        settlements: list[Settlement] = state["settlements"]
        materiality: MaterialityBound = state["materiality"]
        exceptions: list[Exception_] = state["exceptions"]
        predictions = state["predictions"]
        exposure: PeriodExposure | None = state.get("exposure")

        total_value = sum(s.net_paise for s in settlements)
        allowable_exposure = materiality.max_allowable_exposure_paise(total_value)

        # Use authoritative PeriodExposure when available; otherwise derive from verdict
        if exposure is not None:
            net_unresolved = exposure.net_unresolved_exposure_paise
            gross_contested = exposure.gross_contested_claim_exposure_paise
            reconciled_value = exposure.verified_value_paise
        else:
            net_unresolved = sum(ex.unexplained_paise for ex in exceptions)
            gross_contested = net_unresolved
            reconciled_value = max(0, total_value - net_unresolved)

        # Count auto-resolvable items
        likely_resolutions = [
            p for p in predictions
            if p.probability >= 0.70
        ]

        response_data = {
            "period_id": period.period_id,
            "decision": verdict.decision.value,
            "can_close": verdict.decision == ReadinessDecision.READY_TO_CLOSE,
            "total_financial_value_paise": total_value,
            "total_financial_value_rupees": rupees(total_value),
            "reconciled_value_paise": reconciled_value,
            "reconciled_value_rupees": rupees(reconciled_value),
            # Primary close-readiness economic metric
            "net_unresolved_exposure_paise": net_unresolved,
            "net_unresolved_exposure_rupees": rupees(net_unresolved),
            # Diagnostic/risk metric for ambiguity
            "gross_contested_claim_exposure_paise": gross_contested,
            "gross_contested_claim_exposure_rupees": rupees(gross_contested),
            # Legacy alias for backward compatibility
            "unresolved_exposure_paise": net_unresolved,
            "unresolved_exposure_rupees": rupees(net_unresolved),
            "material_exposure_paise": verdict.material_exposure_paise,
            "material_exposure_rupees": rupees(verdict.material_exposure_paise),
            "materiality_threshold_paise": allowable_exposure,
            "materiality_threshold_rupees": rupees(allowable_exposure),
            "materiality_policy": {
                "version": materiality.version,
                "threshold_bps": materiality.threshold_bps,
                "floor_rupees": rupees(materiality.floor_paise),
                "ceiling_rupees": rupees(materiality.ceiling_paise),
            },
            # Blocker semantics: distinguish rule instances from affected entities
            "active_blocker_rule_instances": verdict.active_blocker_rule_instances,
            "unique_blocked_exceptions": verdict.unique_blocked_exceptions,
            "unique_blocked_settlements": verdict.unique_blocked_settlements,
            "blocker_rule_breakdown": verdict.blocker_rule_breakdown,
            # Legacy alias
            "blocker_count": verdict.active_blocker_rule_instances,
            "blockers": [b.to_dict() for b in verdict.structured_blockers],
            "carry_forward_count": len(verdict.carry_forward_items),
            "carry_forward_exposure_paise": verdict.get_carry_forward_total_paise(),
            "carry_forward_exposure_rupees": rupees(verdict.get_carry_forward_total_paise()),
            "carry_forward_items": [cf.to_dict() for cf in verdict.carry_forward_items],
            "exception_count": len(exceptions),
            "likely_resolutions_count": len(likely_resolutions),
            "reasons": list(verdict.reasons),
            "close_impact": (
                f"Close authorization is BLOCKED by active safety rules and material unresolved exposure. "
                f"[{verdict.active_blocker_rule_instances}] active blocker rule instances, "
                f"[{verdict.unique_blocked_exceptions}] unique blocked exceptions, "
                f"[{verdict.unique_blocked_settlements}] unique blocked settlements."
                if verdict.decision == ReadinessDecision.BLOCKED
                else f"Authorized for carry-forward: {rupees(net_unresolved)}"
            ),
        }
        self.send_json(response_data)

    def _handle_why_blocked(self, state: dict[str, Any]) -> None:
        verdict: PeriodVerdict = state["verdict"]
        blockers = verdict.structured_blockers

        items = []
        for b in blockers:
            items.append({
                "kind": b.kind.value,
                "ref_id": b.ref_id,
                "reason": b.reason,
                "exposure_paise": b.exposure_paise,
                "exposure_rupees": rupees(b.exposure_paise),
                "remedy": self._get_remedy(b.kind),
            })

        self.send_json({
            "is_blocked": verdict.decision == ReadinessDecision.BLOCKED,
            "total_blockers": len(blockers),
            "blockers": items,
            "integrity_pass": not any(b.kind == BlockerKind.COMPROMISED_INTEGRITY for b in blockers),
            "arithmetic_pass": not any(b.kind == BlockerKind.FAILED_INVARIANT for b in blockers),
        })

    def _get_remedy(self, kind: BlockerKind) -> str:
        remedies = {
            BlockerKind.UNRESOLVED_MATERIAL_AMOUNT: "Resolve or book manual adjustments for high-exposure exceptions until total exposure is below materiality threshold.",
            BlockerKind.AMBIGUOUS_MATERIAL_SETTLEMENT: "Provide order-level payment identifiers to discriminate between multiple valid subsets.",
            BlockerKind.CONTRADICTORY_EVIDENCE: "Reconcile conflicting settlement finding proofs with payment gateway capture logs.",
            BlockerKind.HIGH_SEVERITY_EXCEPTION: "Investigate exception root-cause; data quality or full transaction shortfall must be cleared.",
            BlockerKind.MISSING_SETTLEMENT: "Re-pull gateway settlement batch export for period range.",
            BlockerKind.DUPLICATE_LEDGER_IMPACT: "De-duplicate order references across settlements to prevent double credit.",
            BlockerKind.COMPROMISED_INTEGRITY: "Expand search envelope; solver candidate universe was truncated illegally.",
            BlockerKind.POLICY_BLOCKED: "Obtain formal senior controller approval override.",
        }
        return remedies.get(kind, "Investigate exception details in Human Review Queue.")

    def _handle_materiality(self, state: dict[str, Any]) -> None:
        materiality: MaterialityBound = state["materiality"]
        settlements: list[Settlement] = state["settlements"]
        exceptions: list[Exception_] = state["exceptions"]
        exposure: PeriodExposure | None = state.get("exposure")

        total_value = sum(s.net_paise for s in settlements)
        allowable_exposure = materiality.max_allowable_exposure_paise(total_value)

        # Use authoritative net unresolved metric from PeriodExposure when available
        if exposure is not None:
            net_unresolved = exposure.net_unresolved_exposure_paise
        else:
            net_unresolved = sum(ex.unexplained_paise for ex in exceptions)

        items = []
        for ex in exceptions:
            is_mat = ex.unexplained_paise > allowable_exposure
            items.append({
                "exception_id": ex.id,
                "settlement_id": ex.settlement_id,
                "exposure_paise": ex.unexplained_paise,
                "exposure_rupees": rupees(ex.unexplained_paise),
                "is_individually_material": is_mat,
                "percentage_of_allowable": round((ex.unexplained_paise / max(1, allowable_exposure)) * 100, 1),
            })

        self.send_json({
            "policy_version": materiality.version,
            "threshold_bps": materiality.threshold_bps,
            "effective_threshold_rupees": rupees(allowable_exposure),
            "floor_rupees": rupees(materiality.floor_paise),
            "ceiling_rupees": rupees(materiality.ceiling_paise),
            "total_period_value_rupees": rupees(total_value),
            "net_unresolved_exposure_rupees": rupees(net_unresolved),
            # Legacy alias
            "total_unresolved_rupees": rupees(net_unresolved),
            "exceeds_threshold": net_unresolved > allowable_exposure,
            "exceptions": items,
        })

    def _handle_predictions(self, state: dict[str, Any]) -> None:
        predictions = state["predictions"]
        results = [p.to_dict() for p in predictions]
        self.send_json({
            "total_predictions": len(results),
            "predictions": sorted(results, key=lambda p: -p["probability"]),
        })

    def _handle_evidence(self, state: dict[str, Any], query: dict[str, list[str]]) -> None:
        target_id = query.get("id", [""])[0]
        lineage = state["lineage"]
        investigator = state["investigator"]

        trace = lineage.trace_backward(target_id)
        report = investigator.investigate(target_id=target_id)

        self.send_json({
            "target_id": target_id,
            "lineage_nodes": [n.to_dict() for n in trace],
            "ai_investigation": report.to_dict(),
        })

    def _handle_review_queue(self, state: dict[str, Any]) -> None:
        review_queue: HumanReviewQueue = state["review_queue"]
        self.send_json(review_queue.to_dict())

    def _handle_review_action(self, state: dict[str, Any], payload: dict[str, Any]) -> None:
        review_queue: HumanReviewQueue = state["review_queue"]
        exception_id = payload.get("exception_id", "")
        action_type_str = payload.get("action_type", "")
        reviewer = payload.get("reviewer", "")
        justification = payload.get("justification", "")
        evidence_ref = payload.get("evidence_ref")

        try:
            action_type = HumanActionType(action_type_str)
            updated_queue = review_queue.record_action(
                exception_id=exception_id,
                action_type=action_type,
                reviewer=reviewer,
                justification=justification,
                evidence_ref=evidence_ref,
            )
            state["review_queue"] = updated_queue
            self.send_json({
                "success": True,
                "message": f"Action {action_type.value} recorded for {exception_id}",
                "audit_record": updated_queue.audit_log[-1].to_dict(),
            })
        except Exception as e:
            self.send_json({"success": False, "error": str(e)}, status=400)

    def _handle_simulate(self, state: dict[str, Any], payload: dict[str, Any]) -> None:
        scenario_type_str = payload.get("scenario_type", "CLOSE_NOW")
        target_ids = payload.get("target_ids", [])
        horizon_days = payload.get("horizon_days", 2)

        try:
            scenario_type = ScenarioType(scenario_type_str)
        except ValueError:
            scenario_type = ScenarioType.CLOSE_NOW

        simulator = CloseSimulator(
            period=state["period"],
            findings=state["findings"],
            judgements=state["judgements"],
            exceptions=state["exceptions"],
            materiality=state["materiality"],
            settlements=state["settlements"],
        )

        if scenario_type == ScenarioType.CLOSE_NOW:
            outcome = simulator.simulate_close_now()
        elif scenario_type == ScenarioType.RESOLVE_EXCEPTIONS:
            outcome = simulator.simulate_resolve_exceptions(target_ids)
        elif scenario_type == ScenarioType.CARRY_FORWARD_IMMATERIAL:
            outcome = simulator.simulate_carry_forward_immaterial()
        elif scenario_type == ScenarioType.CLEAR_BLOCKER:
            outcome = simulator.simulate_clear_blocker(ref_ids=target_ids)
        elif scenario_type == ScenarioType.WAIT_PREDICTED_RESOLUTIONS:
            outcome = simulator.simulate_wait_predicted(horizon_days=horizon_days)
        else:
            outcome = simulator.simulate_close_now()

        actual = simulator.actual_baseline
        actual_dict = {
            "decision": actual.projected_verdict.value,
            "net_unresolved_exposure_paise": actual.unresolved_exposure_paise,
            "unresolved_exposure_paise": actual.unresolved_exposure_paise,
            "material_exposure_paise": actual.material_exposure_paise,
            "blockers": list(actual.blockers),
            "active_blocker_rule_instances": actual.active_blocker_rule_instances,
            "unique_blocked_exceptions": actual.unique_blocked_exceptions,
            "unique_blocked_settlements": actual.unique_blocked_settlements,
            "blocker_count": actual.blocker_count,
            "carry_forward_count": actual.carry_forward_count,
            "carry_forward_value_paise": actual.carry_forward_value_paise,
            "is_closeable": actual.is_closeable,
            "state_type": "ACTUAL",
        }

        hypothetical_dict = {
            "scenario_id": outcome.scenario_id,
            "scenario_type": outcome.scenario_type.value,
            "description": outcome.description,
            "decision": outcome.projected_verdict.value,
            "net_unresolved_exposure_paise": outcome.unresolved_exposure_paise,
            "unresolved_exposure_paise": outcome.unresolved_exposure_paise,
            "material_exposure_paise": outcome.material_exposure_paise,
            "blockers": list(outcome.blockers),
            "active_blocker_rule_instances": outcome.active_blocker_rule_instances,
            "unique_blocked_exceptions": outcome.unique_blocked_exceptions,
            "unique_blocked_settlements": outcome.unique_blocked_settlements,
            "blocker_count": outcome.blocker_count,
            "carry_forward_count": outcome.carry_forward_count,
            "carry_forward_value_paise": outcome.carry_forward_value_paise,
            "delta_unresolved_exposure_paise": outcome.delta_unresolved_exposure_paise,
            "delta_material_exposure_paise": outcome.delta_material_exposure_paise,
            "delta_blockers": outcome.delta_blocker_count,
            "verdict_transition": outcome.verdict_transition,
            "is_closeable": outcome.is_closeable,
            "explanation": outcome.explanation,
            "state_type": "HYPOTHETICAL",
        }

        self.send_json({
            "is_counterfactual": True,
            "scenario_name": outcome.description,
            "simulated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC"),
            "actual_state": actual_dict,
            "hypothetical_state": hypothetical_dict,
            "deltas": {
                "unresolved_exposure_paise": outcome.delta_unresolved_exposure_paise,
                "material_exposure_paise": outcome.delta_material_exposure_paise,
                "blockers": outcome.delta_blocker_count,
                "carry_forward": outcome.delta_carry_forward_count,
            },
        })

    def _handle_investigate(self, state: dict[str, Any], payload: dict[str, Any]) -> None:
        investigator: AIInvestigator = state["investigator"]
        target_id = payload.get("target_id", "")
        context_notes = payload.get("context_notes", "")

        report = investigator.investigate(target_id=target_id, context_notes=context_notes)
        self.send_json(report.to_dict())

    def _handle_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"

        file_path = UI_DIR / path.lstrip("/")
        if not file_path.exists() or file_path.is_dir():
            file_path = UI_DIR / "index.html"

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "text/html"

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json({"error": f"Failed to read file: {e}"}, status=500)


def create_dashboard_server(
    host: str = "127.0.0.1",
    port: int = 8430,
    state: dict[str, Any] | None = None,
) -> ThreadingHTTPServer:
    """Create a configured ThreadingHTTPServer for the ClosePilot Dashboard."""
    if state is None:
        state = create_demo_controller_state()

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.controller_state = state  # type: ignore
    return server


def run_dashboard(
    host: str = "127.0.0.1",
    port: int = 8430,
    open_browser: bool = False,
) -> None:
    """Run the ClosePilot Controller Dashboard server."""
    server = create_dashboard_server(host=host, port=port)
    print(f"=== CLOSEPILOT CONTROLLER DASHBOARD ===")
    print(f"Server listening on http://{host}:{port}")
    print(f"Question: CAN I CLOSE?")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://{host}:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ClosePilot Dashboard...")
        server.shutdown()


if __name__ == "__main__":
    port = int(os.environ.get("CLOSEPILOT_PORT", "8430"))
    host = os.environ.get("CLOSEPILOT_HOST", "127.0.0.1")
    run_dashboard(host=host, port=port, open_browser=True)
