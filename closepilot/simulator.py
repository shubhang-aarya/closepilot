"""CLOSEPILOT — Counterfactual Close Simulator (Phase 2B).

Answers the financial controller's critical question:
    "What happens if I close now?"

Architectural Guarantees:
- PURE AND NON-MUTATING: The simulator NEVER mutates source ledgers, findings,
  exceptions, judgements, or settlements. All scenarios are pure functional projections.
- AUTHORITATIVE CONTROLLER: The simulator does NOT invent decision logic. It evaluates
  projected candidate states strictly through the authoritative Close Controller
  (`attest.close.readiness.decide_period`).
- DISTINCT STATE TAXONOMY: Explicitly separates `ACTUAL STATE` (today's realized
  financial truth) from `HYPOTHETICAL STATE` (projected what-if outcome).
- FULL TRACEABILITY: Calculates projected verdict, unresolved exposure, material exposure,
  blockers, carry-forward count/value, and exact delta from actual baseline.
- ZERO LLM / ZERO HEURISTIC OVERRIDE: Evaluates deterministic rule invariants.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from attest.exceptions import Exception_, ReasonCode, Severity
from attest.model import Settlement
from attest.money import rupees
from attest.policy import Decision, Judgement, RiskModel
from attest.searchspace import Reduction, SearchSpace
from attest.verdict import Finding, Proof, Verdict

from attest.close.exposure import ExposureKind, PeriodExposure, assess_exposure
from attest.close.materiality import MaterialityAssessment, MaterialityBound
from attest.close.period import Period
from attest.close.readiness import (
    Blocker,
    BlockerKind,
    CarryForwardItem,
    PeriodVerdict,
    ReadinessDecision,
    decide_period,
)
from closepilot.predictor import (
    ConfidenceTier,
    ResolutionPrediction,
    predict_batch,
    predict_resolution,
)


class SimulationState(str, Enum):
    """Explicit distinction between realized truth and hypothetical projection."""

    ACTUAL = "ACTUAL"
    """The realized, observed financial state as of the evaluation timestamp."""

    HYPOTHETICAL = "HYPOTHETICAL"
    """A projected counterfactual what-if simulation; non-authoritative until executed."""


class ScenarioType(str, Enum):
    """Taxonomy of counterfactual close scenarios."""

    CLOSE_NOW = "CLOSE_NOW"
    """Baseline actual evaluation: evaluate close readiness as-is."""

    RESOLVE_EXCEPTIONS = "RESOLVE_EXCEPTIONS"
    """Simulate resolution of selected exception(s) via manual or external intervention."""

    CARRY_FORWARD_IMMATERIAL = "CARRY_FORWARD_IMMATERIAL"
    """Simulate explicitly authorizing eligible immaterial exceptions for carry-forward."""

    CLEAR_BLOCKER = "CLEAR_BLOCKER"
    """Simulate hypothetical clearance of a specific blocker where explicitly permitted."""

    WAIT_PREDICTED_RESOLUTIONS = "WAIT_PREDICTED_RESOLUTIONS"
    """Simulate waiting for predicted natural resolutions over horizon T+N days."""

    CUSTOM_COMPOSITE = "CUSTOM_COMPOSITE"
    """Simulate a combined scenario (e.g. resolve exceptions + clear blocker + wait)."""


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    """Specification of a counterfactual simulation scenario."""

    scenario_id: str
    scenario_type: ScenarioType
    description: str
    resolved_exception_ids: tuple[str, ...] = ()
    cleared_blocker_refs: tuple[str, ...] = ()
    cleared_blocker_kinds: tuple[BlockerKind, ...] = ()
    carry_forward_immaterial: bool = False
    wait_horizon_days: int | None = None
    min_prediction_prob: float = 0.70
    hypothetical_materiality: MaterialityBound | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type.value,
            "description": self.description,
            "resolved_exception_ids": list(self.resolved_exception_ids),
            "cleared_blocker_refs": list(self.cleared_blocker_refs),
            "cleared_blocker_kinds": [k.value for k in self.cleared_blocker_kinds],
            "carry_forward_immaterial": self.carry_forward_immaterial,
            "wait_horizon_days": self.wait_horizon_days,
            "min_prediction_prob": self.min_prediction_prob,
        }


@dataclass(frozen=True, slots=True)
class SimulationOutcome:
    """The complete projected financial verdict and delta from actual baseline."""

    scenario_id: str
    scenario_type: ScenarioType
    description: str
    state_type: SimulationState
    projected_verdict: ReadinessDecision
    unresolved_exposure_paise: int
    material_exposure_paise: int
    blockers: tuple[str, ...]
    structured_blockers: tuple[Blocker, ...]
    carry_forward_count: int
    carry_forward_value_paise: int
    carry_forward_items: tuple[CarryForwardItem, ...]
    delta_unresolved_exposure_paise: int
    delta_material_exposure_paise: int
    delta_blocker_count: int
    delta_carry_forward_count: int
    verdict_transition: str
    resolved_exception_ids: tuple[str, ...]
    cleared_blocker_refs: tuple[str, ...]
    is_closeable: bool
    explanation: str

    @property
    def blocker_count(self) -> int:
        return len(self.blockers)

    @property
    def net_unresolved_exposure_paise(self) -> int:
        return self.unresolved_exposure_paise

    @property
    def active_blocker_rule_instances(self) -> int:
        return len(self.blockers)

    @property
    def unique_blocked_exceptions(self) -> int:
        seen: set[str] = set()
        for b in self.structured_blockers:
            if b.ref_id.startswith("EX-") or b.ref_id.startswith("ex_"):
                seen.add(b.ref_id)
            elif "exception_id" in b.metadata:
                seen.add(str(b.metadata["exception_id"]))
        return len(seen)

    @property
    def unique_blocked_settlements(self) -> int:
        seen: set[str] = set()
        for b in self.structured_blockers:
            if b.ref_id.startswith("setl_") or b.ref_id.startswith("s_"):
                seen.add(b.ref_id)
            elif ":" in b.ref_id and b.ref_id.split(":")[0].startswith("setl_"):
                seen.add(b.ref_id.split(":")[0])
            elif "settlement_id" in b.metadata:
                seen.add(str(b.metadata["settlement_id"]))
        return len(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type.value,
            "description": self.description,
            "state_type": self.state_type.value,
            "projected_verdict": self.projected_verdict.value,
            "net_unresolved_exposure_paise": self.unresolved_exposure_paise,
            "unresolved_exposure_paise": self.unresolved_exposure_paise,
            "material_exposure_paise": self.material_exposure_paise,
            "blockers": list(self.blockers),
            "active_blocker_rule_instances": self.active_blocker_rule_instances,
            "unique_blocked_exceptions": self.unique_blocked_exceptions,
            "unique_blocked_settlements": self.unique_blocked_settlements,
            "blocker_count": self.blocker_count,
            "structured_blockers": [b.to_dict() for b in self.structured_blockers],
            "carry_forward_count": self.carry_forward_count,
            "carry_forward_value_paise": self.carry_forward_value_paise,
            "carry_forward_items": [cf.to_dict() for cf in self.carry_forward_items],
            "delta_unresolved_exposure_paise": self.delta_unresolved_exposure_paise,
            "delta_material_exposure_paise": self.delta_material_exposure_paise,
            "delta_blocker_count": self.delta_blocker_count,
            "delta_carry_forward_count": self.delta_carry_forward_count,
            "verdict_transition": self.verdict_transition,
            "resolved_exception_ids": list(self.resolved_exception_ids),
            "cleared_blocker_refs": list(self.cleared_blocker_refs),
            "is_closeable": self.is_closeable,
            "explanation": self.explanation,
        }

    def summary(self) -> str:
        state_tag = f"[{self.state_type.value}]"
        sign = "+" if self.delta_unresolved_exposure_paise >= 0 else ""
        delta_str = f"Δexp: {sign}{rupees(self.delta_unresolved_exposure_paise)}"
        return (
            f"{state_tag} {self.scenario_id} ({self.scenario_type.value}): "
            f"{self.projected_verdict.value} | Exposure: {rupees(self.unresolved_exposure_paise)} ({delta_str}) | "
            f"Blockers: {self.blocker_count} (Δ{self.delta_blocker_count:+d}) | "
            f"CF: {self.carry_forward_count} ({rupees(self.carry_forward_value_paise)})"
        )


@dataclass(frozen=True, slots=True)
class SimulationReport:
    """Comprehensive comparative simulation report across scenarios."""

    period_id: str
    total_period_value_paise: int
    actual_baseline: SimulationOutcome
    scenarios: tuple[SimulationOutcome, ...]
    evaluated_at: str

    @property
    def all_outcomes(self) -> tuple[SimulationOutcome, ...]:
        return (self.actual_baseline,) + self.scenarios

    def recommended_scenario(self) -> SimulationOutcome | None:
        """Deterministically recommend the least intrusive scenario that achieves close."""
        # Check if actual baseline is already closeable
        if self.actual_baseline.is_closeable:
            return self.actual_baseline

        closeable = [s for s in self.scenarios if s.is_closeable]
        if not closeable:
            # If none can close, pick scenario with greatest material exposure reduction
            return min(self.scenarios, key=lambda s: (s.material_exposure_paise, s.unresolved_exposure_paise), default=None)

        # Prioritize:
        # 1. WAIT_PREDICTED (natural resolution without manual toil)
        # 2. CARRY_FORWARD_IMMATERIAL (procedural close)
        # 3. Lowest resolved exception count (minimal intervention)
        def score(s: SimulationOutcome) -> tuple[int, int, int]:
            type_prio = {
                ScenarioType.WAIT_PREDICTED_RESOLUTIONS: 1,
                ScenarioType.CARRY_FORWARD_IMMATERIAL: 2,
                ScenarioType.RESOLVE_EXCEPTIONS: 3,
                ScenarioType.CLEAR_BLOCKER: 4,
                ScenarioType.CUSTOM_COMPOSITE: 5,
                ScenarioType.CLOSE_NOW: 0,
            }.get(s.scenario_type, 9)
            return (type_prio, len(s.resolved_exception_ids), s.unresolved_exposure_paise)

        return min(closeable, key=score)

    def render(self) -> str:
        """Render a clean ASCII comparative dashboard."""
        w = 104
        lines = [
            "=" * w,
            "CLOSEPILOT — COUNTERFACTUAL CLOSE SIMULATION REPORT",
            f"Period: {self.period_id} | Total Period Value: {rupees(self.total_period_value_paise)}",
            f"Evaluated At: {self.evaluated_at}",
            "=" * w,
            "",
            f"[ACTUAL STATE] Baseline — Close Now:",
            f"  Verdict:             {self.actual_baseline.projected_verdict.value}",
            f"  Unresolved Exposure: {rupees(self.actual_baseline.unresolved_exposure_paise)}",
            f"  Material Exposure:   {rupees(self.actual_baseline.material_exposure_paise)}",
            f"  Blockers ({self.actual_baseline.blocker_count}):        "
            + (", ".join(self.actual_baseline.blockers[:3]) if self.actual_baseline.blockers else "None"),
            f"  Carry-Forward ({self.actual_baseline.carry_forward_count}):   "
            f"{rupees(self.actual_baseline.carry_forward_value_paise)}",
            "",
            "-" * w,
            "HYPOTHETICAL SCENARIOS (WHAT-IF ANALYSIS):",
            "-" * w,
            f"{'#':<3} {'Scenario':<26} {'State':<14} {'Projected Verdict':<26} {'Exposure (Δ)':<20} {'Blockers':<10}",
            "-" * w,
        ]

        # First row: baseline
        b = self.actual_baseline
        lines.append(
            f"{'0':<3} {'Close Now (Baseline)':<26} {'[ACTUAL]':<14} "
            f"{b.projected_verdict.value:<26} {rupees(b.unresolved_exposure_paise) + ' (+0)':<20} "
            f"{b.blocker_count:<10}"
        )

        for i, s in enumerate(self.scenarios, 1):
            sign = "+" if s.delta_unresolved_exposure_paise >= 0 else ""
            delta_exp = f"{rupees(s.unresolved_exposure_paise)} ({sign}{rupees(s.delta_unresolved_exposure_paise)})"
            delta_blk = f"{s.blocker_count} ({s.delta_blocker_count:+d})"
            state_label = f"[{s.state_type.value}]"
            lines.append(
                f"{i:<3} {s.description[:25]:<26} {state_label:<14} "
                f"{s.projected_verdict.value:<26} {delta_exp:<20} "
                f"{delta_blk:<10}"
            )

        lines.append("-" * w)
        rec = self.recommended_scenario()
        if rec and rec.scenario_id != self.actual_baseline.scenario_id:
            lines.extend([
                "RECOMMENDED OPERATIONAL ACTION:",
                f"  Scenario: {rec.description} ({rec.scenario_id})",
                f"  Projected Verdict:    {rec.projected_verdict.value} (Transition: {rec.verdict_transition})",
                f"  Remaining Exposure:   {rupees(rec.unresolved_exposure_paise)} (Δ {rupees(rec.delta_unresolved_exposure_paise)})",
                f"  Remaining Blockers:   {rec.blocker_count} (Δ {rec.delta_blocker_count:+d})",
                f"  Carry-Forward Items:  {rec.carry_forward_count} ({rupees(rec.carry_forward_value_paise)})",
                f"  Rationale:            {rec.explanation}",
            ])
        elif rec and rec.scenario_id == self.actual_baseline.scenario_id:
            lines.extend([
                "RECOMMENDED OPERATIONAL ACTION:",
                f"  Baseline state is already closeable: {self.actual_baseline.projected_verdict.value}.",
                f"  No operational interventions or wait horizons required to close.",
            ])
        else:
            lines.extend([
                "RECOMMENDED OPERATIONAL ACTION:",
                "  No simulated scenario achieves clean close. Escalation to Finance Controller required.",
            ])

        lines.append("=" * w)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        rec = self.recommended_scenario()
        return {
            "period_id": self.period_id,
            "total_period_value_paise": self.total_period_value_paise,
            "evaluated_at": self.evaluated_at,
            "actual_baseline": self.actual_baseline.to_dict(),
            "scenarios": [s.to_dict() for s in self.scenarios],
            "recommended_scenario_id": rec.scenario_id if rec else None,
        }


def _make_hypothetical_proven_finding(sid: str, net: int) -> Finding:
    """Construct a clean, valid postable PROVEN finding for a resolved settlement."""
    sp = SearchSpace(universe=100, members=frozenset((f"ORD-SIM-{sid}",)))
    sp.reductions.append(Reduction("simulation", 50, True, "counterfactual resolution"))
    proof = Proof(
        settlement_id=sid,
        order_ids=(f"ORD-SIM-{sid}",),
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


def _compute_source_checksum(
    findings: Sequence[Finding],
    judgements: Mapping[str, Judgement],
    exceptions: Sequence[Exception_],
    settlements: Sequence[Settlement] | None,
) -> str:
    """Compute a deterministic SHA-256 fingerprint over source inputs to guarantee immutability."""
    h = hashlib.sha256()

    for f in sorted(findings, key=lambda x: x.settlement_id):
        h.update(f.settlement_id.encode("utf-8"))
        h.update(f.verdict.value.encode("utf-8"))
        for p in f.proofs:
            h.update(str(p.net_paise).encode("utf-8"))

    for sid in sorted(judgements.keys()):
        j = judgements[sid]
        h.update(sid.encode("utf-8"))
        h.update(j.decision.value.encode("utf-8"))

    for e in sorted(exceptions, key=lambda x: x.id):
        h.update(e.id.encode("utf-8"))
        h.update(e.settlement_id.encode("utf-8"))
        h.update(str(e.unexplained_paise).encode("utf-8"))

    if settlements:
        for s in sorted(settlements, key=lambda x: x.settlement_id):
            h.update(s.settlement_id.encode("utf-8"))
            h.update(str(s.net_paise).encode("utf-8"))

    return h.hexdigest()


class CloseSimulator:
    """The Close Simulation Engine.

    Evaluates counterfactual scenarios answering:
        "What happens if I close now?"

    Guarantees:
    - Never mutates the source ledger or any caller inputs.
    - Evaluates all projected decisions through the authoritative `decide_period` kernel.
    - Distinguishes ACTUAL from HYPOTHETICAL states.
    """

    def __init__(
        self,
        period: Period,
        findings: Sequence[Finding],
        judgements: Mapping[str, Judgement],
        exceptions: Sequence[Exception_],
        materiality: MaterialityBound,
        settlements: Sequence[Settlement] | None = None,
    ):
        self._period = period
        # Freeze copies to prevent external mutation from affecting simulator
        self._findings = tuple(findings)
        self._judgements = dict(judgements)
        self._exceptions = tuple(exceptions)
        self._materiality = materiality
        self._settlements = tuple(settlements) if settlements is not None else None

        # Record cryptographic checksum of initial caller state
        self._initial_checksum = _compute_source_checksum(
            findings=findings,
            judgements=judgements,
            exceptions=exceptions,
            settlements=settlements,
        )

        # Baseline actual outcome
        self._actual_baseline = self._evaluate_scenario_internal(
            scenario=SimulationScenario(
                scenario_id="baseline_close_now",
                scenario_type=ScenarioType.CLOSE_NOW,
                description="Close Now (Actual Baseline)",
            ),
            state_type=SimulationState.ACTUAL,
            baseline_for_deltas=None,
        )

    @property
    def actual_baseline(self) -> SimulationOutcome:
        """The authoritative realized baseline state as of today."""
        return self._actual_baseline

    def verify_source_unmodified(
        self,
        current_findings: Sequence[Finding],
        current_judgements: Mapping[str, Judgement],
        current_exceptions: Sequence[Exception_],
        current_settlements: Sequence[Settlement] | None = None,
    ) -> bool:
        """Verify that caller's source data has not suffered any in-place mutation."""
        curr_checksum = _compute_source_checksum(
            findings=current_findings,
            judgements=current_judgements,
            exceptions=current_exceptions,
            settlements=current_settlements,
        )
        return curr_checksum == self._initial_checksum

    def simulate_close_now(self) -> SimulationOutcome:
        """Scenario 1: What happens if I close now? (Returns actual baseline)."""
        return self._actual_baseline

    def simulate_resolve_exceptions(
        self,
        exception_ids: Sequence[str],
        scenario_id: str = "resolve_selected_exceptions",
        description: str = "",
    ) -> SimulationOutcome:
        """Scenario 2: What happens if selected exceptions are resolved?"""
        ids_tuple = tuple(sorted(set(exception_ids)))
        desc = description or f"Resolve {len(ids_tuple)} selected exception(s)"
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            scenario_type=ScenarioType.RESOLVE_EXCEPTIONS,
            description=desc,
            resolved_exception_ids=ids_tuple,
        )
        return self.simulate_scenario(scenario)

    def simulate_carry_forward_immaterial(
        self,
        scenario_id: str = "carry_forward_immaterial",
        description: str = "Carry forward eligible immaterial exceptions",
    ) -> SimulationOutcome:
        """Scenario 3: What happens if immaterial exceptions are carried forward?"""
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            scenario_type=ScenarioType.CARRY_FORWARD_IMMATERIAL,
            description=description,
            carry_forward_immaterial=True,
        )
        return self.simulate_scenario(scenario)

    def simulate_clear_blocker(
        self,
        ref_ids: Sequence[str] = (),
        kinds: Sequence[BlockerKind] = (),
        scenario_id: str = "clear_hypothetical_blocker",
        description: str = "",
    ) -> SimulationOutcome:
        """Scenario 4: What happens if a hypothetical blocker is cleared/waived?"""
        refs_tuple = tuple(sorted(set(ref_ids)))
        kinds_tuple = tuple(sorted(set(kinds), key=lambda k: k.value))
        desc = description or f"Clear blocker(s) {refs_tuple or kinds_tuple}"
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            scenario_type=ScenarioType.CLEAR_BLOCKER,
            description=desc,
            cleared_blocker_refs=refs_tuple,
            cleared_blocker_kinds=kinds_tuple,
        )
        return self.simulate_scenario(scenario)

    def simulate_wait_predicted(
        self,
        horizon_days: int = 3,
        min_probability: float = 0.70,
        scenario_id: str = "wait_predicted_resolutions",
        description: str = "",
    ) -> SimulationOutcome:
        """Scenario 5: What happens if we wait for predicted natural resolutions?"""
        desc = description or f"Wait for predicted resolutions (T+{horizon_days}d, p>={min_probability:.0%})"
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            scenario_type=ScenarioType.WAIT_PREDICTED_RESOLUTIONS,
            description=desc,
            wait_horizon_days=horizon_days,
            min_prediction_prob=min_probability,
        )
        return self.simulate_scenario(scenario)

    def simulate_scenario(self, scenario: SimulationScenario) -> SimulationOutcome:
        """Evaluate an arbitrary counterfactual scenario strictly through authoritative controller."""
        return self._evaluate_scenario_internal(
            scenario=scenario,
            state_type=SimulationState.HYPOTHETICAL,
            baseline_for_deltas=self._actual_baseline,
        )

    def run_standard_suite(
        self,
        target_exception_ids: Sequence[str] | None = None,
        target_blocker_refs: Sequence[str] | None = None,
        wait_horizon_days: int = 3,
        min_probability: float = 0.70,
    ) -> SimulationReport:
        """Run the standard suite of 5 canonical scenarios in batch."""
        scenarios: list[SimulationOutcome] = []

        # Scenario 2: Resolve selected exceptions
        if target_exception_ids:
            res_ids = tuple(target_exception_ids)
        elif self._actual_baseline.structured_blockers:
            # Pick exceptions contributing to material exposure
            res_ids = tuple(sorted({
                b.ref_id for b in self._actual_baseline.structured_blockers
                if any(e.id == b.ref_id for e in self._exceptions)
            }))
        else:
            res_ids = tuple(e.id for e in self._exceptions[:2])

        if res_ids:
            scenarios.append(self.simulate_resolve_exceptions(
                exception_ids=res_ids,
                scenario_id="scenario_02_resolve_selected",
                description=f"Resolve {len(res_ids)} exception(s) ({', '.join(res_ids[:2])})",
            ))

        # Scenario 3: Carry forward immaterial
        scenarios.append(self.simulate_carry_forward_immaterial(
            scenario_id="scenario_03_carry_forward",
            description="Authorize carry-forward for qualifying immaterial exceptions",
        ))

        # Scenario 4: Clear hypothetical blocker
        blk_refs = tuple(target_blocker_refs) if target_blocker_refs else (
            tuple(self._actual_baseline.blockers[:1]) if self._actual_baseline.blockers else ()
        )
        if blk_refs:
            scenarios.append(self.simulate_clear_blocker(
                ref_ids=blk_refs,
                scenario_id="scenario_04_clear_blocker",
                description=f"Waive/resolve blocker ({blk_refs[0]})",
            ))

        # Scenario 5: Wait predicted resolutions
        scenarios.append(self.simulate_wait_predicted(
            horizon_days=wait_horizon_days,
            min_probability=min_probability,
            scenario_id="scenario_05_wait_predicted",
            description=f"Wait for predicted resolutions at T+{wait_horizon_days}d",
        ))

        total_paise = (
            sum(abs(s.net_paise) for s in self._settlements)
            if self._settlements
            else sum(f.proofs[0].net_paise for f in self._findings if f.proofs)
        )
        now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

        return SimulationReport(
            period_id=self._period.period_id,
            total_period_value_paise=total_paise,
            actual_baseline=self._actual_baseline,
            scenarios=tuple(scenarios),
            evaluated_at=now_str,
        )

    # --------------------------------------------------------------------------
    # Internal Candidate Projection and Authoritative Evaluation
    # --------------------------------------------------------------------------

    def _evaluate_scenario_internal(
        self,
        scenario: SimulationScenario,
        state_type: SimulationState,
        baseline_for_deltas: SimulationOutcome | None,
    ) -> SimulationOutcome:
        """Pure candidate projection builder and authoritative controller runner."""
        # 1. Start with shallow copies of source collections
        cand_findings = list(self._findings)
        cand_judgements = dict(self._judgements)
        cand_exceptions = list(self._exceptions)
        cand_settlements = list(self._settlements) if self._settlements is not None else None
        cand_materiality = scenario.hypothetical_materiality or self._materiality

        settlements_by_id = {s.settlement_id: s for s in cand_settlements} if cand_settlements else {}
        resolved_ids: set[str] = set(scenario.resolved_exception_ids)
        cleared_refs: set[str] = set(scenario.cleared_blocker_refs)
        cleared_kinds: set[BlockerKind] = set(scenario.cleared_blocker_kinds)

        # 2. Handle Scenario: WAIT_PREDICTED_RESOLUTIONS
        if scenario.scenario_type is ScenarioType.WAIT_PREDICTED_RESOLUTIONS or scenario.wait_horizon_days is not None:
            horizon = scenario.wait_horizon_days if scenario.wait_horizon_days is not None else 3
            min_p = scenario.min_prediction_prob
            preds = predict_batch(cand_exceptions, cand_settlements)
            for p in preds:
                if p.probability >= min_p and p.expected_horizon_days <= horizon:
                    resolved_ids.add(p.exception_id)

        # 3. Handle Scenario: RESOLVE_EXCEPTIONS
        if resolved_ids:
            cand_exceptions = [e for e in cand_exceptions if e.id not in resolved_ids]

            # For settlements whose exceptions have been resolved, ensure findings reflect resolution
            resolved_sids = {
                e.settlement_id for e in self._exceptions if e.id in resolved_ids
            }
            for sid in resolved_sids:
                # If no unresolved exceptions remain for this settlement
                if not any(e.settlement_id == sid for e in cand_exceptions):
                    s = settlements_by_id.get(sid)
                    s_val = abs(s.net_paise) if s else 0

                    # Check if settlement already has an existing proven finding
                    existing_findings = [f for f in cand_findings if f.settlement_id == sid]
                    if not existing_findings or any(f.verdict is not Verdict.PROVEN or not f.postable for f in existing_findings):
                        cand_findings = [f for f in cand_findings if f.settlement_id != sid]
                        # Determine settlement value
                        if s_val == 0 and existing_findings and existing_findings[0].proofs:
                            s_val = existing_findings[0].proofs[0].net_paise
                        elif s_val == 0:
                            ex_orig = next((e for e in self._exceptions if e.settlement_id == sid), None)
                            s_val = abs(ex_orig.amount_paise) if ex_orig else 1000

                        cand_findings.append(_make_hypothetical_proven_finding(sid, s_val))

        # 4. Handle Scenario: CLEAR_BLOCKER
        if cleared_refs or cleared_kinds:
            # Policy blocked clearance
            for sid, j in list(cand_judgements.items()):
                if j.decision is Decision.BLOCK:
                    if sid in cleared_refs or BlockerKind.POLICY_BLOCKED in cleared_kinds:
                        cand_judgements[sid] = Judgement(
                            decision=Decision.AUTO_POST,
                            expected_loss_paise=500,
                            p_error=0.005,
                            reasons=("Hypothetical clearance for close simulation",),
                        )

            # Missing settlement clearance
            if BlockerKind.MISSING_SETTLEMENT in cleared_kinds or any(
                ref in self._period.settlement_ids for ref in cleared_refs
            ):
                present_sids = {f.settlement_id for f in cand_findings}
                for sid in self._period.settlement_ids:
                    if sid not in present_sids and (sid in cleared_refs or BlockerKind.MISSING_SETTLEMENT in cleared_kinds):
                        s = settlements_by_id.get(sid)
                        s_val = abs(s.net_paise) if s else 1000
                        cand_findings.append(_make_hypothetical_proven_finding(sid, s_val))

            # Contradictory evidence clearance
            if BlockerKind.CONTRADICTORY_EVIDENCE in cleared_kinds:
                findings_by_id: dict[str, list[Finding]] = {}
                for f in cand_findings:
                    findings_by_id.setdefault(f.settlement_id, []).append(f)
                new_findings: list[Finding] = []
                for sid, flist in findings_by_id.items():
                    if len(flist) > 1:
                        s = settlements_by_id.get(sid)
                        s_val = abs(s.net_paise) if s else flist[0].proofs[0].net_paise if flist[0].proofs else 1000
                        new_findings.append(_make_hypothetical_proven_finding(sid, s_val))
                    else:
                        new_findings.extend(flist)
                cand_findings = new_findings

        # 5. Authoritative Evaluation through Close Controller kernel
        projected: PeriodVerdict = decide_period(
            period=self._period,
            findings=cand_findings,
            judgements=cand_judgements,
            exceptions=cand_exceptions,
            materiality=cand_materiality,
            settlements=cand_settlements,
        )

        # 6. Calculate total unresolved exposure from candidate state
        target_ids = self._period.settlement_ids
        period_findings = [f for f in cand_findings if f.settlement_id in target_ids]
        period_exceptions = [e for e in cand_exceptions if e.settlement_id in target_ids]
        period_settlements = [s for s in cand_settlements if s.settlement_id in target_ids] if cand_settlements else None

        cand_exposure: PeriodExposure = assess_exposure(
            findings=period_findings,
            exceptions=period_exceptions,
            target_settlement_ids=target_ids,
            settlements=period_settlements,
        )

        unresolved_exp = cand_exposure.total_exposure_paise
        mat_exp = projected.material_exposure_paise
        cf_items = projected.carry_forward_items
        cf_count = len(cf_items)
        cf_val = sum(item.exposure_paise for item in cf_items)
        blockers_tuple = projected.blockers
        structured_blockers_tuple = projected.structured_blockers

        # 7. Compute Deltas relative to baseline
        if baseline_for_deltas is None:
            # Baseline itself
            delta_unresolved = 0
            delta_material = 0
            delta_blockers = 0
            delta_cf = 0
            transition = f"BASELINE ({projected.decision.value})"
            explanation = (
                f"Actual baseline state: {projected.decision.value} with "
                f"{rupees(unresolved_exp)} unresolved exposure and {len(blockers_tuple)} blocker(s)."
            )
        else:
            delta_unresolved = unresolved_exp - baseline_for_deltas.unresolved_exposure_paise
            delta_material = mat_exp - baseline_for_deltas.material_exposure_paise
            delta_blockers = len(blockers_tuple) - baseline_for_deltas.blocker_count
            delta_cf = cf_count - baseline_for_deltas.carry_forward_count
            transition = f"{baseline_for_deltas.projected_verdict.value} → {projected.decision.value}"

            parts = [f"Verdict transitioned from {baseline_for_deltas.projected_verdict.value} to {projected.decision.value}."]
            if delta_unresolved < 0:
                parts.append(f"Unresolved exposure reduced by {rupees(abs(delta_unresolved))}.")
            elif delta_unresolved > 0:
                parts.append(f"Unresolved exposure increased by {rupees(delta_unresolved)}.")
            if delta_blockers < 0:
                parts.append(f"Blockers decreased by {abs(delta_blockers)}.")
            if cf_count > 0:
                parts.append(f"{cf_count} item(s) totalling {rupees(cf_val)} authorized for carry-forward.")
            explanation = " ".join(parts)

        is_closeable = projected.decision in (
            ReadinessDecision.READY_TO_CLOSE,
            ReadinessDecision.READY_WITH_CARRY_FORWARD,
        )

        return SimulationOutcome(
            scenario_id=scenario.scenario_id,
            scenario_type=scenario.scenario_type,
            description=scenario.description,
            state_type=state_type,
            projected_verdict=projected.decision,
            unresolved_exposure_paise=unresolved_exp,
            material_exposure_paise=mat_exp,
            blockers=blockers_tuple,
            structured_blockers=structured_blockers_tuple,
            carry_forward_count=cf_count,
            carry_forward_value_paise=cf_val,
            carry_forward_items=cf_items,
            delta_unresolved_exposure_paise=delta_unresolved,
            delta_material_exposure_paise=delta_material,
            delta_blocker_count=delta_blockers,
            delta_carry_forward_count=delta_cf,
            verdict_transition=transition,
            resolved_exception_ids=tuple(sorted(resolved_ids)),
            cleared_blocker_refs=tuple(sorted(cleared_refs)),
            is_closeable=is_closeable,
            explanation=explanation,
        )


