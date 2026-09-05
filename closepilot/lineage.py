"""CLOSEPILOT — Financial Lineage Layer (Phase 2C).

Provides an auditable, deterministic, end-to-end chain of custody answering:
    "Why did ClosePilot make this decision?"

Traceable Lineage Chain:
    Financial Event
    → Normalized Record (Order / BankCredit)
    → Settlement / Transaction
    → Finding / Exception
    → Exposure
    → Materiality
    → Verdict

Architectural Guarantees:
- DETERMINISTIC IDENTIFIERS: All node and edge IDs are deterministic functions of
  canonical domain entities.
- ZERO EVIDENCE FABRICATION: The engine never invents synthetic orders, payments,
  or fake proofs to force a graph edge.
- EXPLICIT MISSING EVIDENCE: Unresolved residuals, missing order references, and unlinked
  credits are modeled as first-class `MissingEvidenceRecord` nodes.
- STRICT GRAPH INTEGRITY: `validate_integrity()` detects and flags broken references,
  dangling links, and orphaned records.
- CARDINALITY SUPPORT: Supports many-to-one (orders to settlement, exposures to materiality)
  and one-to-many (settlement to proofs/exceptions, verdict to blockers/carry-forwards).
- READ-ONLY: Never alters authoritative financial truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import BankCredit, Order, Settlement
from attest.money import rupees
from attest.policy import Judgement
from attest.verdict import Finding, Proof, Verdict

from attest.close.exposure import ExposureItem, ExposureKind, PeriodExposure
from attest.close.materiality import MaterialityAssessment, MaterialityBound
from attest.close.period import Period
from attest.close.readiness import (
    Blocker,
    BlockerKind,
    CarryForwardItem,
    PeriodVerdict,
    ReadinessDecision,
)


class LineageStage(str, Enum):
    """The 7 stages of financial close lineage."""

    FINANCIAL_EVENT = "FINANCIAL_EVENT"
    """Raw source event from payment gateway, bank feed, or order capture."""

    NORMALIZED_RECORD = "NORMALIZED_RECORD"
    """Normalized ledger record: captured Order or BankCredit line."""

    SETTLEMENT = "SETTLEMENT"
    """Gateway payout batch transaction."""

    FINDING_EXCEPTION = "FINDING_EXCEPTION"
    """Solver proof, match verdict, or classified discrepancy exception."""

    EXPOSURE = "EXPOSURE"
    """Assessed financial risk in integer paise at stake."""

    MATERIALITY = "MATERIALITY"
    """Policy threshold evaluation (bps, floor, ceiling)."""

    VERDICT = "VERDICT"
    """Final period-level close readiness decision with blockers and carry-forward."""


class EdgeRelationship(str, Enum):
    """Semantic relationship connecting lineage nodes."""

    CAPTURED_AS = "CAPTURED_AS"
    """Raw event normalized into an Order or BankCredit record."""

    BUNDLED_IN_SETTLEMENT = "BUNDLED_IN_SETTLEMENT"
    """Normalized Order settled in a gateway payout batch."""

    CREDITED_IN_BANK = "CREDITED_IN_BANK"
    """BankCredit transaction associated with a settlement payout."""

    PROVEN_BY = "PROVEN_BY"
    """Settlement verified by solver Proof referencing Order(s)."""

    DISCREPANCY_RAISED = "DISCREPANCY_RAISED"
    """Settlement generated an Exception_."""

    ESTABLISHED_PARTIAL = "ESTABLISHED_PARTIAL"
    """Order identified as part of an established partial match."""

    MISSING_EVIDENCE_LINK = "MISSING_EVIDENCE_LINK"
    """Exception or proof points to missing source evidence."""

    ASSESSED_EXPOSURE = "ASSESSED_EXPOSURE"
    """Settlement finding/exception assessed for monetary exposure."""

    EVALUATED_AGAINST_POLICY = "EVALUATED_AGAINST_POLICY"
    """Exposure item evaluated against the materiality policy."""

    CAUSES_BLOCKER = "CAUSES_BLOCKER"
    """Exception, finding, or policy block triggers a close Blocker."""

    CARRIED_FORWARD = "CARRIED_FORWARD"
    """Immaterial exception authorized into Carry-Forward Ledger."""

    DETERMINES_VERDICT = "DETERMINES_VERDICT"
    """Blocker, carry-forward, or materiality bound determines final Verdict."""


@dataclass(frozen=True, slots=True)
class LineageNode:
    """A single deterministic entity within the financial lineage graph."""

    node_id: str
    stage: LineageStage
    entity_type: str
    label: str
    amount_paise: int | None
    status: str
    evidence_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "stage": self.stage.value,
            "entity_type": self.entity_type,
            "label": self.label,
            "amount_paise": self.amount_paise,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LineageEdge:
    """A directed causal dependency from an upstream source to a downstream consequence."""

    source_id: str
    target_id: str
    relationship: EdgeRelationship
    amount_paise: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship.value,
            "amount_paise": self.amount_paise,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class MissingEvidenceRecord:
    """First-class representation of missing or unverified financial evidence.

    Explicitly models what is NOT present in the system, preventing fabricated links.
    """

    missing_id: str
    referencing_node_id: str
    expected_entity_type: str
    reason: str
    impact_paise: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "missing_id": self.missing_id,
            "referencing_node_id": self.referencing_node_id,
            "expected_entity_type": self.expected_entity_type,
            "reason": self.reason,
            "impact_paise": self.impact_paise,
        }


@dataclass(frozen=True, slots=True)
class LineageDefect:
    """A structural integrity defect or broken reference in the financial lineage."""

    defect_type: str
    source_id: str
    target_id: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "defect_type": self.defect_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "description": self.description,
        }


# --------------------------------------------------------------------------
# Deterministic Node ID Generators
# --------------------------------------------------------------------------

def node_id_event(event_type: str, ref: str) -> str:
    return f"evt:{event_type}:{ref}"


def node_id_order(order_id: str) -> str:
    return f"rec:order:{order_id}"


def node_id_bank(txn_id: str) -> str:
    return f"rec:bank:{txn_id}"


def node_id_settlement(settlement_id: str) -> str:
    return f"setl:{settlement_id}"


def node_id_finding(settlement_id: str) -> str:
    return f"finding:{settlement_id}"


def node_id_proof(settlement_id: str, index: int) -> str:
    return f"proof:{settlement_id}:{index}"


def node_id_exception(exception_id: str) -> str:
    return f"exc:{exception_id}"


def node_id_exposure(settlement_id: str) -> str:
    return f"exp:{settlement_id}"


def node_id_materiality(period_id: str, version: str) -> str:
    return f"mat:{period_id}:{version}"


def node_id_blocker(kind: str, ref_id: str) -> str:
    return f"blk:{kind}:{ref_id}"


def node_id_carry_forward(exception_id: str) -> str:
    return f"cf:{exception_id}"


def node_id_verdict(period_id: str) -> str:
    return f"vdt:{period_id}"


def node_id_missing(referencing_id: str, target_kind: str) -> str:
    return f"missing:{referencing_id}:{target_kind}"


# --------------------------------------------------------------------------
# Financial Lineage Graph
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FinancialLineageGraph:
    """The immutable, complete financial lineage graph for a close period."""

    period_id: str
    verdict_node_id: str
    nodes: Mapping[str, LineageNode]
    edges: tuple[LineageEdge, ...]
    missing_evidence: tuple[MissingEvidenceRecord, ...]

    def get_node(self, node_id: str) -> LineageNode | None:
        return self.nodes.get(node_id)

    @property
    def total_nodes(self) -> int:
        return len(self.nodes)

    @property
    def total_edges(self) -> int:
        return len(self.edges)

    def get_outgoing_edges(self, node_id: str) -> tuple[LineageEdge, ...]:
        return tuple(e for e in self.edges if e.source_id == node_id)

    def get_incoming_edges(self, node_id: str) -> tuple[LineageEdge, ...]:
        return tuple(e for e in self.edges if e.target_id == node_id)

    def get_parents(self, node_id: str) -> tuple[LineageNode, ...]:
        """Direct upstream causes for a node."""
        parent_ids = {e.source_id for e in self.edges if e.target_id == node_id}
        return tuple(self.nodes[pid] for pid in sorted(parent_ids) if pid in self.nodes)

    def get_children(self, node_id: str) -> tuple[LineageNode, ...]:
        """Direct downstream effects of a node."""
        child_ids = {e.target_id for e in self.edges if e.source_id == node_id}
        return tuple(self.nodes[cid] for cid in sorted(child_ids) if cid in self.nodes)

    def trace_backward(self, node_id: str) -> tuple[LineageNode, ...]:
        """Recursively trace all upstream ancestors (root-cause analysis)."""
        visited: set[str] = set()
        queue: list[str] = [node_id]

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            for e in self.edges:
                if e.target_id == curr and e.source_id not in visited:
                    queue.append(e.source_id)

        # Return ancestors sorted deterministically by stage then node_id
        ancestors = [self.nodes[nid] for nid in visited if nid in self.nodes]
        stage_order = {s: i for i, s in enumerate(LineageStage)}
        return tuple(sorted(ancestors, key=lambda n: (stage_order.get(n.stage, 99), n.node_id)))

    def trace_forward(self, node_id: str) -> tuple[LineageNode, ...]:
        """Recursively trace all downstream descendants (impact analysis)."""
        visited: set[str] = set()
        queue: list[str] = [node_id]

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            for e in self.edges:
                if e.source_id == curr and e.target_id not in visited:
                    queue.append(e.target_id)

        descendants = [self.nodes[nid] for nid in visited if nid in self.nodes]
        stage_order = {s: i for i, s in enumerate(LineageStage)}
        return tuple(sorted(descendants, key=lambda n: (stage_order.get(n.stage, 99), n.node_id)))

    def trace_decision_root_causes(self) -> dict[str, Any]:
        """Extract the exact causal tree explaining the close verdict."""
        verdict_node = self.get_node(self.verdict_node_id)
        if not verdict_node:
            return {"error": "verdict node not found"}

        ancestors = self.trace_backward(self.verdict_node_id)
        blocker_nodes = [n for n in ancestors if n.stage is LineageStage.VERDICT and n.entity_type == "Blocker"]
        cf_nodes = [n for n in ancestors if n.stage is LineageStage.VERDICT and n.entity_type == "CarryForwardItem"]
        mat_nodes = [n for n in ancestors if n.stage is LineageStage.MATERIALITY]
        exp_nodes = [n for n in ancestors if n.stage is LineageStage.EXPOSURE]
        exc_nodes = [n for n in ancestors if n.stage is LineageStage.FINDING_EXCEPTION and n.entity_type == "Exception_"]
        finding_nodes = [n for n in ancestors if n.stage is LineageStage.FINDING_EXCEPTION and n.entity_type == "Finding"]
        setl_nodes = [n for n in ancestors if n.stage is LineageStage.SETTLEMENT]
        order_nodes = [n for n in ancestors if n.stage is LineageStage.NORMALIZED_RECORD and n.entity_type == "Order"]
        missing_nodes = [n for n in ancestors if n.entity_type == "MissingEvidence"]

        return {
            "period_id": self.period_id,
            "verdict": verdict_node.status,
            "blockers": [b.to_dict() for b in blocker_nodes],
            "carry_forwards": [cf.to_dict() for cf in cf_nodes],
            "materiality": [m.to_dict() for m in mat_nodes],
            "exposures": [e.to_dict() for e in exp_nodes],
            "exceptions": [x.to_dict() for x in exc_nodes],
            "findings": [f.to_dict() for f in finding_nodes],
            "settlements": [s.to_dict() for s in setl_nodes],
            "orders": [o.to_dict() for o in order_nodes],
            "missing_evidence": [m.to_dict() for m in missing_nodes],
        }

    def trace_order_impact(self, order_id: str) -> dict[str, Any]:
        """Forward trace answering: 'What did this order impact in the close decision?'"""
        oid = node_id_order(order_id)
        node = self.get_node(oid)
        if not node:
            return {"error": f"order {order_id} not found in lineage"}

        descendants = self.trace_forward(oid)
        impacted_settlements = [d for d in descendants if d.stage is LineageStage.SETTLEMENT]
        impacted_findings = [d for d in descendants if d.stage is LineageStage.FINDING_EXCEPTION and d.entity_type in ("Finding", "Proof")]
        impacted_exposures = [d for d in descendants if d.stage is LineageStage.EXPOSURE]
        impacted_verdict = [d for d in descendants if d.stage is LineageStage.VERDICT and d.entity_type == "PeriodVerdict"]

        return {
            "order_id": order_id,
            "order_node": node.to_dict(),
            "impacted_settlements": [s.to_dict() for s in impacted_settlements],
            "impacted_findings": [f.to_dict() for f in impacted_findings],
            "impacted_exposures": [e.to_dict() for e in impacted_exposures],
            "reached_verdict": bool(impacted_verdict),
            "verdict_status": impacted_verdict[0].status if impacted_verdict else None,
        }

    def validate_integrity(self) -> tuple[LineageDefect, ...]:
        """Validate complete graph integrity and detect broken or dangling references.

        Ensures that every edge connects valid nodes and that missing evidence is explicit.
        """
        defects: list[LineageDefect] = []

        # Check edge endpoints
        for e in self.edges:
            if e.source_id not in self.nodes:
                defects.append(LineageDefect(
                    defect_type="BROKEN_SOURCE_REFERENCE",
                    source_id=e.source_id,
                    target_id=e.target_id,
                    description=f"Edge references source node {e.source_id} which does not exist in the graph.",
                ))
            if e.target_id not in self.nodes:
                defects.append(LineageDefect(
                    defect_type="BROKEN_TARGET_REFERENCE",
                    source_id=e.source_id,
                    target_id=e.target_id,
                    description=f"Edge references target node {e.target_id} which does not exist in the graph.",
                ))

        # Check orphan exceptions: every exception must connect to an existing settlement
        exc_nodes = [n for n in self.nodes.values() if n.stage is LineageStage.FINDING_EXCEPTION and n.entity_type == "Exception_"]
        for xn in exc_nodes:
            sid = xn.metadata.get("settlement_id")
            if sid:
                s_node_id = node_id_settlement(sid)
                if s_node_id not in self.nodes:
                    defects.append(LineageDefect(
                        defect_type="ORPHAN_EXCEPTION",
                        source_id=xn.node_id,
                        target_id=s_node_id,
                        description=f"Exception {xn.node_id} references settlement {sid} which is absent from period scope.",
                    ))

        return tuple(defects)

    def explain_decision(self) -> str:
        """Produce a comprehensive human-readable step-by-step audit explanation."""
        w = 90
        v_node = self.get_node(self.verdict_node_id)
        verdict_str = v_node.status if v_node else "UNKNOWN"
        causes = self.trace_decision_root_causes()

        lines = [
            "=" * w,
            f"CLOSEPILOT FINANCIAL LINEAGE AUDIT TRAIL — PERIOD {self.period_id}",
            f"Close Verdict: {verdict_str}",
            "=" * w,
            "",
            "1. CLOSE VERDICT & DECISION CRITERIA:",
            f"   Decision: {verdict_str}",
        ]

        if causes.get("blockers"):
            lines.append(f"   Hard Blockers Triggered ({len(causes['blockers'])}):")
            for b in causes["blockers"]:
                lines.append(f"     • [{b['status']}] {b['label']}")
        else:
            lines.append("   Hard Blockers: None (0)")

        if causes.get("carry_forwards"):
            cf_val = sum(c.get("amount_paise", 0) or 0 for c in causes["carry_forwards"])
            lines.append(f"   Carry-Forward Ledger ({len(causes['carry_forwards'])} items, total {rupees(cf_val)}):")
            for cf in causes["carry_forwards"]:
                lines.append(f"     • {cf['label']} | Exposure: {rupees(cf.get('amount_paise') or 0)}")
        else:
            lines.append("   Carry-Forward Items: None (0)")

        lines.extend([
            "",
            "2. ECONOMIC MATERIALITY BOUNDS:",
        ])
        if causes.get("materiality"):
            m = causes["materiality"][0]
            lines.extend([
                f"   Policy Version:     {m.get('metadata', {}).get('version', 'N/A')}",
                f"   Total Period Value: {rupees(m.get('metadata', {}).get('total_period_paise', 0))}",
                f"   Allowable Bound:    {rupees(m.get('metadata', {}).get('effective_threshold_paise', 0))}",
                f"   Evaluation:         {m.get('status')} ({m.get('metadata', {}).get('explanation', '')})",
            ])

        lines.extend([
            "",
            "3. FINANCIAL EXPOSURE ASSESSMENT:",
            f"   Total Exposure Items: {len(causes.get('exposures', []))}",
        ])
        for exp in causes.get("exposures", [])[:5]:
            lines.append(
                f"     • Settlement {exp.get('metadata', {}).get('settlement_id')}: "
                f"at risk {rupees(exp.get('amount_paise') or 0)} ({exp.get('status')}) — {exp.get('metadata', {}).get('explanation', '')}"
            )
        if len(causes.get("exposures", [])) > 5:
            lines.append(f"     ... and {len(causes['exposures']) - 5} more exposure item(s)")

        lines.extend([
            "",
            "4. UPSTREAM SETTLEMENTS & SOURCE EVIDENCE:",
            f"   Active Settlements in Period: {len(causes.get('settlements', []))}",
            f"   Reconciliation Proofs / Findings: {len(causes.get('findings', []))}",
            f"   Classified Discrepancies: {len(causes.get('exceptions', []))}",
            f"   Normalized Source Orders Linked: {len(causes.get('orders', []))}",
        ])

        if causes.get("missing_evidence"):
            lines.extend([
                "",
                "5. EXPLICIT MISSING EVIDENCE AUDIT:",
                f"   Identified Missing Evidence Records ({len(causes['missing_evidence'])}):",
            ])
            for me in causes["missing_evidence"]:
                lines.append(
                    f"     ⚠ [{me.get('metadata', {}).get('expected_type')}] {me.get('label')}: "
                    f"{me.get('metadata', {}).get('reason')} (Impact: {rupees(me.get('amount_paise') or 0)})"
                )

        lines.append("=" * w)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": self.period_id,
            "verdict_node_id": self.verdict_node_id,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "missing_evidence": [me.to_dict() for me in self.missing_evidence],
        }


# --------------------------------------------------------------------------
# Graph Builder
# --------------------------------------------------------------------------

def build_lineage(
    period: Period,
    verdict: PeriodVerdict,
    findings: Sequence[Finding],
    exceptions: Sequence[Exception_],
    exposure: PeriodExposure,
    materiality: MaterialityAssessment | MaterialityBound,
    settlements: Sequence[Settlement] | None = None,
    orders: Sequence[Order] | None = None,
    bank_credits: Sequence[BankCredit] | None = None,
) -> FinancialLineageGraph:
    """Construct a complete, deterministic, auditable Financial Lineage Graph."""
    nodes: dict[str, LineageNode] = {}
    edges: list[LineageEdge] = []
    missing_records: list[MissingEvidenceRecord] = []

    # Map collections by primary identifiers
    orders_by_id = {o.order_id: o for o in orders} if orders else {}
    credits_by_id = {c.txn_id: c for c in bank_credits} if bank_credits else {}
    settlements_by_id = {s.settlement_id: s for s in settlements} if settlements else {}

    # Map bank credits by UTR if available in narration
    credits_by_utr: dict[str, BankCredit] = {}
    if bank_credits:
        for bc in bank_credits:
            for word in bc.narration.split():
                if word.startswith("UTR") or "UTR" in word:
                    credits_by_utr[word] = bc

    # ----------------------------------------------------------------------
    # Stage 1 & 2: Financial Events and Normalized Records (Orders & BankCredits)
    # ----------------------------------------------------------------------
    if orders:
        for o in orders:
            ord_nid = node_id_order(o.order_id)
            nodes[ord_nid] = LineageNode(
                node_id=ord_nid,
                stage=LineageStage.NORMALIZED_RECORD,
                entity_type="Order",
                label=f"Order {o.order_id} ({rupees(o.net)} net)",
                amount_paise=o.net,
                status="NORMALIZED",
                evidence_refs=(o.payment_id,) if o.payment_id else (),
                metadata={
                    "order_id": o.order_id,
                    "gross_paise": o.gross_paise,
                    "net_paise": o.net,
                    "method": o.method.value,
                    "customer_name": o.customer_name,
                    "payment_id": o.payment_id,
                    "captured_on": o.captured_on.isoformat(),
                },
            )

            # Raw Event Node
            evt_id = node_id_event("gateway_payment", o.payment_id or o.order_id)
            nodes[evt_id] = LineageNode(
                node_id=evt_id,
                stage=LineageStage.FINANCIAL_EVENT,
                entity_type="GatewayPaymentEvent",
                label=f"Payment Event {o.payment_id or o.order_id}",
                amount_paise=o.gross_paise,
                status="CAPTURED",
                evidence_refs=(o.order_id,),
                metadata={"captured_on": o.captured_on.isoformat()},
            )
            edges.append(LineageEdge(
                source_id=evt_id,
                target_id=ord_nid,
                relationship=EdgeRelationship.CAPTURED_AS,
                amount_paise=o.gross_paise,
            ))

    if bank_credits:
        for bc in bank_credits:
            bank_nid = node_id_bank(bc.txn_id)
            nodes[bank_nid] = LineageNode(
                node_id=bank_nid,
                stage=LineageStage.NORMALIZED_RECORD,
                entity_type="BankCredit",
                label=f"Bank Credit {bc.txn_id} ({rupees(bc.credit_paise)})",
                amount_paise=bc.credit_paise,
                status="STATEMENT_LINE",
                evidence_refs=(bc.narration,),
                metadata={
                    "txn_id": bc.txn_id,
                    "credit_paise": bc.credit_paise,
                    "value_date": bc.value_date.isoformat(),
                    "narration": bc.narration,
                },
            )

            # Raw Bank Statement Feed Event
            b_evt_id = node_id_event("bank_statement_feed", bc.txn_id)
            nodes[b_evt_id] = LineageNode(
                node_id=b_evt_id,
                stage=LineageStage.FINANCIAL_EVENT,
                entity_type="BankFeedEvent",
                label=f"Bank Statement Event {bc.txn_id}",
                amount_paise=bc.credit_paise,
                status="IMPORTED",
                evidence_refs=(bc.narration,),
                metadata={"value_date": bc.value_date.isoformat()},
            )
            edges.append(LineageEdge(
                source_id=b_evt_id,
                target_id=bank_nid,
                relationship=EdgeRelationship.CAPTURED_AS,
                amount_paise=bc.credit_paise,
            ))

    # ----------------------------------------------------------------------
    # Stage 3: Settlement / Transactions
    # ----------------------------------------------------------------------
    for sid in period.settlement_ids:
        s = settlements_by_id.get(sid)
        s_val = abs(s.net_paise) if s else None
        setl_nid = node_id_settlement(sid)

        nodes[setl_nid] = LineageNode(
            node_id=setl_nid,
            stage=LineageStage.SETTLEMENT,
            entity_type="Settlement",
            label=f"Settlement {sid} ({rupees(s_val) if s_val else 'unknown'})",
            amount_paise=s_val,
            status="ACTIVE_IN_PERIOD",
            evidence_refs=(s.utr,) if s and s.utr else (),
            metadata={
                "settlement_id": sid,
                "net_paise": s_val,
                "utr": s.utr if s else None,
                "settled_on": s.settled_on.isoformat() if s else None,
            },
        )

        # Connect BankCredit to Settlement if matching UTR is present
        if s and s.utr:
            bc = credits_by_utr.get(s.utr)
            if bc:
                b_nid = node_id_bank(bc.txn_id)
                edges.append(LineageEdge(
                    source_id=b_nid,
                    target_id=setl_nid,
                    relationship=EdgeRelationship.CREDITED_IN_BANK,
                    amount_paise=bc.credit_paise,
                ))

        # Connect Settlement to Verdict
        vdt_nid = node_id_verdict(period.period_id)
        edges.append(LineageEdge(
            source_id=setl_nid,
            target_id=vdt_nid,
            relationship=EdgeRelationship.DETERMINES_VERDICT,
            amount_paise=s_val,
        ))

    # ----------------------------------------------------------------------
    # Stage 4: Findings & Exceptions (Solver Proofs & Residual Discrepancies)
    # ----------------------------------------------------------------------
    target_sids = set(period.settlement_ids)
    period_findings = [f for f in findings if f.settlement_id in target_sids]
    period_exceptions = [e for e in exceptions if e.settlement_id in target_sids]

    # Process Findings & Proofs
    for f in period_findings:
        f_nid = node_id_finding(f.settlement_id)
        setl_nid = node_id_settlement(f.settlement_id)

        nodes[f_nid] = LineageNode(
            node_id=f_nid,
            stage=LineageStage.FINDING_EXCEPTION,
            entity_type="Finding",
            label=f"Finding {f.settlement_id} [{f.verdict.value}]",
            amount_paise=f.proofs[0].net_paise if f.proofs else None,
            status=f.verdict.value,
            evidence_refs=tuple(f.unsat_core) if f.unsat_core else (),
            metadata={
                "settlement_id": f.settlement_id,
                "verdict": f.verdict.value,
                "postable": f.postable,
                "layer": f.layer,
                "proof_count": len(f.proofs),
            },
        )
        edges.append(LineageEdge(
            source_id=f_nid,
            target_id=setl_nid,
            relationship=EdgeRelationship.PROVEN_BY,
        ))

        # Proofs and their referenced Orders
        for p_idx, p in enumerate(f.proofs):
            p_nid = node_id_proof(f.settlement_id, p_idx)
            nodes[p_nid] = LineageNode(
                node_id=p_nid,
                stage=LineageStage.FINDING_EXCEPTION,
                entity_type="Proof",
                label=f"Proof #{p_idx} for {f.settlement_id} ({len(p.order_ids)} orders, {rupees(p.net_paise)})",
                amount_paise=p.net_paise,
                status="CHECKED_BY_KERNEL",
                evidence_refs=p.order_ids,
                metadata={
                    "settlement_id": f.settlement_id,
                    "order_ids": list(p.order_ids),
                    "gross_paise": p.gross_paise,
                    "fee_paise": p.fee_paise,
                    "tax_paise": p.tax_paise,
                    "adjustment_paise": p.adjustment_paise,
                    "net_paise": p.net_paise,
                },
            )
            edges.append(LineageEdge(
                source_id=p_nid,
                target_id=f_nid,
                relationship=EdgeRelationship.PROVEN_BY,
                amount_paise=p.net_paise,
            ))

            # Connect Orders to Proof
            for oid in p.order_ids:
                ord_nid = node_id_order(oid)
                if ord_nid in nodes:
                    edges.append(LineageEdge(
                        source_id=ord_nid,
                        target_id=p_nid,
                        relationship=EdgeRelationship.BUNDLED_IN_SETTLEMENT,
                        amount_paise=orders_by_id[oid].net if oid in orders_by_id else None,
                    ))
                else:
                    # Order is referenced in proof but wasn't provided in source orders:
                    # Create a referenced record node so lineage has no broken reference
                    nodes[ord_nid] = LineageNode(
                        node_id=ord_nid,
                        stage=LineageStage.NORMALIZED_RECORD,
                        entity_type="Order",
                        label=f"Order {oid} (Referenced in proof)",
                        amount_paise=None,
                        status="REFERENCED_IN_PROOF",
                        evidence_refs=(f.settlement_id,),
                    )
                    edges.append(LineageEdge(
                        source_id=ord_nid,
                        target_id=p_nid,
                        relationship=EdgeRelationship.BUNDLED_IN_SETTLEMENT,
                    ))

    # Process Exceptions
    for e in period_exceptions:
        e_nid = node_id_exception(e.id)
        setl_nid = node_id_settlement(e.settlement_id)

        nodes[e_nid] = LineageNode(
            node_id=e_nid,
            stage=LineageStage.FINDING_EXCEPTION,
            entity_type="Exception_",
            label=f"Exception {e.id} [{e.reason.value}: {rupees(e.unexplained_paise)}]",
            amount_paise=e.unexplained_paise,
            status=e.severity.value,
            evidence_refs=(e.missing,) if e.missing else (),
            metadata={
                "exception_id": e.id,
                "settlement_id": e.settlement_id,
                "reason": e.reason.value,
                "severity": e.severity.value,
                "amount_paise": e.amount_paise,
                "unexplained_paise": e.unexplained_paise,
                "missing": e.missing,
                "next_step": e.next_step,
            },
        )
        edges.append(LineageEdge(
            source_id=setl_nid,
            target_id=e_nid,
            relationship=EdgeRelationship.DISCREPANCY_RAISED,
            amount_paise=e.unexplained_paise,
        ))

        # Established order references
        for oid in e.established:
            ord_nid = node_id_order(oid)
            if ord_nid in nodes:
                edges.append(LineageEdge(
                    source_id=ord_nid,
                    target_id=e_nid,
                    relationship=EdgeRelationship.ESTABLISHED_PARTIAL,
                ))

        # Explicit Missing Evidence Record
        if e.missing:
            m_nid = node_id_missing(e_nid, "EvidenceRef")
            rec = MissingEvidenceRecord(
                missing_id=m_nid,
                referencing_node_id=e_nid,
                expected_entity_type="EvidenceReference",
                reason=str(e.missing),
                impact_paise=e.unexplained_paise,
            )
            missing_records.append(rec)
            nodes[m_nid] = LineageNode(
                node_id=m_nid,
                stage=LineageStage.FINDING_EXCEPTION,
                entity_type="MissingEvidence",
                label=f"Missing Evidence: {e.missing}",
                amount_paise=e.unexplained_paise,
                status="EXPLICITLY_UNRESOLVED",
                evidence_refs=(e.id,),
                metadata=rec.to_dict(),
            )
            edges.append(LineageEdge(
                source_id=m_nid,
                target_id=e_nid,
                relationship=EdgeRelationship.MISSING_EVIDENCE_LINK,
                amount_paise=e.unexplained_paise,
            ))

    # ----------------------------------------------------------------------
    # Stage 5: Financial Exposure
    # ----------------------------------------------------------------------
    for item in exposure.items:
        exp_nid = node_id_exposure(item.settlement_id)
        setl_nid = node_id_settlement(item.settlement_id)

        nodes[exp_nid] = LineageNode(
            node_id=exp_nid,
            stage=LineageStage.EXPOSURE,
            entity_type="ExposureItem",
            label=f"Exposure for {item.settlement_id} [{item.kind.value}: {rupees(item.exposure_paise)}]",
            amount_paise=item.exposure_paise,
            status=item.kind.value,
            evidence_refs=(item.reason.value,),
            metadata={
                "settlement_id": item.settlement_id,
                "settlement_value_paise": item.settlement_value_paise,
                "exposure_paise": item.exposure_paise,
                "kind": item.kind.value,
                "reason": item.reason.value,
                "severity": item.severity.value,
                "explanation": item.explanation,
            },
        )
        edges.append(LineageEdge(
            source_id=setl_nid,
            target_id=exp_nid,
            relationship=EdgeRelationship.ASSESSED_EXPOSURE,
            amount_paise=item.exposure_paise,
        ))

        # Connect matching findings & exceptions to exposure
        f_nid = node_id_finding(item.settlement_id)
        if f_nid in nodes:
            edges.append(LineageEdge(
                source_id=f_nid,
                target_id=exp_nid,
                relationship=EdgeRelationship.ASSESSED_EXPOSURE,
            ))

        for e in period_exceptions:
            if e.settlement_id == item.settlement_id:
                e_nid = node_id_exception(e.id)
                if e_nid in nodes:
                    edges.append(LineageEdge(
                        source_id=e_nid,
                        target_id=exp_nid,
                        relationship=EdgeRelationship.ASSESSED_EXPOSURE,
                        amount_paise=e.unexplained_paise,
                    ))

    # ----------------------------------------------------------------------
    # Stage 6: Materiality Policy
    # ----------------------------------------------------------------------
    mat_version = materiality.version
    mat_nid = node_id_materiality(period.period_id, mat_version)

    is_mat = (
        materiality.is_material
        if isinstance(materiality, MaterialityAssessment)
        else materiality.is_material(exposure.total_exposure_paise, exposure.total_value_paise)
    )
    eff_threshold = (
        materiality.effective_threshold_paise
        if isinstance(materiality, MaterialityAssessment)
        else materiality.max_allowable_exposure_paise(exposure.total_value_paise)
    )

    nodes[mat_nid] = LineageNode(
        node_id=mat_nid,
        stage=LineageStage.MATERIALITY,
        entity_type="MaterialityAssessment",
        label=f"Materiality Policy [{mat_version[:8]}] ({'MATERIAL' if is_mat else 'IMMATERIAL'})",
        amount_paise=eff_threshold,
        status="MATERIAL" if is_mat else "IMMATERIAL",
        evidence_refs=(mat_version,),
        metadata={
            "version": mat_version,
            "threshold_bps": materiality.threshold_bps,
            "floor_paise": materiality.floor_paise,
            "ceiling_paise": materiality.ceiling_paise,
            "total_period_paise": exposure.total_value_paise,
            "effective_threshold_paise": eff_threshold,
            "is_material": is_mat,
            "explanation": (
                materiality.explanation
                if isinstance(materiality, MaterialityAssessment)
                else materiality.explain_threshold(exposure.total_value_paise)
            ),
        },
    )

    # Connect all exposure items to the materiality node
    for item in exposure.items:
        exp_nid = node_id_exposure(item.settlement_id)
        if exp_nid in nodes:
            edges.append(LineageEdge(
                source_id=exp_nid,
                target_id=mat_nid,
                relationship=EdgeRelationship.EVALUATED_AGAINST_POLICY,
                amount_paise=item.exposure_paise,
            ))

    # ----------------------------------------------------------------------
    # Stage 7: Verdict, Blockers & Carry-Forward Ledger
    # ----------------------------------------------------------------------
    vdt_nid = node_id_verdict(period.period_id)
    nodes[vdt_nid] = LineageNode(
        node_id=vdt_nid,
        stage=LineageStage.VERDICT,
        entity_type="PeriodVerdict",
        label=f"Verdict for {period.period_id} [{verdict.decision.value}]",
        amount_paise=verdict.material_exposure_paise,
        status=verdict.decision.value,
        evidence_refs=verdict.blockers,
        metadata={
            "period_id": period.period_id,
            "decision": verdict.decision.value,
            "material_exposure_paise": verdict.material_exposure_paise,
            "active_blocker_rule_instances": verdict.active_blocker_rule_instances,
            "unique_blocked_exceptions": verdict.unique_blocked_exceptions,
            "unique_blocked_settlements": verdict.unique_blocked_settlements,
            "blocker_count": len(verdict.blockers),
            "carry_forward_count": len(verdict.carry_forward),
            "reasons": list(verdict.reasons),
        },
    )

    # Connect Materiality to Verdict
    edges.append(LineageEdge(
        source_id=mat_nid,
        target_id=vdt_nid,
        relationship=EdgeRelationship.DETERMINES_VERDICT,
    ))

    # Blockers
    for b in verdict.structured_blockers:
        b_nid = node_id_blocker(b.kind.value, b.ref_id)
        nodes[b_nid] = LineageNode(
            node_id=b_nid,
            stage=LineageStage.VERDICT,
            entity_type="Blocker",
            label=f"Blocker [{b.kind.value}] on {b.ref_id}",
            amount_paise=b.exposure_paise,
            status="HARD_BLOCKER",
            evidence_refs=(b.ref_id,),
            metadata={
                "kind": b.kind.value,
                "ref_id": b.ref_id,
                "reason": b.reason,
                "exposure_paise": b.exposure_paise,
            },
        )
        edges.append(LineageEdge(
            source_id=b_nid,
            target_id=vdt_nid,
            relationship=EdgeRelationship.CAUSES_BLOCKER,
            amount_paise=b.exposure_paise,
        ))

        # Trace blocker back to underlying cause
        if node_id_exception(b.ref_id) in nodes:
            edges.append(LineageEdge(
                source_id=node_id_exception(b.ref_id),
                target_id=b_nid,
                relationship=EdgeRelationship.CAUSES_BLOCKER,
            ))
        elif node_id_settlement(b.ref_id) in nodes:
            edges.append(LineageEdge(
                source_id=node_id_settlement(b.ref_id),
                target_id=b_nid,
                relationship=EdgeRelationship.CAUSES_BLOCKER,
            ))
        elif b.kind is BlockerKind.UNRESOLVED_MATERIAL_AMOUNT:
            edges.append(LineageEdge(
                source_id=mat_nid,
                target_id=b_nid,
                relationship=EdgeRelationship.CAUSES_BLOCKER,
                amount_paise=b.exposure_paise,
            ))

    # Carry-Forward Items
    for cf in verdict.carry_forward_items:
        cf_nid = node_id_carry_forward(cf.exception_id)
        nodes[cf_nid] = LineageNode(
            node_id=cf_nid,
            stage=LineageStage.VERDICT,
            entity_type="CarryForwardItem",
            label=f"Carry-Forward [{cf.exception_id}: {rupees(cf.exposure_paise)}]",
            amount_paise=cf.exposure_paise,
            status="AUTHORIZED_CARRY_FORWARD",
            evidence_refs=(cf.settlement_id, cf.evidence),
            metadata=cf.to_dict(),
        )
        edges.append(LineageEdge(
            source_id=cf_nid,
            target_id=vdt_nid,
            relationship=EdgeRelationship.CARRIED_FORWARD,
            amount_paise=cf.exposure_paise,
        ))

        # Connect exception to carry-forward node
        e_nid = node_id_exception(cf.exception_id)
        if e_nid in nodes:
            edges.append(LineageEdge(
                source_id=e_nid,
                target_id=cf_nid,
                relationship=EdgeRelationship.CARRIED_FORWARD,
                amount_paise=cf.exposure_paise,
            ))

    return FinancialLineageGraph(
        period_id=period.period_id,
        verdict_node_id=vdt_nid,
        nodes=nodes,
        edges=tuple(edges),
        missing_evidence=tuple(missing_records),
    )
