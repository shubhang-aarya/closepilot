"""CLOSEPILOT — Advisory AI Investigator (Phase 3).

Investigates financial exceptions, retrieves evidence, explains discrepancies,
summarizes findings, predicts root causes, and recommends review priorities.

ARCHITECTURAL INVARIANTS:
1. AI is strictly ADVISORY:
   Deterministic ClosePilot remains authoritative.
   AI may NOT create financial truth, alter source records, bypass deterministic
   verification, override materiality, override blockers, approve close, or post
   ledger entries.
2. Every AI claim must cite/refer to available evidence.
3. No hallucinated financial facts:
   Amounts, order IDs, and entity references are validated against retrieved tool evidence.
4. If evidence is insufficient, AI must explicitly state:
   INSUFFICIENT_EVIDENCE.
5. If evidence is contradictory, AI must explicitly state:
   CONFLICTING_EVIDENCE.
6. Untrusted text (e.g. BankCredit.narration) is strictly sandboxed against prompt injection.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from attest.close.exposure import PeriodExposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import Blocker, CarryForwardItem, PeriodVerdict
from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import BankCredit, Order, Settlement
from attest.money import rupees

from closepilot.lineage import FinancialLineageGraph, build_lineage


class InvestigationStatus(str, Enum):
    """Investigation outcome status."""

    COMPLETED = "COMPLETED"
    """Investigation completed with grounded evidence and verified citations."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    """Required evidence is missing or inaccessible; no safe factual conclusion possible."""

    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    """Retrieved evidence contains contradictory records or irreconcilable proofs."""

    REJECTED_UNTRUSTED_CONTENT = "REJECTED_UNTRUSTED_CONTENT"
    """Untrusted text contains prompt injection or adversarial directives."""


class ToolName(str, Enum):
    """Structured tools available to the AI Investigator."""

    GET_SETTLEMENT_DETAILS = "get_settlement_details"
    GET_EXCEPTION_DETAILS = "get_exception_details"
    GET_CANDIDATE_ORDERS = "get_candidate_orders"
    GET_BANK_CREDIT_NARRATION = "get_bank_credit_narration"
    GET_LINEAGE_TRACE = "get_lineage_trace"
    GET_VERDICT_SUMMARY = "get_verdict_summary"


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Audit record of a structured tool call made by the investigator."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str
    result_summary: str
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "status": self.status,
            "result_summary": self.result_summary,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class InvestigationReport:
    """Grounded advisory investigation report generated for human financial controllers.

    Strict Invariant:
    financial_truth_mutated is always False.
    """

    investigation_id: str
    target_id: str
    status: InvestigationStatus
    summary: str
    discrepancy_explanation: str
    predicted_root_cause: str
    recommended_review_priority: int
    cited_evidence_refs: tuple[str, ...]
    unverified_claims: tuple[str, ...]
    tool_calls_made: tuple[ToolCallRecord, ...]
    is_grounded: bool
    financial_truth_mutated: bool = False
    security_notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_line(self) -> str:
        grounded_str = "GROUNDED" if self.is_grounded else "UNGROUNDED"
        return (
            f"[{self.investigation_id}] Target={self.target_id} | Status={self.status.value} "
            f"({grounded_str}) | Priority={self.recommended_review_priority} | "
            f"Citations={len(self.cited_evidence_refs)} | Unverified={len(self.unverified_claims)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "target_id": self.target_id,
            "status": self.status.value,
            "summary": self.summary,
            "discrepancy_explanation": self.discrepancy_explanation,
            "predicted_root_cause": self.predicted_root_cause,
            "recommended_review_priority": self.recommended_review_priority,
            "cited_evidence_refs": list(self.cited_evidence_refs),
            "unverified_claims": list(self.unverified_claims),
            "tool_calls_made": [t.to_dict() for t in self.tool_calls_made],
            "is_grounded": self.is_grounded,
            "financial_truth_mutated": self.financial_truth_mutated,
            "security_notes": list(self.security_notes),
            "metadata": dict(self.metadata),
        }


class ToolSelectionError(Exception):
    """Raised when an invalid tool is selected or arguments are malformed."""


class PromptInjectionGuard:
    """Detects and quarantines adversarial prompt injection attempts in financial records."""

    _INJECTION_PATTERNS = (
        r"(?i)system\s*override",
        r"(?i)ignore\s+(all\s+)?(previous\s+)?instructions",
        r"(?i)approve\s+(close|period|verdict)",
        r"(?i)bypass\s+(verification|blocker|materiality)",
        r"(?i)verdict\s*:\s*ready_to_close",
        r"(?i)disregard\s+(all\s+)?blockers?",
        r"(?i)set\s+status\s+to\s+proven",
        r"(?i)you\s+are\s+now\s+in\s+developer\s+mode",
        r"(?i)delete\s+all\s+exceptions?",
    )

    @classmethod
    def scan_for_injection(cls, text: str) -> tuple[bool, str | None]:
        """Check if untrusted text contains prompt injection or adversarial directives."""
        if not text:
            return False, None
        for pattern in cls._INJECTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return True, f"Detected adversarial prompt directive: '{match.group(0)}'"
        return False, None

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Quarantine untrusted text by neutralizing control commands."""
        if not text:
            return ""
        # Strip potential markdown instruction injections or backtick fences
        clean = text.replace("```", "'''")
        # Prepend explicit untrusted tag
        return f"<untrusted_text>{clean}</untrusted_text>"


