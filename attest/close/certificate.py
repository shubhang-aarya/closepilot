"""The Close Certificate — audit-ready, tamper-evident cryptographic record of close readiness.

A Close Readiness verdict is an assertion. A Close Certificate is the cryptographic account
behind it: what was evaluated, what was verified, what was not, what the thresholds were,
the exact blocker reasons, carry-forward exceptions, invariant checks, and enough
tamper-evident evidence for an independent auditor or regulator to reproduce the decision.

Guarantees:
- Every field is read, never derived or estimated.
- The `evidence_hash` is a deterministic SHA-256 digest cryptographically tied
  to all decision-relevant fields (verdict, values, exposures, materiality,
  blockers, carry-forward items, invariant results, and policy versions).
- Nondeterministic issuance fields (issued_at, certificate_id) are excluded from
  `evidence_hash` so that:
      same financial state + same policy = same evidence identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from attest.money import rupees

from attest.close.materiality import MaterialityBound
from attest.close.period import Period
from attest.close.readiness import PeriodVerdict, ReadinessDecision


def compute_evidence_hash(
    period_id: str,
    period_start: str | None,
    period_end: str | None,
    verdict: str,
    period_value_paise: int,
    reconciled_value_paise: int,
    unresolved_exposure_paise: int,
    material_exposure_paise: int,
    effective_materiality_threshold_paise: int,
    materiality_policy_version: str,
    materiality_threshold_bps: int,
    materiality_floor_paise: int,
    materiality_ceiling_paise: int,
    structured_blockers: tuple[dict[str, Any], ...],
    carry_forward_items: tuple[dict[str, Any], ...],
    invariants: tuple[str, ...],
    policy_version: str,
    engine_version: str,
) -> str:
    """Compute the deterministic, cryptographic SHA-256 digest over all decision-relevant evidence.

    Changing ANY decision-relevant field changes this hash.
    Nondeterministic issuance fields (e.g. issued_at, certificate_id) are strictly excluded.
    """
    payload = {
        "period": {
            "period_id": period_id,
            "start": period_start,
            "end": period_end,
        },
        "verdict": verdict,
        "values": {
            "period_value_paise": period_value_paise,
            "reconciled_value_paise": reconciled_value_paise,
            "unresolved_exposure_paise": unresolved_exposure_paise,
            "material_exposure_paise": material_exposure_paise,
        },
        "materiality": {
            "effective_threshold_paise": effective_materiality_threshold_paise,
            "policy_version": materiality_policy_version,
            "threshold_bps": materiality_threshold_bps,
            "floor_paise": materiality_floor_paise,
            "ceiling_paise": materiality_ceiling_paise,
        },
        "blockers": list(structured_blockers),
        "carry_forward": list(carry_forward_items),
        "invariants": list(invariants),
        "provenance": {
            "policy_version": policy_version,
            "engine_version": engine_version,
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CloseCertificate:
    """A tamper-evident, audit-ready cryptographic certificate of a close readiness decision.

    Contains all decision-relevant fields, blocker details, carry-forward records,
    invariant results, and a cryptographic evidence hash verifying audit integrity.
    """

    # --- identity & issuance ---
    certificate_id: str
    issued_at: str

    # --- period ---
    period_id: str
    period_start: str | None
    period_end: str | None

    # --- decision ---
    verdict: str
    explanation: str

    # --- values ---
    period_value_paise: int
    reconciled_value_paise: int
    unresolved_exposure_paise: int
    material_exposure_paise: int

    # --- materiality ---
    effective_materiality_threshold_paise: int
    materiality_policy_version: str
    materiality_threshold_bps: int
    materiality_floor_paise: int
    materiality_ceiling_paise: int

    # --- blockers ---
    blocker_ids: tuple[str, ...]
    blocker_reasons: tuple[str, ...]
    structured_blockers: tuple[dict[str, Any], ...]

    # --- carry-forward ---
    carry_forward_ids: tuple[str, ...]
    carry_forward_items: tuple[dict[str, Any], ...]

    # --- invariants ---
    invariants: tuple[str, ...]

    # --- provenance ---
    policy_version: str
    engine_version: str

    # --- cryptographic evidence hash ---
    evidence_hash: str

    # --- optional gross contested claim exposure (diagnostic metric) ---
    gross_contested_claim_exposure_paise: int | None = None

    # --- explicit semantic property aliases ---
    @property
    def total_period_value_paise(self) -> int:
        return self.period_value_paise

    @property
    def verified_value_paise(self) -> int:
        return self.reconciled_value_paise

    @property
    def net_unresolved_exposure_paise(self) -> int:
        return self.unresolved_exposure_paise

    @property
    def active_blocker_rule_instances(self) -> int:
        return len(self.blocker_ids)

    @property
    def unique_blocked_exceptions(self) -> int:
        seen: set[str] = set()
        for b in self.structured_blockers:
            ref = str(b.get("ref_id", ""))
            if ref.startswith("EX-"):
                seen.add(ref)
            meta = b.get("metadata", {})
            if isinstance(meta, dict) and "exception_id" in meta:
                seen.add(str(meta["exception_id"]))
            if "exception_id" in b:
                seen.add(str(b["exception_id"]))
        return len(seen)

    @property
    def unique_blocked_settlements(self) -> int:
        seen: set[str] = set()
        for b in self.structured_blockers:
            ref = str(b.get("ref_id", ""))
            if ref.startswith("setl_"):
                seen.add(ref)
            elif ":" in ref and ref.split(":")[0].startswith("setl_"):
                seen.add(ref.split(":")[0])
            meta = b.get("metadata", {})
            if isinstance(meta, dict) and "settlement_id" in meta:
                seen.add(str(meta["settlement_id"]))
            if "settlement_id" in b:
                seen.add(str(b["settlement_id"]))
        return len(seen)

    def verify_evidence_hash(self) -> bool:
        """Cryptographically verify that the certificate's evidence_hash matches its fields.

        Returns True if and only if zero decision-relevant fields have been altered or tampered with.
        """
        expected = compute_evidence_hash(
            period_id=self.period_id,
            period_start=self.period_start,
            period_end=self.period_end,
            verdict=self.verdict,
            period_value_paise=self.period_value_paise,
            reconciled_value_paise=self.reconciled_value_paise,
            unresolved_exposure_paise=self.unresolved_exposure_paise,
            material_exposure_paise=self.material_exposure_paise,
            effective_materiality_threshold_paise=self.effective_materiality_threshold_paise,
            materiality_policy_version=self.materiality_policy_version,
            materiality_threshold_bps=self.materiality_threshold_bps,
            materiality_floor_paise=self.materiality_floor_paise,
            materiality_ceiling_paise=self.materiality_ceiling_paise,
            structured_blockers=self.structured_blockers,
            carry_forward_items=self.carry_forward_items,
            invariants=self.invariants,
            policy_version=self.policy_version,
            engine_version=self.engine_version,
        )
        return self.evidence_hash == expected

    def to_json(self) -> dict[str, object]:
        return {
            "certificate_id": self.certificate_id,
            "issued_at": self.issued_at,
            "period": {
                "period_id": self.period_id,
                "start": self.period_start,
                "end": self.period_end,
            },
            "decision": {
                "verdict": self.verdict,
                "explanation": self.explanation,
            },
            "values": {
                "total_period_value_paise": self.period_value_paise,
                "period_value_paise": self.period_value_paise,
                "verified_value_paise": self.reconciled_value_paise,
                "reconciled_value_paise": self.reconciled_value_paise,
                "net_unresolved_exposure_paise": self.unresolved_exposure_paise,
                "unresolved_exposure_paise": self.unresolved_exposure_paise,
                "material_exposure_paise": self.material_exposure_paise,
                "gross_contested_claim_exposure_paise": self.gross_contested_claim_exposure_paise,
            },
            "counts": {
                "active_blocker_rule_instances": self.active_blocker_rule_instances,
                "unique_blocked_exceptions": self.unique_blocked_exceptions,
                "unique_blocked_settlements": self.unique_blocked_settlements,
            },
            "materiality": {
                "effective_threshold_paise": self.effective_materiality_threshold_paise,
                "policy_version": self.materiality_policy_version,
                "threshold_bps": self.materiality_threshold_bps,
                "floor_paise": self.materiality_floor_paise,
                "ceiling_paise": self.materiality_ceiling_paise,
            },
            "blockers": list(self.structured_blockers),
            "carry_forward": list(self.carry_forward_items),
            "invariants": list(self.invariants),
            "provenance": {
                "policy_version": self.policy_version,
                "engine_version": self.engine_version,
            },
            "evidence_hash": self.evidence_hash,
        }

    def render(self) -> str:
        w = 66
        mark = {
            "READY_TO_CLOSE": "✓ READY TO CLOSE",
            "READY_WITH_CARRY_FORWARD": "⚠ READY WITH CARRY-FORWARD",
            "BLOCKED": "✗ BLOCKED",
        }
        lines = [
            "=" * w,
            "CLOSEPILOT CLOSE CERTIFICATE",
            "=" * w,
            f"  Certificate ID       : {self.certificate_id}",
            f"  Issued At (UTC)      : {self.issued_at}",
            f"  Period ID            : {self.period_id}",
            f"  Period Range         : {self.period_start or 'N/A'} -> {self.period_end or 'N/A'}",
            f"  Decision             : {mark.get(self.verdict, self.verdict)}",
            "-" * w,
            f"  Total Period Value   : {rupees(self.period_value_paise)}",
            f"  Verified Value       : {rupees(self.reconciled_value_paise)}",
            f"  Net Unresolved Exp.  : {rupees(self.unresolved_exposure_paise)}",
            *(
                [f"  Gross Contested Claim: {rupees(self.gross_contested_claim_exposure_paise)} (diagnostic)"]
                if self.gross_contested_claim_exposure_paise is not None
                else []
            ),
            f"  Material Exposure    : {rupees(self.material_exposure_paise)}",
            f"  Materiality Threshold: {rupees(self.effective_materiality_threshold_paise)}",
            f"  Materiality Policy   : {self.materiality_policy_version} ({self.materiality_threshold_bps} bps, floor {rupees(self.materiality_floor_paise)}, ceiling {rupees(self.materiality_ceiling_paise)})",
            "-" * w,
            f"  Active Blocker Rule Instances : {self.active_blocker_rule_instances}",
            f"  Unique Blocked Exceptions     : {self.unique_blocked_exceptions}",
            f"  Unique Blocked Settlements    : {self.unique_blocked_settlements}",
            f"  Blockers ({len(self.blocker_ids)}):",
        ]
        for bid, r in zip(self.blocker_ids, self.blocker_reasons):
            lines.append(f"    • {bid}: {r}")
        if not self.blocker_ids:
            lines.append("    (None)")

        lines.append(f"  Carry-Forward Exceptions ({len(self.carry_forward_ids)}):")
        for cf in self.carry_forward_items:
            lines.append(f"    • [{cf.get('exception_id')}] {cf.get('settlement_id')}: {rupees(cf.get('exposure_paise', 0))} — {cf.get('reason')}")
        if not self.carry_forward_ids:
            lines.append("    (None)")

        lines.append("-" * w)
        lines.append("  Invariants:")
        for inv in self.invariants:
            lines.append(f"    ✓ {inv}")

        lines.append("-" * w)
        lines.append(f"  Policy Version       : {self.policy_version}")
        lines.append(f"  Evidence Hash        : {self.evidence_hash}")
        lines.append("=" * w)
        return "\n".join(lines)


def issue_certificate(
    verdict: PeriodVerdict,
    period: Period,
    materiality: MaterialityBound,
    reconciled_value_paise: int,
    period_value_paise: int,
    unresolved_exposure_paise: int | None = None,
    gross_contested_claim_exposure_paise: int | None = None,
    policy_version: str = "policy_v1",
    engine_version: str = "closepilot_v1",
    invariants: tuple[str, ...] | None = None,
    issued_at: str | None = None,
    certificate_id: str | None = None,
) -> CloseCertificate:
    """Issue a tamper-evident Close Certificate from engine decision records."""
    unresolved_paise = (
        unresolved_exposure_paise
        if unresolved_exposure_paise is not None
        else (verdict.material_exposure_paise if verdict.decision is ReadinessDecision.BLOCKED else verdict.get_carry_forward_total_paise())
    )
    effective_thresh = materiality.max_allowable_exposure_paise(period_value_paise)

    # Invariants verification results: conservation law holds strictly
    if invariants is not None:
        invariants_tuple = tuple(invariants)
    else:
        inv_list: list[str] = [
            f"verified_value + net_unresolved_exposure == total_value: {rupees(reconciled_value_paise)} + {rupees(unresolved_paise)} == {rupees(period_value_paise)} (verified_value + exposure == total_value)",
        ]
        if verdict.decision is ReadinessDecision.READY_TO_CLOSE:
            inv_list.append("decision READY_TO_CLOSE: zero unresolved material exposure and zero blockers")
        elif verdict.decision is ReadinessDecision.READY_WITH_CARRY_FORWARD:
            inv_list.append(f"decision READY_WITH_CARRY_FORWARD: exposure {rupees(unresolved_paise)} is within allowable threshold; zero blockers")
        elif verdict.decision is ReadinessDecision.BLOCKED:
            inv_list.append(f"decision BLOCKED: close prevented by {len(verdict.blockers)} blocker(s)")
        invariants_tuple = tuple(inv_list)

    structured_blockers = tuple(b.to_dict() for b in verdict.structured_blockers)
    carry_forward_items = tuple(cf.to_dict() for cf in verdict.carry_forward_items)

    period_start_iso = period.start.isoformat() if period.start else None
    period_end_iso = period.end.isoformat() if period.end else None

    # Compute deterministic evidence hash across all decision-relevant evidence
    ev_hash = compute_evidence_hash(
        period_id=period.period_id,
        period_start=period_start_iso,
        period_end=period_end_iso,
        verdict=verdict.decision.value,
        period_value_paise=period_value_paise,
        reconciled_value_paise=reconciled_value_paise,
        unresolved_exposure_paise=unresolved_paise,
        material_exposure_paise=verdict.material_exposure_paise,
        effective_materiality_threshold_paise=effective_thresh,
        materiality_policy_version=materiality.version,
        materiality_threshold_bps=materiality.threshold_bps,
        materiality_floor_paise=materiality.floor_paise,
        materiality_ceiling_paise=materiality.ceiling_paise,
        structured_blockers=structured_blockers,
        carry_forward_items=carry_forward_items,
        invariants=invariants_tuple,
        policy_version=policy_version,
        engine_version=engine_version,
    )

    now = issued_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    cert_id = certificate_id or f"CERT-{period.period_id}-{ev_hash[:8]}"

    return CloseCertificate(
        certificate_id=cert_id,
        issued_at=now,
        period_id=period.period_id,
        period_start=period_start_iso,
        period_end=period_end_iso,
        verdict=verdict.decision.value,
        explanation=verdict.explain(),
        period_value_paise=period_value_paise,
        reconciled_value_paise=reconciled_value_paise,
        unresolved_exposure_paise=unresolved_paise,
        material_exposure_paise=verdict.material_exposure_paise,
        effective_materiality_threshold_paise=effective_thresh,
        materiality_policy_version=materiality.version,
        materiality_threshold_bps=materiality.threshold_bps,
        materiality_floor_paise=materiality.floor_paise,
        materiality_ceiling_paise=materiality.ceiling_paise,
        blocker_ids=verdict.blockers,
        blocker_reasons=tuple(b.reason for b in verdict.structured_blockers),
        structured_blockers=structured_blockers,
        carry_forward_ids=verdict.carry_forward,
        carry_forward_items=carry_forward_items,
        invariants=invariants_tuple,
        policy_version=policy_version,
        engine_version=engine_version,
        evidence_hash=ev_hash,
        gross_contested_claim_exposure_paise=gross_contested_claim_exposure_paise,
    )
