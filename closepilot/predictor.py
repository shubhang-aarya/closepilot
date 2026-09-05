"""CLOSEPILOT — Resolution Predictor (Phase 2A).

Predicts which unresolved financial exceptions are likely to resolve naturally
within a future horizon, versus those requiring manual intervention or dispute.

Architectural Guarantees:
- This is an operational intelligence and routing layer, NOT the close decision.
- The deterministic Close Controller remains authoritative.
- The predictor NEVER:
    * modifies financial truth
    * modifies ledger state
    * overrides a blocker
    * overrides materiality
    * changes READY/BLOCKED semantics
    * auto-posts financial entries
- Predictions are 100% reproducible and deterministic given the same inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement
from attest.money import rupees

from attest.close.readiness import CarryForwardItem


class ResolutionRouting(str, Enum):
    """Actionable operational routing recommended by the predictor."""

    AUTO_RESOLVE_NEXT_CYCLE = "AUTO_RESOLVE_NEXT_CYCLE"
    """Expected to clear naturally on the next batch/run (e.g. timing gap, month boundary)."""

    HOLD_FOR_SETTLEMENT_WINDOW = "HOLD_FOR_SETTLEMENT_WINDOW"
    """Wait for expected settlement window / gateway batch (e.g. refund processing)."""

    INVESTIGATE_OPERATIONAL = "INVESTIGATE_OPERATIONAL"
    """Requires manual investigation to supply missing identifiers or tie-breakers."""

    ESCALATE_FINANCE_DISPUTE = "ESCALATE_FINANCE_DISPUTE"
    """Requires formal dispute, gateway inquiry, or chargeback response."""

    DATA_OPS_CORRECTION = "DATA_OPS_CORRECTION"
    """Technical or pipeline issue requiring re-export or schema fix."""

    MANUAL_AUDIT = "MANUAL_AUDIT"
    """High value or high severity residual requiring controller sign-off."""


class ConfidenceTier(str, Enum):
    """Confidence tier for the resolution prediction."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class ResolutionFeatures:
    """Extracted normalized features for an unresolved financial exception."""

    exception_id: str
    settlement_id: str
    reason_code: str
    severity: str
    age_days: int
    exposure_paise: int
    settlement_value_paise: int
    exposure_ratio: float
    has_partial_match: bool
    has_established_orders: bool
    has_missing_evidence_ref: bool
    ambiguity_count: int
    prior_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "settlement_id": self.settlement_id,
            "reason_code": self.reason_code,
            "severity": self.severity,
            "age_days": self.age_days,
            "exposure_paise": self.exposure_paise,
            "settlement_value_paise": self.settlement_value_paise,
            "exposure_ratio": round(self.exposure_ratio, 4),
            "has_partial_match": self.has_partial_match,
            "has_established_orders": self.has_established_orders,
            "has_missing_evidence_ref": self.has_missing_evidence_ref,
            "ambiguity_count": self.ambiguity_count,
            "prior_attempts": self.prior_attempts,
        }


@dataclass(frozen=True, slots=True)
class ResolutionPrediction:
    """Deterministic prediction of natural resolution for an unresolved exception."""

    exception_id: str
    settlement_id: str
    probability: float
    expected_horizon_days: int
    confidence: ConfidenceTier
    confidence_score: float
    recommended_routing: ResolutionRouting
    rationale: str
    features: ResolutionFeatures
    feature_contributions: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "settlement_id": self.settlement_id,
            "probability": self.probability,
            "expected_horizon_days": self.expected_horizon_days,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
            "recommended_routing": self.recommended_routing.value,
            "rationale": self.rationale,
            "features": self.features.to_dict(),
            "feature_contributions": {
                k: round(v, 4) for k, v in self.feature_contributions.items()
            },
        }

    def summary(self) -> str:
        pct = f"{self.probability * 100:.1f}%"
        return (
            f"[{self.exception_id}] p(resolve)={pct} (T+{self.expected_horizon_days}d, "
            f"{self.confidence.value} conf) → {self.recommended_routing.value}: {self.rationale}"
        )


