"""The Close Controller — period close readiness kernel.

Answers the question no reconciliation tool answers:
    "Can this financial period be safely closed?"

Like `attest.verdict.check()`, this module is a small, read-only kernel that
composes trusted outputs without computing new financial truth:
- Findings from the reconciliation engine (`Finding.postable`, search space integrity)
- Judgements from the action policy (`Judgement.decision`)
- Exceptions from the classifier (`Exception_.severity`, `unexplained_paise`)
- Financial Exposure Engine (`assess_exposure`)
- Configurable economic materiality bounds (`MaterialityBound`)

Emits one of three period-level verdicts:
    READY_TO_CLOSE
    READY_WITH_CARRY_FORWARD
    BLOCKED

LOCKED SEMANTICS:

    READY_TO_CLOSE
    = no unresolved material exposure
    + no blockers
    + all required invariants pass

    READY_WITH_CARRY_FORWARD
    = unresolved exposure exists
    + total unresolved exposure is below materiality
    + no blocker
    + required invariants pass
    + every carry-forward is explicitly represented

    BLOCKED
    = material unresolved exposure
    OR blocker
    OR failed required invariant
    OR compromised integrity
    OR contradictory/unsafe evidence
    OR any other condition that prevents a safe financial conclusion

CRITICAL RULE:
    Materiality may downgrade an economic exception to carry-forward.
    Materiality may NEVER override a hard safety blocker.
    Therefore:
    LOW VALUE + HARD BLOCKER = BLOCKED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from attest.exceptions import Exception_, Severity
from attest.model import Settlement
from attest.money import rupees
from attest.policy import Decision, Judgement
from attest.searchspace import Integrity, SearchSpace
from attest.verdict import Finding, Verdict

from attest.close.exposure import ExposureKind, assess_exposure
from attest.close.materiality import MaterialityBound
from attest.close.period import Period


class ReadinessDecision(str, Enum):
    """The three period-level close states."""

    READY_TO_CLOSE = "READY_TO_CLOSE"
    """All transactions proven and posted, or zero unresolved exposure and zero blockers."""

    READY_WITH_CARRY_FORWARD = "READY_WITH_CARRY_FORWARD"
    """Unresolved exposure is strictly below materiality, invariants pass, and carry-forward items are named."""

    BLOCKED = "BLOCKED"
    """Material exposure, hard blockers, failed invariants, compromised integrity, or unsafe evidence."""


class BlockerKind(str, Enum):
    """Machine-readable taxonomy of hard close blockers."""

    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    """Contradictory findings or evidence for the same settlement or ledger transaction."""

    AMBIGUOUS_MATERIAL_SETTLEMENT = "AMBIGUOUS_MATERIAL_SETTLEMENT"
    """Ambiguous settlement whose unverified amount is individually material."""

    DUPLICATE_LEDGER_IMPACT = "DUPLICATE_LEDGER_IMPACT"
    """Duplicate order references across settlements affecting ledger balance (double spending)."""

    IMPOSSIBLE_STATE_TRANSITION = "IMPOSSIBLE_STATE_TRANSITION"
    """Boundary violation, impossible date range, or invalid lifecycle state transition."""

    UNRESOLVED_MATERIAL_AMOUNT = "UNRESOLVED_MATERIAL_AMOUNT"
    """Total unresolved financial exposure exceeds allowable materiality threshold."""

    FAILED_INVARIANT = "FAILED_INVARIANT"
    """Core engine invariant failure (e.g. unpostable proven finding or arithmetic mismatch)."""

    COMPROMISED_INTEGRITY = "COMPROMISED_INTEGRITY"
    """Search space integrity was compromised (known_loss > 0 or candidate pruned illegally)."""

    POLICY_BLOCKED = "POLICY_BLOCKED"
    """Action policy issued Decision.BLOCK."""

    HIGH_SEVERITY_EXCEPTION = "HIGH_SEVERITY_EXCEPTION"
    """Exception classified with Severity.HIGH (e.g. data quality failure)."""

    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    """Settlement in period scope is missing from reconciliation evidence."""

    UNVERIFIED_CONTRADICTION = "UNVERIFIED_CONTRADICTION"
    """Settlement contradicted with zero explained value."""


@dataclass(frozen=True, slots=True)
class Blocker:
    """Traceable, machine-readable hard close blocker.

    Materiality may NEVER override a hard safety blocker.
    """

    kind: BlockerKind
    ref_id: str
    reason: str
    exposure_paise: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "ref_id": self.ref_id,
            "reason": self.reason,
            "exposure_paise": self.exposure_paise,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CarryForwardItem:
    """An unresolved exception explicitly authorized to carry forward into the next period.

    Provides complete operational transparency for financial controllers:
    - What remains unresolved? (exception_id, settlement_id, reason)
    - How much money is exposed? (exposure_paise)
    - Why is it allowed to carry forward? (close_impact)
    - What should happen next? (next_step)
    - What evidence exists? (evidence)
    """

    exception_id: str
    settlement_id: str
    exposure_paise: int
    reason: str
    age_days: int
    severity: str
    close_impact: str
    next_step: str
    evidence: str
    metadata: dict[str, object] = field(default_factory=dict)

    def summary(self) -> str:
        """Single-line operational summary for controller dashboard/logs."""
        return (
            f"[{self.exception_id}] {self.settlement_id}: {rupees(self.exposure_paise)} "
            f"({self.reason}, {self.severity}, age {self.age_days}d) — "
            f"Impact: {self.close_impact} — Next: {self.next_step}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "exception_id": self.exception_id,
            "settlement_id": self.settlement_id,
            "exposure_paise": self.exposure_paise,
            "reason": self.reason,
            "age_days": self.age_days,
            "severity": self.severity,
            "close_impact": self.close_impact,
            "next_step": self.next_step,
            "evidence": self.evidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class PeriodVerdict:
    """Tamper-evident, audit-ready close readiness decision for a financial period."""

    period_id: str
    decision: ReadinessDecision
    reasons: tuple[str, ...]
    material_exposure_paise: int
    carry_forward: tuple[str, ...]
    blockers: tuple[str, ...]
    structured_blockers: tuple[Blocker, ...] = ()
    carry_forward_items: tuple[CarryForwardItem, ...] = ()
    net_unresolved_exposure_paise: int = 0
    gross_contested_claim_exposure_paise: int = 0

    @property
    def active_blocker_rule_instances(self) -> int:
        """Count of active blocker rule instances that fired."""
        return len(self.structured_blockers)

    @property
    def unique_blocked_exceptions(self) -> int:
        """Count of unique exceptions affected by active blockers."""
        seen: set[str] = set()
        for b in self.structured_blockers:
            if b.ref_id.startswith("EX-"):
                seen.add(b.ref_id)
            elif "exception_id" in b.metadata:
                seen.add(str(b.metadata["exception_id"]))
        return len(seen)

    @property
    def unique_blocked_settlements(self) -> int:
        """Count of unique settlements affected by active blockers."""
        seen: set[str] = set()
        for b in self.structured_blockers:
            if b.ref_id.startswith("setl_"):
                seen.add(b.ref_id)
            elif ":" in b.ref_id and b.ref_id.split(":")[0].startswith("setl_"):
                seen.add(b.ref_id.split(":")[0])
            elif "settlement_id" in b.metadata:
                seen.add(str(b.metadata["settlement_id"]))
        return len(seen)

    @property
    def blocker_rule_breakdown(self) -> dict[str, int]:
        """Breakdown of active blocker rule instances by BlockerKind."""
        counts: dict[str, int] = {}
        for b in self.structured_blockers:
            counts[b.kind.value] = counts.get(b.kind.value, 0) + 1
        return counts

    def explain(self) -> str:
        """Render human-readable reasoning lines, matching Judgement.explain()."""
        lines = list(self.reasons)
        if self.carry_forward_items:
            lines.append("")
            lines.append(
                f"CARRY-FORWARD LEDGER ({len(self.carry_forward_items)} item(s), "
                f"total exposure {rupees(self.get_carry_forward_total_paise())}):"
            )
            for item in self.carry_forward_items:
                lines.append(f"  • {item.summary()}")
                if item.evidence:
                    lines.append(f"    Evidence: {item.evidence}")
        return "\n".join(lines)

    def has_blocker_kind(self, kind: BlockerKind) -> bool:
        """Check if a specific category of blocker was triggered."""
        return any(b.kind == kind for b in self.structured_blockers)

    def get_blockers_by_kind(self, kind: BlockerKind) -> tuple[Blocker, ...]:
        """Retrieve all blockers of a specific category."""
        return tuple(b for b in self.structured_blockers if b.kind == kind)

    def get_carry_forward_by_id(self, exception_id: str) -> CarryForwardItem | None:
        """Find a specific carry-forward item by its exception ID."""
        for cf in self.carry_forward_items:
            if cf.exception_id == exception_id:
                return cf
        return None

    def get_carry_forward_total_paise(self) -> int:
        """Total unverified exposure across all carry-forward items."""
        return sum(cf.exposure_paise for cf in self.carry_forward_items)

    def to_json(self) -> dict[str, object]:
        return {
            "period_id": self.period_id,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "material_exposure_paise": self.material_exposure_paise,
            "net_unresolved_exposure_paise": self.net_unresolved_exposure_paise,
            "gross_contested_claim_exposure_paise": self.gross_contested_claim_exposure_paise,
            "active_blocker_rule_instances": self.active_blocker_rule_instances,
            "unique_blocked_exceptions": self.unique_blocked_exceptions,
            "unique_blocked_settlements": self.unique_blocked_settlements,
            "blocker_rule_breakdown": self.blocker_rule_breakdown,
            "carry_forward": list(self.carry_forward),
            "carry_forward_items": [cf.to_dict() for cf in self.carry_forward_items],
            "blockers": list(self.blockers),
            "structured_blockers": [b.to_dict() for b in self.structured_blockers],
        }



def decide_period(
    period: Period,
    findings: list[Finding],
    judgements: dict[str, Judgement],
    exceptions: list[Exception_],
    materiality: MaterialityBound,
    settlements: list[Settlement] | None = None,
) -> PeriodVerdict:
    """Evaluate close readiness for a period by composing engine outputs.

    Pure, deterministic, read-only.
    Enforces the locked ClosePilot readiness semantics:
        READY_TO_CLOSE: Zero unresolved material exposure + zero blockers + all invariants pass.
        READY_WITH_CARRY_FORWARD: Unresolved exposure is strictly below materiality +
                                  zero blockers + all invariants pass + every carry-forward explicitly listed.
        BLOCKED: Material unresolved exposure OR hard blocker OR failed invariant OR compromised integrity.

    CRITICAL RULE:
        Materiality may NEVER override a hard safety blocker.
        LOW VALUE + HARD BLOCKER = BLOCKED.
    """
    target_ids = set(period.settlement_ids)

    # 1. Filter items relevant to this period scope
    period_findings = [f for f in findings if f.settlement_id in target_ids]
    period_exceptions = [e for e in exceptions if e.settlement_id in target_ids]
    period_settlements = [s for s in settlements if s.settlement_id in target_ids] if settlements is not None else None

    findings_by_id: dict[str, list[Finding]] = {}
    for f in period_findings:
        findings_by_id.setdefault(f.settlement_id, []).append(f)

    exceptions_by_sid: dict[str, list[Exception_]] = {}
    for e in period_exceptions:
        exceptions_by_sid.setdefault(e.settlement_id, []).append(e)

    structured_blockers: list[Blocker] = []
    reasons: list[str] = []

    # 2. Check Period Boundary & Impossible State Transitions
    if period_settlements is not None and period.start and period.end:
        for s in period_settlements:
            if s.settled_on < period.start or s.settled_on > period.end:
                structured_blockers.append(Blocker(
                    kind=BlockerKind.IMPOSSIBLE_STATE_TRANSITION,
                    ref_id=s.settlement_id,
                    reason=f"settlement {s.settlement_id} settled_on ({s.settled_on}) falls outside period range [{period.start}, {period.end}]",
                    exposure_paise=abs(s.net_paise),
                ))

    # 3. Check Contradictory Evidence & Conflicting Findings
    for sid, flist in findings_by_id.items():
        if len(flist) > 1:
            verdicts = {f.verdict for f in flist}
            if len(verdicts) > 1:
                structured_blockers.append(Blocker(
                    kind=BlockerKind.CONTRADICTORY_EVIDENCE,
                    ref_id=sid,
                    reason=f"settlement {sid} has contradictory findings with conflicting verdicts: {sorted(v.value for v in verdicts)}",
                ))
            else:
                proof_sets = {tuple(p.order_ids) for f in flist for p in f.proofs}
                if len(proof_sets) > 1:
                    structured_blockers.append(Blocker(
                        kind=BlockerKind.CONTRADICTORY_EVIDENCE,
                        ref_id=sid,
                        reason=f"settlement {sid} has contradictory proofs with conflicting order assignments",
                    ))

    # Check for CONTRADICTED findings with unverified residual
    for f in period_findings:
        if f.verdict is Verdict.CONTRADICTED:
            exs = exceptions_by_sid.get(f.settlement_id, [])
            for ex in exs:
                if ex.unexplained_paise == ex.amount_paise and ex.amount_paise > 0:
                    structured_blockers.append(Blocker(
                        kind=BlockerKind.CONTRADICTORY_EVIDENCE,
                        ref_id=ex.id,
                        reason=f"settlement {f.settlement_id} is contradicted with zero explained value",
                        exposure_paise=ex.unexplained_paise,
                    ))

    # 4. Check Duplicate Reference Affecting Ledger Value (Cross-Settlement Double-Spending)
    proven_order_to_settlements: dict[str, set[str]] = {}
    for f in period_findings:
        if f.verdict is Verdict.PROVEN:
            for p in f.proofs:
                for oid in p.order_ids:
                    proven_order_to_settlements.setdefault(oid, set()).add(f.settlement_id)

    for oid, sids in sorted(proven_order_to_settlements.items()):
        if len(sids) > 1:
            sorted_sids = sorted(sids)
            for sid in sorted_sids:
                structured_blockers.append(Blocker(
                    kind=BlockerKind.DUPLICATE_LEDGER_IMPACT,
                    ref_id=f"{sid}:{oid}",
                    reason=f"order {oid} is claimed by multiple proven settlements {sorted_sids}, causing duplicate ledger impact",
                ))

    # 5. Check Engine Invariants (Failed Invariant)
    for f in period_findings:
        if f.verdict is Verdict.PROVEN and not f.postable:
            structured_blockers.append(Blocker(
                kind=BlockerKind.FAILED_INVARIANT,
                ref_id=f.settlement_id,
                reason=f"settlement {f.settlement_id} marked PROVEN failed posting invariant (postable is False: candidate universe, membership, or solver layer unrecorded)",
            ))

        for p in f.proofs:
            expected_net = p.gross_paise - p.fee_paise - p.tax_paise + p.adjustment_paise
            if abs(expected_net - p.net_paise) > p.tolerance_paise:
                structured_blockers.append(Blocker(
                    kind=BlockerKind.FAILED_INVARIANT,
                    ref_id=f.settlement_id,
                    reason=f"proof arithmetic mismatch for settlement {f.settlement_id}: gross-fee-tax+adj={expected_net} vs net={p.net_paise}",
                    exposure_paise=abs(expected_net - p.net_paise),
                ))

    # 6. Check Search Space Integrity (Compromised Integrity)
    for f in period_findings:
        space = f.space if isinstance(f.space, SearchSpace) else None
        if space is not None and space.integrity is Integrity.COMPROMISED:
            structured_blockers.append(Blocker(
                kind=BlockerKind.COMPROMISED_INTEGRITY,
                ref_id=f.settlement_id,
                reason=f"settlement {f.settlement_id} has a COMPROMISED search space; valid candidates were excluded",
            ))

    # 7. Check Action Policy Blocks
    for sid in period.settlement_ids:
        j = judgements.get(sid)
        if j is not None and j.decision is Decision.BLOCK:
            structured_blockers.append(Blocker(
                kind=BlockerKind.POLICY_BLOCKED,
                ref_id=sid,
                reason=f"settlement {sid} is BLOCKED by policy: {j.explain()}",
            ))

    # 8. Check High Severity Exceptions
    for ex in period_exceptions:
        if ex.severity is Severity.HIGH:
            structured_blockers.append(Blocker(
                kind=BlockerKind.HIGH_SEVERITY_EXCEPTION,
                ref_id=ex.id,
                reason=f"exception {ex.id} on settlement {ex.settlement_id} has HIGH severity ({ex.reason.value})",
                exposure_paise=abs(ex.unexplained_paise),
            ))

    # 9. Check Missing Settlements in Period Scope
    for sid in period.settlement_ids:
        f_list = findings_by_id.get(sid, [])
        exs = exceptions_by_sid.get(sid, [])
        if not f_list and not exs:
            structured_blockers.append(Blocker(
                kind=BlockerKind.MISSING_SETTLEMENT,
                ref_id=sid,
                reason=f"settlement {sid} included in period scope but missing from reconciliation findings",
            ))

    # 10. Compute Exposure Assessment and Materiality
    exposure_assessment = assess_exposure(
        findings=period_findings,
        exceptions=period_exceptions,
        target_settlement_ids=period.settlement_ids,
        settlements=period_settlements,
    )

    total_period_paise = exposure_assessment.total_value_paise
    net_unresolved_exposure_paise = exposure_assessment.net_unresolved_exposure_paise
    gross_contested_claim_exposure_paise = exposure_assessment.gross_contested_claim_exposure_paise
    unresolved_exposure_paise = net_unresolved_exposure_paise  # Primary close-readiness economic metric
    allowable_paise = materiality.max_allowable_exposure_paise(total_period_paise)
    is_material = materiality.is_material(net_unresolved_exposure_paise, total_period_paise)

    reasons.append(
        f"period {period.period_id} evaluated with {len(target_ids)} settlement(s) "
        f"totalling {rupees(total_period_paise)}"
    )
    reasons.append(
        f"materiality policy {materiality.version} allows up to {rupees(allowable_paise)} "
        f"unexplained exposure ({materiality.threshold_bps} bps, floor {rupees(materiality.floor_paise)}, "
        f"ceiling {rupees(materiality.ceiling_paise)})"
    )
    reasons.append(exposure_assessment.summary())

    # Check for Ambiguous Material Settlement
    for item in exposure_assessment.items:
        item_net_unresolved_paise = item.settlement_value_paise
        if item.kind is ExposureKind.AMBIGUOUS and item_net_unresolved_paise > allowable_paise:
            structured_blockers.append(Blocker(
                kind=BlockerKind.AMBIGUOUS_MATERIAL_SETTLEMENT,
                ref_id=item.settlement_id,
                reason=f"ambiguous settlement {item.settlement_id} net unresolved exposure {rupees(item_net_unresolved_paise)} exceeds allowable threshold {rupees(allowable_paise)}",
                exposure_paise=item_net_unresolved_paise,
                metadata={"settlement_id": item.settlement_id},
            ))

    # Check for Unresolved Material Amount
    if is_material:
        structured_blockers.append(Blocker(
            kind=BlockerKind.UNRESOLVED_MATERIAL_AMOUNT,
            ref_id=f"material_exposure:{period.period_id}",
            reason=f"net unresolved exposure {rupees(net_unresolved_exposure_paise)} exceeds allowable threshold {rupees(allowable_paise)}",
            exposure_paise=net_unresolved_exposure_paise,
            metadata={"period_id": period.period_id},
        ))
        reasons.append(
            f"net unresolved exposure {rupees(net_unresolved_exposure_paise)} exceeds allowable threshold "
            f"{rupees(allowable_paise)}"
        )
        for item in exposure_assessment.items:
            ex_matches = exceptions_by_sid.get(item.settlement_id, [])
            if ex_matches:
                for ex in ex_matches:
                    structured_blockers.append(Blocker(
                        kind=BlockerKind.UNRESOLVED_MATERIAL_AMOUNT,
                        ref_id=ex.id,
                        reason=f"unresolved exception {ex.id} on settlement {item.settlement_id} contributes to material exposure",
                        exposure_paise=abs(ex.unexplained_paise),
                        metadata={"exception_id": ex.id, "settlement_id": item.settlement_id},
                    ))
            else:
                structured_blockers.append(Blocker(
                    kind=BlockerKind.UNRESOLVED_MATERIAL_AMOUNT,
                    ref_id=item.settlement_id,
                    reason=f"unresolved settlement {item.settlement_id} contributes to material exposure",
                    exposure_paise=item.exposure_paise,
                    metadata={"settlement_id": item.settlement_id},
                ))
    else:
        reasons.append(
            f"net unresolved exposure {rupees(net_unresolved_exposure_paise)} is within allowable threshold "
            f"{rupees(allowable_paise)}"
        )


    # 11. Deduplicate Blockers deterministically
    seen_blocker_keys: set[tuple[BlockerKind, str]] = set()
    dedup_structured: list[Blocker] = []
    blockers_str_list: list[str] = []

    for b in structured_blockers:
        key = (b.kind, b.ref_id)
        if key not in seen_blocker_keys:
            seen_blocker_keys.add(key)
            dedup_structured.append(b)
            if b.ref_id not in blockers_str_list:
                blockers_str_list.append(b.ref_id)
            reasons.append(f"BLOCKER [{b.kind.value}] on {b.ref_id}: {b.reason}")

    dedup_structured_tuple = tuple(dedup_structured)
    blockers_str_tuple = tuple(blockers_str_list)

    # 12. Synthesize Final Verdict strictly enforcing locked semantics
    # CRITICAL RULE: Materiality may NEVER override a hard safety blocker.
    # LOW VALUE + HARD BLOCKER = BLOCKED.
    carry_items_list: list[CarryForwardItem] = []

    if dedup_structured_tuple:
        decision = ReadinessDecision.BLOCKED
        carry_tuple: tuple[str, ...] = ()
        carry_items_tuple: tuple[CarryForwardItem, ...] = ()
        mat_exp = unresolved_exposure_paise if is_material else sum(
            b.exposure_paise for b in dedup_structured_tuple if b.exposure_paise > 0
        )
    elif unresolved_exposure_paise > 0 or period_exceptions:
        decision = ReadinessDecision.READY_WITH_CARRY_FORWARD
        mat_exp = 0

        settlements_by_id = {s.settlement_id: s for s in period_settlements} if period_settlements else {}

        # Build rich CarryForwardItem for each exception authorized to carry forward
        seen_ex_ids: set[str] = set()
        for ex in period_exceptions:
            if ex.id in seen_ex_ids:
                continue
            seen_ex_ids.add(ex.id)

            exp_paise = abs(ex.unexplained_paise)
            reason_str = ex.reason.value if hasattr(ex.reason, "value") else str(ex.reason)
            severity_str = ex.severity.value if hasattr(ex.severity, "value") else str(ex.severity)
            s = settlements_by_id.get(ex.settlement_id)

            # Compute age in days
            if s is not None and period.end is not None and s.settled_on is not None:
                age_days = max(0, (period.end - s.settled_on).days)
            elif s is not None and period.start is not None and s.settled_on is not None:
                age_days = max(0, (s.settled_on - period.start).days)
            else:
                age_days = 0

            # Close impact explanation
            close_impact = (
                f"Immaterial residual {rupees(exp_paise)} is within allowable policy threshold "
                f"{rupees(allowable_paise)} ({materiality.threshold_bps} bps); authorized for carry-forward"
            )

            # Compile evidence references
            evidence_parts: list[str] = []
            if ex.missing:
                evidence_parts.append(f"missing: {ex.missing}")
            if ex.established:
                evidence_parts.append(f"established: {', '.join(ex.established)}")
            if ex.partial is not None:
                evidence_parts.append(f"partial match: {len(ex.partial.order_ids)} order(s) totalling {rupees(ex.partial.net_paise)}")
            if ex.settled is not None:
                evidence_parts.append(f"uncontested: {len(ex.settled.order_ids)} order(s) totalling {rupees(ex.settled.net_paise)}")
            if s is not None and s.utr:
                evidence_parts.append(f"UTR: {s.utr}")
            evidence_str = "; ".join(evidence_parts) if evidence_parts else f"settlement {ex.settlement_id}"

            carry_items_list.append(CarryForwardItem(
                exception_id=ex.id,
                settlement_id=ex.settlement_id,
                exposure_paise=exp_paise,
                reason=reason_str,
                age_days=age_days,
                severity=severity_str,
                close_impact=close_impact,
                next_step=ex.next_step,
                evidence=evidence_str,
            ))

        # Deterministic sort: largest financial exposure first, then exception ID
        carry_items_list.sort(key=lambda item: (-item.exposure_paise, item.exception_id))
        carry_items_tuple = tuple(carry_items_list)
        carry_tuple = tuple(item.exception_id for item in carry_items_tuple)
    else:
        decision = ReadinessDecision.READY_TO_CLOSE
        mat_exp = 0
        carry_tuple = ()
        carry_items_tuple = ()

    return PeriodVerdict(
        period_id=period.period_id,
        decision=decision,
        reasons=tuple(reasons),
        material_exposure_paise=mat_exp,
        carry_forward=carry_tuple,
        blockers=blockers_str_tuple,
        structured_blockers=dedup_structured_tuple,
        carry_forward_items=carry_items_tuple,
        net_unresolved_exposure_paise=net_unresolved_exposure_paise,
        gross_contested_claim_exposure_paise=gross_contested_claim_exposure_paise,
    )