def simulate_close(
    period: Period,
    findings: Sequence[Finding],
    judgements: Mapping[str, Judgement],
    exceptions: Sequence[Exception_],
    materiality: MaterialityBound,
    settlements: Sequence[Settlement] | None = None,
    scenarios: Sequence[SimulationScenario] | None = None,
    wait_horizon_days: int = 3,
    min_probability: float = 0.70,
) -> SimulationReport:
    """Convenience top-level entry point for counterfactual close simulation.

    Takes the current period and evaluates baseline 'Close Now' plus standard or custom scenarios.
    Returns a multi-scenario comparative simulation report.
    """
    simulator = CloseSimulator(
        period=period,
        findings=findings,
        judgements=judgements,
        exceptions=exceptions,
        materiality=materiality,
        settlements=settlements,
    )

    if scenarios is None:
        return simulator.run_standard_suite(
            wait_horizon_days=wait_horizon_days,
            min_probability=min_probability,
        )

    outcomes = tuple(simulator.simulate_scenario(s) for s in scenarios)
    total_paise = (
        sum(abs(s.net_paise) for s in settlements)
        if settlements
        else sum(f.proofs[0].net_paise for f in findings if f.proofs)
    )
    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return SimulationReport(
        period_id=period.period_id,
        total_period_value_paise=total_paise,
        actual_baseline=simulator.actual_baseline,
        scenarios=outcomes,
        evaluated_at=now_str,
    )