# --------------------------------------------------------------------------
# Statistical Hazard Priors (derived from reconciliation physics & taxonomy)
# --------------------------------------------------------------------------

# (base_probability, default_horizon_days, default_routing)
_HAZARD_PRIORS: dict[str, tuple[float, int, ResolutionRouting]] = {
    ReasonCode.TIMING_MISMATCH.value: (
        0.88,
        3,
        ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE,
    ),
    ReasonCode.REFUND_MISMATCH.value: (
        0.72,
        5,
        ResolutionRouting.HOLD_FOR_SETTLEMENT_WINDOW,
    ),
    ReasonCode.UNKNOWN_ADJUSTMENT.value: (
        0.45,
        7,
        ResolutionRouting.INVESTIGATE_OPERATIONAL,
    ),
    ReasonCode.MULTIPLE_VALID_ASSIGNMENTS.value: (
        0.25,
        14,
        ResolutionRouting.INVESTIGATE_OPERATIONAL,
    ),
    ReasonCode.DUPLICATE_AMOUNT.value: (
        0.30,
        10,
        ResolutionRouting.INVESTIGATE_OPERATIONAL,
    ),
    ReasonCode.PARTIAL_SETTLEMENT.value: (
        0.65,
        5,
        ResolutionRouting.HOLD_FOR_SETTLEMENT_WINDOW,
    ),
    ReasonCode.MISSING_TRANSACTION.value: (
        0.40,
        7,
        ResolutionRouting.DATA_OPS_CORRECTION,
    ),
    ReasonCode.SEARCH_SPACE_UNCERTAIN.value: (
        0.55,
        3,
        ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE,
    ),
    ReasonCode.CHARGEBACK.value: (
        0.18,
        30,
        ResolutionRouting.ESCALATE_FINANCE_DISPUTE,
    ),
    ReasonCode.DATA_QUALITY.value: (
        0.05,
        14,
        ResolutionRouting.DATA_OPS_CORRECTION,
    ),
    ReasonCode.NO_VALID_ASSIGNMENT.value: (
        0.20,
        14,
        ResolutionRouting.INVESTIGATE_OPERATIONAL,
    ),
    ReasonCode.INSUFFICIENT_EVIDENCE.value: (
        0.35,
        7,
        ResolutionRouting.INVESTIGATE_OPERATIONAL,
    ),
}

_DEFAULT_PRIOR = (0.30, 7, ResolutionRouting.INVESTIGATE_OPERATIONAL)


def extract_features(
    exception: Exception_ | CarryForwardItem | dict[str, Any],
    settlement: Settlement | None = None,
    age_days: int | None = None,
    prior_attempts: int = 0,
) -> ResolutionFeatures:
    """Deterministically extract normalized prediction features from an exception."""
    if isinstance(exception, Exception_):
        eid = exception.id
        sid = exception.settlement_id
        rc = exception.reason.value if hasattr(exception.reason, "value") else str(exception.reason)
        sev = exception.severity.value if hasattr(exception.severity, "value") else str(exception.severity)
        exp_paise = abs(exception.unexplained_paise)
        setl_val = exception.amount_paise if exception.amount_paise > 0 else (settlement.net_paise if settlement else exp_paise)
        has_partial = exception.partial is not None
        has_est = len(exception.established) > 0
        has_ref = bool(exception.missing and len(str(exception.missing).strip()) > 0)
        amb_count = len(exception.established) + (len(exception.partial.order_ids) if exception.partial else 0)
        eff_age = age_days if age_days is not None else 0

    elif isinstance(exception, CarryForwardItem):
        eid = exception.exception_id
        sid = exception.settlement_id
        rc = exception.reason
        sev = exception.severity
        exp_paise = abs(exception.exposure_paise)
        setl_val = settlement.net_paise if settlement else exp_paise
        has_partial = "partial" in exception.evidence.lower()
        has_est = "order" in exception.evidence.lower()
        has_ref = "arn" in exception.evidence.lower() or "ref" in exception.evidence.lower() or "utr" in exception.evidence.lower()
        amb_count = 1
        eff_age = age_days if age_days is not None else exception.age_days

    elif isinstance(exception, dict):
        eid = str(exception.get("id") or exception.get("exception_id") or "EX-UNKNOWN")
        sid = str(exception.get("settlement_id") or "SETL-UNKNOWN")
        rc = str(exception.get("reason") or ReasonCode.UNKNOWN_ADJUSTMENT.value)
        sev = str(exception.get("severity") or Severity.LOW.value)
        exp_paise = abs(int(exception.get("unexplained_paise") or exception.get("exposure_paise") or 0))
        setl_val = abs(int(exception.get("amount_paise") or exception.get("settlement_value_paise") or (settlement.net_paise if settlement else exp_paise)))
        has_partial = bool(exception.get("partial"))
        has_est = bool(exception.get("established"))
        has_ref = bool(exception.get("missing"))
        amb_count = int(exception.get("ambiguity_count") or 0)
        eff_age = age_days if age_days is not None else int(exception.get("age_days") or 0)
    else:
        raise TypeError(f"Unsupported exception type: {type(exception)}")

    if setl_val <= 0:
        setl_val = max(exp_paise, 1)

    exposure_ratio = min(1.0, max(0.0, exp_paise / setl_val))

    return ResolutionFeatures(
        exception_id=eid,
        settlement_id=sid,
        reason_code=rc,
        severity=sev,
        age_days=max(0, eff_age),
        exposure_paise=exp_paise,
        settlement_value_paise=setl_val,
        exposure_ratio=exposure_ratio,
        has_partial_match=has_partial,
        has_established_orders=has_est,
        has_missing_evidence_ref=has_ref,
        ambiguity_count=amb_count,
        prior_attempts=max(0, prior_attempts),
    )