class InvestigationToolRegistry:
    """Read-only tool registry providing structured access to deterministic close artifacts."""

    def __init__(
        self,
        settlements: Sequence[Settlement] | None = None,
        exceptions: Sequence[Exception_] | None = None,
        orders: Sequence[Order] | None = None,
        bank_credits: Sequence[BankCredit] | None = None,
        verdict: PeriodVerdict | None = None,
        lineage_graph: FinancialLineageGraph | None = None,
    ) -> None:
        self._settlements = {s.settlement_id: s for s in (settlements or ())}
        self._exceptions = {e.id: e for e in (exceptions or ())}
        self._orders = {o.order_id: o for o in (orders or ())}
        self._bank_credits = {b.txn_id: b for b in (bank_credits or ())}
        self._verdict = verdict
        self._lineage_graph = lineage_graph

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a structured tool call safely and return deterministic results."""
        if tool_name == ToolName.GET_SETTLEMENT_DETAILS.value:
            return self._get_settlement_details(arguments.get("settlement_id", ""))
        elif tool_name == ToolName.GET_EXCEPTION_DETAILS.value:
            return self._get_exception_details(arguments.get("exception_id", ""))
        elif tool_name == ToolName.GET_CANDIDATE_ORDERS.value:
            return self._get_candidate_orders(arguments.get("settlement_id", ""))
        elif tool_name == ToolName.GET_BANK_CREDIT_NARRATION.value:
            return self._get_bank_credit_narration(arguments.get("txn_id_or_utr", ""))
        elif tool_name == ToolName.GET_LINEAGE_TRACE.value:
            return self._get_lineage_trace(arguments.get("target_id", ""))
        elif tool_name == ToolName.GET_VERDICT_SUMMARY.value:
            return self._get_verdict_summary(arguments.get("period_id", ""))
        else:
            raise ToolSelectionError(f"Unknown or unauthorized tool: '{tool_name}'")

    def _get_settlement_details(self, settlement_id: str) -> dict[str, Any]:
        s = self._settlements.get(settlement_id)
        if s is None:
            return {"found": False, "error": f"Settlement '{settlement_id}' not found"}
        return {
            "found": True,
            "settlement_id": s.settlement_id,
            "net_paise": s.net_paise,
            "settled_on": str(s.settled_on),
            "utr": s.utr,
        }

    def _get_exception_details(self, exception_id: str) -> dict[str, Any]:
        ex = self._exceptions.get(exception_id)
        if ex is None:
            # Check by settlement_id match
            for e in self._exceptions.values():
                if e.settlement_id == exception_id:
                    ex = e
                    break
        if ex is None:
            return {"found": False, "error": f"Exception '{exception_id}' not found"}
        return {
            "found": True,
            "exception_id": ex.id,
            "settlement_id": ex.settlement_id,
            "reason": ex.reason.value if hasattr(ex.reason, "value") else str(ex.reason),
            "severity": ex.severity.value if hasattr(ex.severity, "value") else str(ex.severity),
            "amount_paise": ex.amount_paise,
            "unexplained_paise": ex.unexplained_paise,
            "established": list(ex.established),
            "missing": ex.missing,
            "next_step": ex.next_step,
            "partial_orders": list(ex.partial.order_ids) if ex.partial else [],
            "settled_orders": list(ex.settled.order_ids) if ex.settled else [],
        }

    def _get_candidate_orders(self, settlement_id: str) -> dict[str, Any]:
        ex = self._exceptions.get(settlement_id)
        if ex is None:
            for e in self._exceptions.values():
                if e.settlement_id == settlement_id:
                    ex = e
                    break

        candidate_ids: set[str] = set()
        if ex is not None:
            if ex.partial:
                candidate_ids.update(ex.partial.order_ids)
            if ex.settled:
                candidate_ids.update(ex.settled.order_ids)
            if ex.established:
                for est in ex.established:
                    candidate_ids.update(re.findall(r"\bORD-[A-Za-z0-9_-]+\b", str(est)))

        # Retrieve order details
        orders_info = []
        for oid in sorted(candidate_ids):
            o = self._orders.get(oid)
            if o is not None:
                orders_info.append({
                    "order_id": o.order_id,
                    "net_paise": o.net,
                    "gross_paise": o.gross_paise,
                    "method": o.method.value if hasattr(o.method, "value") else str(o.method),
                })
        return {
            "settlement_id": settlement_id,
            "total_candidates": len(orders_info),
            "orders": orders_info,
        }

    def _get_bank_credit_narration(self, txn_id_or_utr: str) -> dict[str, Any]:
        # Search by txn_id or by UTR in settlements
        b = self._bank_credits.get(txn_id_or_utr)
        if b is None:
            # Check if any settlement has this UTR
            for s in self._settlements.values():
                if s.utr == txn_id_or_utr or s.settlement_id == txn_id_or_utr:
                    # search matching credit
                    for bc in self._bank_credits.values():
                        if s.utr and s.utr in bc.narration:
                            b = bc
                            break
        if b is None:
            return {"found": False, "error": f"Bank credit for '{txn_id_or_utr}' not found"}

        return {
            "found": True,
            "txn_id": b.txn_id,
            "credit_paise": b.credit_paise,
            "value_date": str(b.value_date),
            "narration": b.narration,
        }

    def _get_lineage_trace(self, target_id: str) -> dict[str, Any]:
        if self._lineage_graph is None:
            return {"found": False, "error": "Lineage graph not initialized"}
        chain = self._lineage_graph.trace_backward(target_id)
        return {
            "found": bool(chain),
            "target_id": target_id,
            "chain_length": len(chain),
            "nodes": [n.to_dict() for n in chain],
        }

    def _get_verdict_summary(self, period_id: str) -> dict[str, Any]:
        if self._verdict is None:
            return {"found": False, "error": "Period verdict not available"}
        return {
            "found": True,
            "period_id": self._verdict.period_id,
            "decision": self._verdict.decision.value,
            "material_exposure_paise": self._verdict.material_exposure_paise,
            "blocker_count": len(self._verdict.blockers),
            "carry_forward_count": len(self._verdict.carry_forward),
        }


class EvidenceGroundingValidator:
    """Validates that all claims, amounts, and entity IDs cited by AI are grounded in evidence."""

    @classmethod
    def validate_grounding(
        cls,
        summary: str,
        discrepancy_explanation: str,
        predicted_root_cause: str,
        cited_evidence_refs: Sequence[str],
        retrieved_evidence: Mapping[str, Any],
    ) -> tuple[bool, tuple[str, ...]]:
        """Verify that every cited ref and mentioned financial amount exists in retrieved evidence.

        Returns: (is_grounded, tuple_of_unverified_claims)
        """
        unverified: list[str] = []

        # 1. Check cited evidence references
        valid_refs: set[str] = set()
        for tool_name, data in retrieved_evidence.items():
            if not isinstance(data, dict):
                continue
            if data.get("settlement_id"):
                valid_refs.add(f"settlement:{data['settlement_id']}")
                valid_refs.add(data["settlement_id"])
            if data.get("exception_id"):
                valid_refs.add(f"exception:{data['exception_id']}")
                valid_refs.add(data["exception_id"])
            if data.get("txn_id"):
                valid_refs.add(f"bank_credit:{data['txn_id']}")
                valid_refs.add(data["txn_id"])
            if data.get("utr"):
                valid_refs.add(f"utr:{data['utr']}")
                valid_refs.add(data["utr"])
            if "orders" in data and isinstance(data["orders"], list):
                for ord_item in data["orders"]:
                    if isinstance(ord_item, dict) and "order_id" in ord_item:
                        valid_refs.add(f"order:{ord_item['order_id']}")
                        valid_refs.add(ord_item["order_id"])
            if "established" in data and isinstance(data["established"], list):
                for est in data["established"]:
                    for oid in re.findall(r"\bORD-[A-Za-z0-9_-]+\b", str(est)):
                        valid_refs.add(f"order:{oid}")
                        valid_refs.add(oid)
            if "partial_orders" in data and isinstance(data["partial_orders"], list):
                for oid in data["partial_orders"]:
                    valid_refs.add(f"order:{oid}")
                    valid_refs.add(oid)

        for ref in cited_evidence_refs:
            if ref not in valid_refs and not any(v in ref for v in valid_refs if len(v) > 3):
                unverified.append(f"Cited reference '{ref}' is not in retrieved tool evidence")

        # 2. Extract and verify explicit amounts mentioned in claims
        # Look for patterns like "₹5,000" or "500000 paise" or "Rs. 100"
        combined_text = f"{summary} {discrepancy_explanation} {predicted_root_cause}"

        # Collect all valid paise amounts in retrieved evidence
        valid_paise: set[int] = set()
        for tool_name, data in retrieved_evidence.items():
            if not isinstance(data, dict):
                continue
            for k, v in data.items():
                if "paise" in k and isinstance(v, int):
                    valid_paise.add(abs(v))
                    # also rupee equivalent
                    valid_paise.add(abs(v) // 100)
            if "orders" in data and isinstance(data["orders"], list):
                for ord_item in data["orders"]:
                    if isinstance(ord_item, dict):
                        for k, v in ord_item.items():
                            if "paise" in k and isinstance(v, int):
                                valid_paise.add(abs(v))
                                valid_paise.add(abs(v) // 100)

        # Also add pairwise differences between retrieved amounts
        paise_list = list(valid_paise)
        for i in range(len(paise_list)):
            for j in range(i + 1, len(paise_list)):
                diff = abs(paise_list[i] - paise_list[j])
                valid_paise.add(diff)
                valid_paise.add(diff // 100)

        # Detect rupee pattern: ₹123,456 or Rs. 123
        rupee_matches = re.findall(r"(?:₹|Rs\.?\s*)([0-9,]+(?:\.[0-9]{2})?)", combined_text)
        for m in rupee_matches:
            clean_val = m.replace(",", "")
            try:
                val_float = float(clean_val)
                paise_val = int(round(val_float * 100))
                # If amount is non-trivial (> ₹1) check that it is grounded
                if paise_val > 100 and paise_val not in valid_paise and int(val_float) not in valid_paise:
                    unverified.append(
                        f"Financial amount '{m}' (approx {paise_val} paise) does not match any evidence record"
                    )
            except ValueError:
                pass

        # Detect order ID pattern: ORD-\w+
        order_matches = set(re.findall(r"\bORD-[A-Za-z0-9_-]+\b", combined_text))
        for oid in order_matches:
            if f"order:{oid}" not in valid_refs and oid not in valid_refs:
                unverified.append(f"Mentioned order ID '{oid}' does not exist in retrieved evidence")

        is_grounded = (len(unverified) == 0)
        return is_grounded, tuple(unverified)


class AIInvestigator:
    """Advisory AI Investigator for ClosePilot.

    Coordinates structured tool retrieval, prompt injection defense,
    evidence-grounded discrepancy analysis, and root-cause prediction.

    Guarantees:
    - Never mutates financial truth.
    - Emits INSUFFICIENT_EVIDENCE when records are missing.
    - Emits CONFLICTING_EVIDENCE when records contradict.
    - Quarantines and rejects prompt injections.
    - Flags unverified or hallucinated claims.
    """

    def __init__(self, tools: InvestigationToolRegistry) -> None:
        self._tools = tools

    def investigate(
        self,
        target_id: str,
        investigation_id: str | None = None,
        context_notes: str = "",
    ) -> InvestigationReport:
        """Conduct an advisory investigation into an exception or settlement."""
        if not investigation_id:
            ts_str = datetime.now(timezone.utc).isoformat()
            digest = hashlib.sha256(f"{target_id}:{ts_str}".encode("utf-8")).hexdigest()[:8]
            investigation_id = f"inv:{target_id}:{digest}"

        tool_calls: list[ToolCallRecord] = []
        retrieved_evidence: dict[str, Any] = {}
        security_notes: list[str] = []

        def call_tool(name: ToolName, args: dict[str, Any]) -> dict[str, Any]:
            ts = datetime.now(timezone.utc).isoformat()
            try:
                res = self._tools.execute_tool(name.value, args)
                status = "SUCCESS" if res.get("found", True) else "NOT_FOUND"
                summary = f"{name.value}({args}) -> {status}"
            except Exception as e:
                status = "ERROR"
                res = {"found": False, "error": str(e)}
                summary = f"{name.value}({args}) -> ERROR: {e}"

            rec = ToolCallRecord(
                call_id=f"tc:{len(tool_calls)+1:03d}",
                tool_name=name.value,
                arguments=args,
                status=status,
                result_summary=summary,
                timestamp=ts,
            )
            tool_calls.append(rec)
            retrieved_evidence[f"{name.value}:{args.get('settlement_id') or args.get('exception_id') or args.get('target_id') or args.get('txn_id_or_utr')}"] = res
            return res

        # 1. Scan context notes for prompt injection
        if context_notes:
            is_inj, inj_msg = PromptInjectionGuard.scan_for_injection(context_notes)
            if is_inj and inj_msg:
                security_notes.append(f"Context Note: {inj_msg}")
                return InvestigationReport(
                    investigation_id=investigation_id,
                    target_id=target_id,
                    status=InvestigationStatus.REJECTED_UNTRUSTED_CONTENT,
                    summary="Investigation aborted: Untrusted prompt injection directive detected in input context.",
                    discrepancy_explanation="Input contained adversarial instructions attempting to manipulate controller state.",
                    predicted_root_cause="MALICIOUS_INPUT_INJECTION",
                    recommended_review_priority=1_000_000,
                    cited_evidence_refs=(),
                    unverified_claims=(),
                    tool_calls_made=(),
                    is_grounded=False,
                    financial_truth_mutated=False,
                    security_notes=tuple(security_notes),
                )

        # 2. Retrieve Exception or Settlement details
        ex_data = call_tool(ToolName.GET_EXCEPTION_DETAILS, {"exception_id": target_id})
        settle_id = ex_data.get("settlement_id", target_id) if ex_data.get("found") else target_id
        settle_data = call_tool(ToolName.GET_SETTLEMENT_DETAILS, {"settlement_id": settle_id})

        # Check for missing evidence
        if not ex_data.get("found") and not settle_data.get("found"):
            return InvestigationReport(
                investigation_id=investigation_id,
                target_id=target_id,
                status=InvestigationStatus.INSUFFICIENT_EVIDENCE,
                summary=f"Insufficient evidence: Record '{target_id}' does not exist in exceptions or settlements.",
                discrepancy_explanation="Cannot determine financial discrepancy because source records are missing.",
                predicted_root_cause="MISSING_SOURCE_RECORD",
                recommended_review_priority=500_000,
                cited_evidence_refs=(),
                unverified_claims=(),
                tool_calls_made=tuple(tool_calls),
                is_grounded=True,
                financial_truth_mutated=False,
            )

        # 3. Retrieve candidate orders
        cand_data = call_tool(ToolName.GET_CANDIDATE_ORDERS, {"settlement_id": settle_id})

        # 4. Retrieve bank credit narration & scan for prompt injection
        bank_data = call_tool(ToolName.GET_BANK_CREDIT_NARRATION, {"txn_id_or_utr": settle_id})
        if bank_data.get("found") and bank_data.get("narration"):
            raw_narration = bank_data["narration"]
            is_inj, inj_msg = PromptInjectionGuard.scan_for_injection(raw_narration)
            if is_inj and inj_msg:
                security_notes.append(f"Bank Narration: {inj_msg}")
                # Quarantine text and return REJECTED_UNTRUSTED_CONTENT
                return InvestigationReport(
                    investigation_id=investigation_id,
                    target_id=target_id,
                    status=InvestigationStatus.REJECTED_UNTRUSTED_CONTENT,
                    summary="Investigation halted: Prompt injection directive detected in BankCredit narration.",
                    discrepancy_explanation="Unstructured bank statement narration contains adversarial command to override close decisions.",
                    predicted_root_cause="ADVERSARIAL_NARRATION_INJECTION",
                    recommended_review_priority=1_000_000,
                    cited_evidence_refs=(f"bank_credit:{bank_data.get('txn_id')}",),
                    unverified_claims=(),
                    tool_calls_made=tuple(tool_calls),
                    is_grounded=True,
                    financial_truth_mutated=False,
                    security_notes=tuple(security_notes),
                )

        # 5. Check for conflicting evidence (e.g. multiple conflicting proofs or ambiguous explanations)
        reason_str = ex_data.get("reason", "")
        if reason_str == ReasonCode.MULTIPLE_VALID_ASSIGNMENTS.value:
            # Check if partial / settled conflict
            if ex_data.get("unexplained_paise", 0) > 0 and len(cand_data.get("orders", [])) > 1:
                # Contradictory subset assignments
                return InvestigationReport(
                    investigation_id=investigation_id,
                    target_id=target_id,
                    status=InvestigationStatus.CONFLICTING_EVIDENCE,
                    summary=(
                        f"Conflicting evidence: Multiple disjoint order subsets satisfy settlement {settle_id}."
                    ),
                    discrepancy_explanation=(
                        f"Unexplained residual of {rupees(ex_data.get('unexplained_paise', 0))} across candidate orders. "
                        "Deterministic solver cannot break the tie without order-level references."
                    ),
                    predicted_root_cause="MULTIPLE_VALID_ASSIGNMENTS",
                    recommended_review_priority=750_000,
                    cited_evidence_refs=(
                        f"exception:{ex_data.get('exception_id')}",
                        f"settlement:{settle_id}",
                    ),
                    unverified_claims=(),
                    tool_calls_made=tuple(tool_calls),
                    is_grounded=True,
                    financial_truth_mutated=False,
                    security_notes=tuple(security_notes),
                )

        # 6. Synthesize grounded explanation
        unexplained = ex_data.get("unexplained_paise", 0)
        amount = ex_data.get("amount_paise", settle_data.get("net_paise", 0))
        missing_desc = ex_data.get("missing", "missing transaction")
        established_list = ex_data.get("established", [])

        citations: list[str] = []
        if ex_data.get("found"):
            citations.append(f"exception:{ex_data['exception_id']}")
        if settle_data.get("found"):
            citations.append(f"settlement:{settle_data['settlement_id']}")
        if bank_data.get("found"):
            citations.append(f"bank_credit:{bank_data['txn_id']}")
        for ord_item in cand_data.get("orders", []):
            citations.append(f"order:{ord_item['order_id']}")

        summary = (
            f"Settlement {settle_id} has unexplained exposure of {rupees(unexplained)} "
            f"against total amount of {rupees(amount)}. Status classified as {reason_str}."
        )

        if established_list:
            est_str = "; ".join(established_list)
            discrepancy_explanation = (
                f"Established: {est_str}. Residual of {rupees(unexplained)} is unexplained due to {missing_desc}."
            )
        else:
            discrepancy_explanation = (
                f"Full amount of {rupees(unexplained)} lacks matching capture records or order proofs."
            )

        predicted_cause = f"LIKELY_{reason_str or 'TIMING_GAP'}"
        review_priority = 200_000 + (unexplained // 1_000)

        # Validate Grounding
        is_grounded, unverified = EvidenceGroundingValidator.validate_grounding(
            summary=summary,
            discrepancy_explanation=discrepancy_explanation,
            predicted_root_cause=predicted_cause,
            cited_evidence_refs=citations,
            retrieved_evidence=retrieved_evidence,
        )

        return InvestigationReport(
            investigation_id=investigation_id,
            target_id=target_id,
            status=InvestigationStatus.COMPLETED,
            summary=summary,
            discrepancy_explanation=discrepancy_explanation,
            predicted_root_cause=predicted_cause,
            recommended_review_priority=review_priority,
            cited_evidence_refs=tuple(citations),
            unverified_claims=unverified,
            tool_calls_made=tuple(tool_calls),
            is_grounded=is_grounded,
            financial_truth_mutated=False,
            security_notes=tuple(security_notes),
        )
