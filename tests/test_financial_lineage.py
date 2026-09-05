"""Tests for ClosePilot Financial Lineage Layer (Phase 2C).

Verifies the Financial Lineage Engine:
    FinancialLineageGraph & build_lineage()

Guarantees Verified:
1. DETERMINISTIC IDS: Node and edge identifiers are deterministic functions of domain entities.
2. ZERO EVIDENCE FABRICATION: Missing evidence is explicitly modeled as `MissingEvidenceRecord`.
3. COMPLETE 7-STAGE CHAIN:
   Event → Order/BankCredit → Settlement → Finding/Exception → Exposure → Materiality → Verdict
4. BIDIRECTIONAL TRACEABILITY:
   - Backward trace: Verdict/Blocker → upstream root causes.
   - Forward trace: Order/Settlement → downstream close impact.
5. CARDINALITY:
   - Many-to-One: Multi-order bundle into settlement.
   - One-to-Many: Settlement with multiple exceptions and verdict with multiple blockers.
6. INTEGRITY & BROKEN REFERENCE DETECTION:
   - Detects broken edge endpoints and orphan exceptions.
7. AUDIT EXPLANATION NARRATIVE:
   - Formats clear, human-readable step-by-step audit trails.
"""

from __future__ import annotations

from datetime import date

import pytest

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import BankCredit, Method, Order, Settlement
from attest.policy import Decision, Judgement
from attest.searchspace import Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict

from attest.close.exposure import ExposureItem, ExposureKind, PeriodExposure, assess_exposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import BlockerKind, ReadinessDecision, decide_period
from closepilot.lineage import (
    EdgeRelationship,
    FinancialLineageGraph,
    LineageDefect,
    LineageEdge,
    LineageNode,
    LineageStage,
    MissingEvidenceRecord,
    build_lineage,
    node_id_bank,
    node_id_blocker,
    node_id_carry_forward,
    node_id_event,
    node_id_exception,
    node_id_exposure,
    node_id_finding,
    node_id_materiality,
    node_id_order,
    node_id_proof,
    node_id_settlement,
    node_id_verdict,
)

_TODAY = date(2026, 9, 1)


# --------------------------------------------------------------------------
# Fixture Helpers
# --------------------------------------------------------------------------

def _make_order(oid: str, gross: int, method: Method = Method.UPI, payment_id: str | None = None) -> Order:
    return Order(
        order_id=oid,
        captured_on=_TODAY,
        gross_paise=gross,
        method=method,
        customer_name="Test Customer",
        payment_id=payment_id or f"pay_{oid}",
    )


def _make_settlement(sid: str, net: int, utr: str | None = None) -> Settlement:
    return Settlement(
        settlement_id=sid,
        settled_on=_TODAY,
        net_paise=net,
        utr=utr or f"UTR_{sid}",
    )


def _make_bank_credit(txid: str, credit: int, utr: str) -> BankCredit:
    return BankCredit(
        txn_id=txid,
        value_date=_TODAY,
        credit_paise=credit,
        narration=f"NEFT CR {utr} RAZORPAY",
    )


def _make_proven_finding(sid: str, order_ids: tuple[str, ...], net: int) -> Finding:
    sp = SearchSpace(universe=100, members=frozenset(order_ids))
    sp.reductions.append(Reduction("deterministic_date", 10, True, "calendar window"))
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


def _make_exception(
    eid: str,
    sid: str,
    unexplained: int,
    total: int,
    reason: ReasonCode = ReasonCode.TIMING_MISMATCH,
    severity: Severity = Severity.LOW,
    missing: str | None = None,
    established: tuple[str, ...] = (),
) -> Exception_:
    return Exception_(
        id=eid,
        settlement_id=sid,
        reason=reason,
        severity=severity,
        amount_paise=total,
        unexplained_paise=unexplained,
        established=established,
        missing=missing,
        next_step="Audit verification",
        partial=None,
    )


# --------------------------------------------------------------------------
# Test Cases
# --------------------------------------------------------------------------