def predict_resolution(features: ResolutionFeatures) -> ResolutionPrediction:
    """Predict resolution probability, horizon, confidence, and routing.

    Pure mathematical, deterministic scoring function.
    No network calls, no randomness, no floating-point ambiguity.
    """
    base_p, base_horizon, default_routing = _HAZARD_PRIORS.get(
        features.reason_code, _DEFAULT_PRIOR
    )

    contributions: dict[str, float] = {"base_prior": base_p}
    logit = math.log(max(1e-4, base_p) / max(1e-4, 1.0 - base_p))

    # 1. Age decay effect: exceptions get harder to resolve naturally over time
    if features.age_days <= 2:
        age_adj = 0.35  # fresh batch boost
    elif features.age_days <= 5:
        age_adj = 0.05
    elif features.age_days <= 10:
        age_adj = -0.40
    elif features.age_days <= 30:
        age_adj = -1.10
    else:
        age_adj = -2.20

    logit += age_adj
    contributions["age_decay"] = age_adj

    # 2. Exposure size effect: very small residuals resolve via minor adjustments;
    # massive exposures require formal disputes
    if features.exposure_paise == 0:
        exp_adj = 1.00
    elif features.exposure_paise < 5_000:  # < Rs 50
        exp_adj = 0.40
    elif features.exposure_paise < 50_000:  # < Rs 500
        exp_adj = 0.10
    elif features.exposure_paise < 500_000:  # < Rs 5,000
        exp_adj = -0.30
    else:  # > Rs 5,000
        exp_adj = -0.80

    logit += exp_adj
    contributions["exposure_magnitude"] = exp_adj

    # 3. Evidence completeness boost
    ev_adj = 0.0
    if features.has_missing_evidence_ref:
        ev_adj += 0.35  # Named identifier (ARN, reference) allows targeted resolution
    if features.has_partial_match or features.has_established_orders:
        ev_adj += 0.25  # Only subset is disputed, majority is explained
    logit += ev_adj
    contributions["evidence_completeness"] = ev_adj

    # 4. Severity penalty
    sev_adj = 0.0
    if features.severity == Severity.HIGH.value:
        sev_adj = -1.20
    elif features.severity == Severity.MEDIUM.value:
        sev_adj = -0.30
    logit += sev_adj
    contributions["severity"] = sev_adj

    # 5. Prior failed attempts penalty
    prior_adj = -0.40 * min(features.prior_attempts, 4)
    logit += prior_adj
    contributions["prior_attempts"] = prior_adj

    # Logistic transformation bounded strictly to [0.01, 0.99]
    prob = 1.0 / (1.0 + math.exp(-logit))
    prob = max(0.01, min(0.99, prob))
    prob = round(prob, 4)

    # Calculate expected horizon days
    if features.reason_code == ReasonCode.TIMING_MISMATCH.value:
        horizon_days = max(1, min(base_horizon, 4 - features.age_days))
    elif prob >= 0.75:
        horizon_days = max(1, base_horizon)
    elif prob >= 0.40:
        horizon_days = max(base_horizon, base_horizon + 3)
    else:
        horizon_days = max(14, base_horizon + 10)

    # Compute confidence score
    conf_score = 0.50
    if abs(prob - 0.50) >= 0.30:
        conf_score += 0.25
    if features.has_missing_evidence_ref or features.has_established_orders:
        conf_score += 0.15
    if features.age_days > 20:
        conf_score += 0.10  # Stale items reliably don't clear naturally

    conf_score = round(min(0.99, max(0.10, conf_score)), 2)
    if conf_score >= 0.75:
        confidence = ConfidenceTier.HIGH
    elif conf_score >= 0.45:
        confidence = ConfidenceTier.MEDIUM
    else:
        confidence = ConfidenceTier.LOW

    # Routing determination
    if features.severity == Severity.HIGH.value or features.exposure_paise >= 1_000_000:
        routing = ResolutionRouting.MANUAL_AUDIT
        rationale = f"High exposure ({rupees(features.exposure_paise)}) or severity requires explicit controller review"
    elif features.reason_code == ReasonCode.CHARGEBACK.value:
        routing = ResolutionRouting.ESCALATE_FINANCE_DISPUTE
        rationale = "Chargeback reversal requires gateway dispute process"
    elif features.reason_code == ReasonCode.DATA_QUALITY.value:
        routing = ResolutionRouting.DATA_OPS_CORRECTION
        rationale = "Data quality defect requires source export correction"
    elif prob >= 0.75 and features.age_days <= 3:
        routing = ResolutionRouting.AUTO_RESOLVE_NEXT_CYCLE
        rationale = f"High probability ({prob*100:.0f}%) of natural clearance within T+{horizon_days}d"
    elif prob >= 0.50:
        routing = ResolutionRouting.HOLD_FOR_SETTLEMENT_WINDOW
        rationale = f"Moderate resolution likelihood ({prob*100:.0f}%); hold across normal settlement window"
    else:
        routing = ResolutionRouting.INVESTIGATE_OPERATIONAL
        rationale = f"Low natural resolution likelihood ({prob*100:.0f}%); requires operational investigation"

    return ResolutionPrediction(
        exception_id=features.exception_id,
        settlement_id=features.settlement_id,
        probability=prob,
        expected_horizon_days=horizon_days,
        confidence=confidence,
        confidence_score=conf_score,
        recommended_routing=routing,
        rationale=rationale,
        features=features,
        feature_contributions=contributions,
    )


def predict_batch(
    exceptions: Sequence[Exception_ | CarryForwardItem | dict[str, Any]],
    settlements: Mapping[str, Settlement] | Sequence[Settlement] | None = None,
    age_days: int | None = None,
) -> tuple[ResolutionPrediction, ...]:
    """Deterministically predict resolution for a sequence of exceptions."""
    if isinstance(settlements, Sequence):
        setl_map: dict[str, Settlement] = {s.settlement_id: s for s in settlements}
    elif isinstance(settlements, Mapping):
        setl_map = dict(settlements)
    else:
        setl_map = {}

    predictions: list[ResolutionPrediction] = []
    for ex in exceptions:
        sid = (
            ex.settlement_id
            if hasattr(ex, "settlement_id")
            else str(ex.get("settlement_id", ""))
        )
        s = setl_map.get(sid)
        feats = extract_features(ex, settlement=s, age_days=age_days)
        pred = predict_resolution(feats)
        predictions.append(pred)

    # Sort predictions deterministically: lowest probability first (highest risk first)
    return tuple(sorted(predictions, key=lambda p: (p.probability, -p.features.exposure_paise, p.exception_id)))
