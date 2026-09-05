"""CLOSEPILOT — Continuous AI Finance Controller.

The controller layer ABOVE the reconciliation kernel.

    attest/    the trusted reconciliation engine — deterministic, frozen core
    closepilot/    the close-readiness controller — imports from attest, never the reverse

The kernel owns financial truth: amounts, matching, settlement verification,
tax, fees, ledger state, close authorization. AI may only investigate, retrieve
evidence, explain, summarize, predict resolution, compare scenarios, draft
close memos, and route cases for human review.

The core question this package answers:

    "Can this financial period be safely closed?"
"""

from __future__ import annotations

import sys as _sys

if _sys.version_info < (3, 11):
    raise RuntimeError(
        f"CLOSEPILOT needs Python 3.11 or newer; this is "
        f"{_sys.version_info.major}.{_sys.version_info.minor}.")

from closepilot.lineage import (
    EdgeRelationship,
    FinancialLineageGraph,
    LineageDefect,
    LineageEdge,
    LineageNode,
    LineageStage,
    MissingEvidenceRecord,
    build_lineage,
)
from closepilot.predictor import (
    ConfidenceTier,
    ResolutionFeatures,
    ResolutionPrediction,
    ResolutionRouting,
    extract_features,
    predict_batch,
    predict_resolution,
)
from closepilot.review_queue import (
    HumanActionRecord,
    HumanActionType,
    HumanReviewItem,
    HumanReviewQueue,
    ReviewItemStatus,
    build_review_queue,
    compute_priority_score,
)
from closepilot.dashboard import (
    create_dashboard_server,
    run_dashboard,
)
from closepilot.investigator import (
    AIInvestigator,
    EvidenceGroundingValidator,
    InvestigationReport,
    InvestigationStatus,
    InvestigationToolRegistry,
    PromptInjectionGuard,
    ToolCallRecord,
    ToolName,
    ToolSelectionError,
)
from closepilot.simulator import (
    CloseSimulator,
    ScenarioType,
    SimulationOutcome,
    SimulationReport,
    SimulationScenario,
    SimulationState,
    simulate_close,
)

__all__ = [
    "ResolutionFeatures",
    "ResolutionPrediction",
    "ResolutionRouting",
    "ConfidenceTier",
    "extract_features",
    "predict_resolution",
    "predict_batch",
    "CloseSimulator",
    "SimulationState",
    "ScenarioType",
    "SimulationScenario",
    "SimulationOutcome",
    "SimulationReport",
    "simulate_close",
    "LineageStage",
    "EdgeRelationship",
    "LineageNode",
    "LineageEdge",
    "MissingEvidenceRecord",
    "LineageDefect",
    "FinancialLineageGraph",
    "build_lineage",
    "ReviewItemStatus",
    "HumanActionType",
    "HumanActionRecord",
    "HumanReviewItem",
    "compute_priority_score",
    "HumanReviewQueue",
    "build_review_queue",
    "AIInvestigator",
    "InvestigationReport",
    "InvestigationStatus",
    "InvestigationToolRegistry",
    "ToolName",
    "ToolCallRecord",
    "PromptInjectionGuard",
    "EvidenceGroundingValidator",
    "ToolSelectionError",
    "create_dashboard_server",
    "run_dashboard",
]