class TestFinancialLineage:
    """Comprehensive test suite for the Financial Lineage layer."""

    def test_deterministic_identifiers(self) -> None:
        """Verify all lineage node IDs are deterministic and idempotent."""
        id1 = node_id_order("ORD-101")
        id2 = node_id_order("ORD-101")
        assert id1 == id2 == "rec:order:ORD-101"

        assert node_id_settlement("SETL-1") == "setl:SETL-1"
        assert node_id_finding("SETL-1") == "finding:SETL-1"
        assert node_id_proof("SETL-1", 0) == "proof:SETL-1:0"
        assert node_id_exception("EX-1") == "exc:EX-1"
        assert node_id_exposure("SETL-1") == "exp:SETL-1"
        assert node_id_materiality("P1", "v123") == "mat:P1:v123"
        assert node_id_verdict("P1") == "vdt:P1"
        assert node_id_blocker("HIGH_SEVERITY_EXCEPTION", "EX-1") == "blk:HIGH_SEVERITY_EXCEPTION:EX-1"

    def test_complete_7_stage_backward_chain(self) -> None:
        """Trace from Verdict back through all 7 stages to raw Financial Events."""
        o1 = _make_order("O-101", 100_000, Method.UPI, payment_id="pay_abc123")
        s1 = _make_settlement("S-101", 100_000, utr="UTR_S101")
        bc1 = _make_bank_credit("TXN-901", 100_000, utr="UTR_S101")
        f1 = _make_proven_finding("S-101", ("O-101",), 100_000)
        e1 = _make_exception("EX-101", "S-101", 5_000, 100_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)

        period = Period("P-2026-09", ("S-101",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000)
        judgements = {"S-101": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))}

        # Authoritative controller decision
        verdict = decide_period(
            period=period,
            findings=[f1],
            judgements=judgements,
            exceptions=[e1],
            materiality=mat,
            settlements=[s1],
        )

        exposure = assess_exposure(
            findings=[f1],
            exceptions=[e1],
            target_settlement_ids=("S-101",),
            settlements=[s1],
        )

        # Build lineage
        graph = build_lineage(
            period=period,
            verdict=verdict,
            findings=[f1],
            exceptions=[e1],
            exposure=exposure,
            materiality=mat,
            settlements=[s1],
            orders=[o1],
            bank_credits=[bc1],
        )

        assert isinstance(graph, FinancialLineageGraph)
        assert graph.period_id == "P-2026-09"

        # Trace backward from Verdict
        vdt_nid = node_id_verdict("P-2026-09")
        ancestors = graph.trace_backward(vdt_nid)
        stages_present = {n.stage for n in ancestors}

        # Assert all 7 stages are present in backward trace!
        assert LineageStage.VERDICT in stages_present
        assert LineageStage.MATERIALITY in stages_present
        assert LineageStage.EXPOSURE in stages_present
        assert LineageStage.FINDING_EXCEPTION in stages_present
        assert LineageStage.SETTLEMENT in stages_present
        assert LineageStage.NORMALIZED_RECORD in stages_present
        assert LineageStage.FINANCIAL_EVENT in stages_present

        # Verify specific nodes reached
        ancestor_ids = {n.node_id for n in ancestors}
        assert node_id_order("O-101") in ancestor_ids
        assert node_id_event("gateway_payment", "pay_abc123") in ancestor_ids
        assert node_id_settlement("S-101") in ancestor_ids
        assert node_id_finding("S-101") in ancestor_ids
        assert node_id_exposure("S-101") in ancestor_ids
        assert node_id_carry_forward("EX-101") in ancestor_ids

    def test_complete_forward_impact_trace(self) -> None:
        """Trace from an individual Order forward to its ultimate close impact."""
        o1 = _make_order("O-201", 200_000)
        s1 = _make_settlement("S-201", 200_000)
        f1 = _make_proven_finding("S-201", ("O-201",), 200_000)

        period = Period("P-FWD", ("S-201",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=10_000)

        verdict = decide_period(
            period=period,
            findings=[f1],
            judgements={"S-201": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))},
            exceptions=[],
            materiality=mat,
            settlements=[s1],
        )
        exposure = assess_exposure(findings=[f1], exceptions=[], target_settlement_ids=("S-201",), settlements=[s1])

        graph = build_lineage(
            period=period,
            verdict=verdict,
            findings=[f1],
            exceptions=[],
            exposure=exposure,
            materiality=mat,
            settlements=[s1],
            orders=[o1],
        )

        impact = graph.trace_order_impact("O-201")
        assert impact["order_id"] == "O-201"
        assert impact["reached_verdict"] is True
        assert impact["verdict_status"] == ReadinessDecision.READY_TO_CLOSE.value

        # Check forward descendants
        descendants = graph.trace_forward(node_id_order("O-201"))
        descendant_ids = {d.node_id for d in descendants}
        assert node_id_proof("S-201", 0) in descendant_ids
        assert node_id_finding("S-201") in descendant_ids
        assert node_id_verdict("P-FWD") in descendant_ids

    def test_many_to_one_and_one_to_many_cardinality(self) -> None:
        """Verify handling of many-to-one (bundle) and one-to-many (split exceptions)."""
        # Many-to-One: 3 orders compose 1 settlement
        o1 = _make_order("O-1", 50_000)
        o2 = _make_order("O-2", 30_000)
        o3 = _make_order("O-3", 20_000)
        s1 = _make_settlement("S-BUNDLE", 100_000)
        f1 = _make_proven_finding("S-BUNDLE", ("O-1", "O-2", "O-3"), 100_000)

        # One-to-Many: 1 settlement has 2 distinct exceptions
        e1 = _make_exception("EX-A", "S-BUNDLE", 3_000, 100_000, ReasonCode.TIMING_MISMATCH, Severity.LOW)
        e2 = _make_exception("EX-B", "S-BUNDLE", 4_000, 100_000, ReasonCode.REFUND_MISMATCH, Severity.LOW)

        period = Period("P-CARDINALITY", ("S-BUNDLE",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=10_000, ceiling_paise=10_000)

        verdict = decide_period(
            period=period,
            findings=[f1],
            judgements={"S-BUNDLE": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))},
            exceptions=[e1, e2],
            materiality=mat,
            settlements=[s1],
        )
        exposure = assess_exposure(findings=[f1], exceptions=[e1, e2], target_settlement_ids=("S-BUNDLE",), settlements=[s1])

        graph = build_lineage(
            period=period,
            verdict=verdict,
            findings=[f1],
            exceptions=[e1, e2],
            exposure=exposure,
            materiality=mat,
            settlements=[s1],
            orders=[o1, o2, o3],
        )

        proof_node = graph.get_node(node_id_proof("S-BUNDLE", 0))
        assert proof_node is not None

        # Many-to-one: Proof has 3 incoming order edges
        incoming_to_proof = graph.get_parents(node_id_proof("S-BUNDLE", 0))
        incoming_order_ids = {p.node_id for p in incoming_to_proof}
        assert node_id_order("O-1") in incoming_order_ids
        assert node_id_order("O-2") in incoming_order_ids
        assert node_id_order("O-3") in incoming_order_ids

        # One-to-many: Settlement has edges to both EX-A and EX-B
        setl_children = graph.get_children(node_id_settlement("S-BUNDLE"))
        child_ids = {c.node_id for c in setl_children}
        assert node_id_exception("EX-A") in child_ids
        assert node_id_exception("EX-B") in child_ids

    def test_no_fabricated_evidence_and_explicit_missing_record(self) -> None:
        """Prove that missing evidence is represented explicitly rather than fabricated."""
        s1 = _make_settlement("S-MISSING", 100_000)
        # Exception explicitly flags missing bank invoice
        e1 = _make_exception(
            eid="EX-MISSING-DOC",
            sid="S-MISSING",
            unexplained=25_000,
            total=100_000,
            reason=ReasonCode.MISSING_TRANSACTION,
            severity=Severity.MEDIUM,
            missing="Missing payment gateway invoice INV-2026-90",
        )

        period = Period("P-MISSING", ("S-MISSING",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        verdict = decide_period(
            period=period,
            findings=[],
            judgements={"S-MISSING": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))},
            exceptions=[e1],
            materiality=mat,
            settlements=[s1],
        )
        exposure = assess_exposure(findings=[], exceptions=[e1], target_settlement_ids=("S-MISSING",), settlements=[s1])

        graph = build_lineage(
            period=period,
            verdict=verdict,
            findings=[],
            exceptions=[e1],
            exposure=exposure,
            materiality=mat,
            settlements=[s1],
        )

        assert len(graph.missing_evidence) == 1
        rec = graph.missing_evidence[0]
        assert rec.expected_entity_type == "EvidenceReference"
        assert "INV-2026-90" in rec.reason
        assert rec.impact_paise == 25_000

        # Verify missing evidence node exists in graph
        missing_node = graph.get_node(rec.missing_id)
        assert missing_node is not None
        assert missing_node.stage is LineageStage.FINDING_EXCEPTION
        assert missing_node.entity_type == "MissingEvidence"
        assert missing_node.status == "EXPLICITLY_UNRESOLVED"

    def test_integrity_validation_and_broken_reference_detection(self) -> None:
        """Test validate_integrity() detects broken references and orphan exceptions."""
        s1 = _make_settlement("S-VALID", 100_000)
        period = Period("P-INTEGRITY", ("S-VALID",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=10_000)
        verdict = decide_period(period, [], {"S-VALID": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))}, [], mat, [s1])
        exposure = assess_exposure(findings=[], exceptions=[], target_settlement_ids=("S-VALID",), settlements=[s1])

        # 1. Clean graph should have 0 defects
        clean_graph = build_lineage(period, verdict, [], [], exposure, mat, [s1])
        assert clean_graph.validate_integrity() == ()

        # 2. Inject an edge pointing to a non-existent target
        broken_edge = LineageEdge(
            source_id=node_id_settlement("S-VALID"),
            target_id="setl:DOES_NOT_EXIST",
            relationship=EdgeRelationship.PROVEN_BY,
        )
        corrupted_graph = FinancialLineageGraph(
            period_id="P-INTEGRITY",
            verdict_node_id=clean_graph.verdict_node_id,
            nodes=clean_graph.nodes,
            edges=clean_graph.edges + (broken_edge,),
            missing_evidence=clean_graph.missing_evidence,
        )
        defects = corrupted_graph.validate_integrity()
        assert len(defects) >= 1
        assert any(d.defect_type == "BROKEN_TARGET_REFERENCE" for d in defects)

        # 3. Inject an orphan exception referencing an unknown settlement
        orphan_exc_node = LineageNode(
            node_id="exc:EX-ORPHAN",
            stage=LineageStage.FINDING_EXCEPTION,
            entity_type="Exception_",
            label="Orphan Exception",
            amount_paise=10_000,
            status="HIGH",
            metadata={"settlement_id": "SETL-UNKNOWN-999"},
        )
        nodes_with_orphan = dict(clean_graph.nodes)
        nodes_with_orphan["exc:EX-ORPHAN"] = orphan_exc_node
        orphan_graph = FinancialLineageGraph(
            period_id="P-INTEGRITY",
            verdict_node_id=clean_graph.verdict_node_id,
            nodes=nodes_with_orphan,
            edges=clean_graph.edges,
            missing_evidence=clean_graph.missing_evidence,
        )
        orphan_defects = orphan_graph.validate_integrity()
        assert any(d.defect_type == "ORPHAN_EXCEPTION" for d in orphan_defects)

    def test_explain_decision_narrative_generation(self) -> None:
        """Test explain_decision() human-readable narrative output."""
        s1 = _make_settlement("S-AUDIT", 500_000)
        e1 = _make_exception(
            eid="EX-DISPUTE",
            sid="S-AUDIT",
            unexplained=35_000,
            total=500_000,
            reason=ReasonCode.CHARGEBACK,
            severity=Severity.HIGH,
            missing="Chargeback notice from acquiring bank",
        )
        period = Period("FY26-Q2", ("S-AUDIT",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=1_000)

        verdict = decide_period(
            period=period,
            findings=[],
            judgements={"S-AUDIT": Judgement(Decision.BLOCK, None, None, ("chargeback dispute",))},
            exceptions=[e1],
            materiality=mat,
            settlements=[s1],
        )
        exposure = assess_exposure(findings=[], exceptions=[e1], target_settlement_ids=("S-AUDIT",), settlements=[s1])

        graph = build_lineage(
            period=period,
            verdict=verdict,
            findings=[],
            exceptions=[e1],
            exposure=exposure,
            materiality=mat,
            settlements=[s1],
        )

        narrative = graph.explain_decision()
        assert "CLOSEPILOT FINANCIAL LINEAGE AUDIT TRAIL — PERIOD FY26-Q2" in narrative
        assert "Close Verdict: BLOCKED" in narrative
        assert "Hard Blockers Triggered" in narrative
        assert "ECONOMIC MATERIALITY BOUNDS:" in narrative
        assert "FINANCIAL EXPOSURE ASSESSMENT:" in narrative
        assert "EXPLICIT MISSING EVIDENCE AUDIT:" in narrative
        assert "Chargeback notice from acquiring bank" in narrative

    def test_json_serialization(self) -> None:
        """Verify graph serialization to dictionary."""
        s1 = _make_settlement("S-JSON", 100_000)
        period = Period("P-JSON", ("S-JSON",), _TODAY, _TODAY)
        mat = MaterialityBound(threshold_bps=100, floor_paise=1_000, ceiling_paise=10_000)
        verdict = decide_period(period, [], {"S-JSON": Judgement(Decision.AUTO_POST, 0, 0.0, ("ok",))}, [], mat, [s1])
        exposure = assess_exposure(findings=[], exceptions=[], target_settlement_ids=("S-JSON",), settlements=[s1])

        graph = build_lineage(period, verdict, [], [], exposure, mat, [s1])
        data = graph.to_dict()

        assert data["period_id"] == "P-JSON"
        assert "nodes" in data
        assert "edges" in data
        assert "missing_evidence" in data
        assert data["total_nodes"] == len(data["nodes"])
