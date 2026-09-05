"""Period-level materiality policy and threshold engine.

Reconciliation marks exact penny discrepancies. Close decisions must assess
whether unexplained residuals are material to the period.

Like `attest.policy.Costs`, materiality is not an asserted intuition; it is an
explicitly parameterized economic bound. The threshold is carried on the close
verdict and certificate so audit can challenge the parameters rather than
guessing why the engine closed or blocked.

Materiality properties:
- Deterministic: Identical inputs always yield identical materiality decisions.
- Configurable: Basis points, absolute floor, and ceiling are configurable.
- Explicit: Every threshold determination explains whether floor, percentage,
  or ceiling governed the bound.
- Auditable: Returns full assessment records with readable explanations.
- Versioned: Content-addressed SHA-256 fingerprint changes if any parameter moves.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from attest.money import rupees


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    """Audit-ready assessment of an exposure against a materiality policy."""

    is_material: bool
    exposure_paise: int
    total_period_paise: int
    effective_threshold_paise: int
    governing_factor: str  # "FLOOR" | "PERCENTAGE" | "CEILING"
    explanation: str
    version: str


@dataclass(frozen=True, slots=True)
class MaterialityBound:
    """Configurable materiality policy for a financial close period.

    Thresholds are defined in basis points (bps) of total period value,
    bounded between an absolute floor and an absolute ceiling:

    - Below floor_paise, discrepancies are immaterial regardless of percentage.
    - Above ceiling_paise, discrepancies are material regardless of percentage.
    - Between floor and ceiling, threshold scales linearly with period value.
    """

    threshold_bps: int = 100
    """Basis points of period value (100 bps = 1.00%, 50 bps = 0.50%).
    Configurable by merchant policy. Never assumed as a single fixed truth."""

    floor_paise: int = 10_000
    """₹100 floor: noise below this is immaterial."""

    ceiling_paise: int = 10_000_000
    """₹1,00,000 ceiling: aligns with `Costs.max_exposure_paise`. Above this,
    exposure is material regardless of the overall period size."""

    def __post_init__(self) -> None:
        if self.threshold_bps < 0:
            raise ValueError(f"threshold_bps must be non-negative, got {self.threshold_bps}")
        if self.floor_paise < 0:
            raise ValueError(f"floor_paise must be non-negative, got {self.floor_paise}")
        if self.ceiling_paise < self.floor_paise:
            raise ValueError(
                f"ceiling_paise ({self.ceiling_paise}) cannot be less than floor_paise ({self.floor_paise})"
            )

    def max_allowable_exposure_paise(self, total_paise: int) -> int:
        """Maximum unexplained paise permitted while still allowing a period to close.

        Uses integer arithmetic exclusively. Discrepancies <= allowable are
        immaterial; discrepancies strictly > allowable are material.
        """
        if total_paise <= 0:
            return self.floor_paise
        scaled = total_paise * self.threshold_bps // 10_000
        return max(self.floor_paise, min(scaled, self.ceiling_paise))

    def is_material(self, exposure_paise: int, total_paise: int) -> bool:
        """Whether a given exposure amount strictly exceeds the allowable threshold."""
        return exposure_paise > self.max_allowable_exposure_paise(total_paise)

    def explain_threshold(self, total_paise: int) -> str:
        """Human-readable audit explanation of how the effective threshold was derived."""
        allowable = self.max_allowable_exposure_paise(total_paise)
        if total_paise <= 0:
            return f"zero-value period: allowable threshold is floor {rupees(allowable)}"
        raw = total_paise * self.threshold_bps // 10_000
        if raw < self.floor_paise:
            return (
                f"{self.threshold_bps} bps of {rupees(total_paise)} is {rupees(raw)}, "
                f"clamped to floor {rupees(self.floor_paise)}"
            )
        if raw > self.ceiling_paise:
            return (
                f"{self.threshold_bps} bps of {rupees(total_paise)} is {rupees(raw)}, "
                f"clamped to ceiling {rupees(self.ceiling_paise)}"
            )
        return (
            f"{self.threshold_bps} bps ({self.threshold_bps / 100:.2f}%) of "
            f"{rupees(total_paise)} is {rupees(allowable)} (within floor {rupees(self.floor_paise)} "
            f"and ceiling {rupees(self.ceiling_paise)})"
        )

    def assess(self, exposure_paise: int, total_paise: int) -> MaterialityAssessment:
        """Detailed audit evaluation of an exposure against this policy."""
        allowable = self.max_allowable_exposure_paise(total_paise)
        is_mat = self.is_material(exposure_paise, total_paise)

        if total_paise <= 0 or (total_paise * self.threshold_bps // 10_000) < self.floor_paise:
            gov = "FLOOR"
        elif (total_paise * self.threshold_bps // 10_000) > self.ceiling_paise:
            gov = "CEILING"
        else:
            gov = "PERCENTAGE"

        status = "MATERIAL" if is_mat else "IMMATERIAL"
        explanation = (
            f"exposure {rupees(exposure_paise)} is {status} against allowable threshold "
            f"{rupees(allowable)} ({self.explain_threshold(total_paise)})"
        )

        return MaterialityAssessment(
            is_material=is_mat,
            exposure_paise=exposure_paise,
            total_period_paise=total_paise,
            effective_threshold_paise=allowable,
            governing_factor=gov,
            explanation=explanation,
            version=self.version,
        )

    @property
    def version(self) -> str:
        """Deterministic fingerprint of this materiality configuration."""
        blob = json.dumps(
            {
                "ceiling_paise": self.ceiling_paise,
                "floor_paise": self.floor_paise,
                "threshold_bps": self.threshold_bps,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "materiality_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
