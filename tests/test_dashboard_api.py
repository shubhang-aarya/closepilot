"""Tests for ClosePilot Phase 4: Controller Dashboard APIs.

Verifies:
1. Core question: CAN I CLOSE? endpoint returns complete financial dimensions.
2. Interaction 1: "Why can't I close?" returns structured blockers and remedies.
3. Interaction 2: "What is financially material?" returns policy boundaries.
4. Interaction 3: "Simulate closing now" runs scenarios without mutating actual state.
5. Interaction 4: "What will likely resolve?" returns prediction timeline.
6. Interaction 5: "Show evidence" returns causal lineage and grounded AI report.
7. Interaction 6: "Review exceptions" supports recording auditable actions.
8. Static asset delivery for index.html, style.css, and app.js.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

import pytest

from closepilot.dashboard import create_dashboard_server


@pytest.fixture(scope="module")
def dashboard_client():
    """Start the dashboard server on an ephemeral local port for testing."""
    server = create_dashboard_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    def get_json(path: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{base_url}{path}") as resp:
            assert resp.status == 200
            return json.loads(resp.read().decode("utf-8"))

    def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            return json.loads(resp.read().decode("utf-8"))

    def get_raw(path: str) -> bytes:
        with urllib.request.urlopen(f"{base_url}{path}") as resp:
            assert resp.status == 200
            return resp.read()

    yield {
        "get_json": get_json,
        "post_json": post_json,
        "get_raw": get_raw,
        "base_url": base_url,
    }

    server.shutdown()


class TestDashboardAPI:
    """Test suite for the Controller Dashboard REST endpoints."""

    def test_can_i_close_readiness_endpoint(self, dashboard_client) -> None:
        """Primary screen must provide decision, financial values, exposures, and impact."""
        data = dashboard_client["get_json"]("/api/closepilot/readiness")

        assert "period_id" in data
        assert data["period_id"] == "P-2026-08"
        assert data["decision"] in ("BLOCKED", "READY_WITH_CARRY_FORWARD", "READY_TO_CLOSE")
        assert "can_close" in data
        assert isinstance(data["can_close"], bool)

        # Financial dimensions
        assert data["total_financial_value_paise"] > 0
        assert "total_financial_value_rupees" in data
        assert "reconciled_value_paise" in data
        assert "unresolved_exposure_paise" in data
        assert "material_exposure_paise" in data
        assert "materiality_threshold_paise" in data
        assert "blocker_count" in data
        assert "carry_forward_count" in data
        assert "exception_count" in data
        assert "likely_resolutions_count" in data
        assert "close_impact" in data

    def test_why_cant_i_close_endpoint(self, dashboard_client) -> None:
        """Interaction 1: Why can't I close? must return active blockers and remedies."""
        data = dashboard_client["get_json"]("/api/closepilot/why-blocked")

        assert "is_blocked" in data
        assert "total_blockers" in data
        assert "blockers" in data
        assert isinstance(data["blockers"], list)

        if data["total_blockers"] > 0:
            first_blocker = data["blockers"][0]
            assert "kind" in first_blocker
            assert "ref_id" in first_blocker
            assert "reason" in first_blocker
            assert "remedy" in first_blocker
            assert len(first_blocker["remedy"]) > 0

    def test_what_is_material_endpoint(self, dashboard_client) -> None:
        """Interaction 2: What is financially material? must return policy limits and exceptions."""
        data = dashboard_client["get_json"]("/api/closepilot/materiality")

        assert "policy_version" in data
        assert "threshold_bps" in data
        assert "effective_threshold_rupees" in data
        assert "exceptions" in data
        assert len(data["exceptions"]) > 0

        first_ex = data["exceptions"][0]
        assert "exception_id" in first_ex
        assert "exposure_paise" in first_ex
        assert "percentage_of_allowable" in first_ex
        assert "is_individually_material" in first_ex

    def test_simulate_closing_now_endpoint(self, dashboard_client) -> None:
        """Interaction 3: Simulate closing now must return hypothetical state without mutating actual."""
        payload = {"scenario_type": "CARRY_FORWARD_IMMATERIAL"}
        data = dashboard_client["post_json"]("/api/closepilot/simulate", payload)

        assert "actual_state" in data
        assert "hypothetical_state" in data
        assert "is_counterfactual" in data
        assert data["is_counterfactual"] is True

        # Assert distinction
        actual = data["actual_state"]
        proj = data["hypothetical_state"]
        assert "decision" in actual
        assert "decision" in proj
        assert "unresolved_exposure_paise" in actual
        assert "unresolved_exposure_paise" in proj

    def test_what_will_likely_resolve_endpoint(self, dashboard_client) -> None:
        """Interaction 4: What will likely resolve? must return resolution predictions."""
        data = dashboard_client["get_json"]("/api/closepilot/predictions")

        assert "total_predictions" in data
        assert "predictions" in data
        assert len(data["predictions"]) > 0

        p = data["predictions"][0]
        assert "exception_id" in p
        assert "probability" in p
        assert 0.0 <= p["probability"] <= 1.0
        assert "expected_horizon_days" in p
        assert "confidence" in p
        assert "recommended_routing" in p

    def test_show_evidence_endpoint(self, dashboard_client) -> None:
        """Interaction 5: Show evidence must return causal lineage and grounded AI investigation."""
        data = dashboard_client["get_json"]("/api/closepilot/evidence?id=EX-00004")

        assert data["target_id"] == "EX-00004"
        assert "lineage_nodes" in data
        assert "ai_investigation" in data

        ai = data["ai_investigation"]
        assert ai["target_id"] == "EX-00004"
        assert "is_grounded" in ai
        assert ai["financial_truth_mutated"] is False

    def test_review_queue_and_action_recording_endpoint(self, dashboard_client) -> None:
        """Interaction 6: Review exceptions must allow recording explicit auditable human actions."""
        # 1. Fetch initial queue
        queue_data = dashboard_client["get_json"]("/api/closepilot/review-queue")
        assert "total_items" in queue_data
        assert "items" in queue_data
        assert len(queue_data["items"]) > 0

        target_ex = queue_data["items"][0]["exception_id"]

        # 2. Record explicit action
        action_payload = {
            "exception_id": target_ex,
            "action_type": "APPROVE_MANUAL_ADJUSTMENT",
            "reviewer": "chief.controller@company.com",
            "justification": "Approved manual fee adjustment from audit dashboard",
            "evidence_ref": "DASH-AUDIT-001",
        }
        action_result = dashboard_client["post_json"]("/api/closepilot/review-action", action_payload)
        assert action_result["success"] is True
        assert "audit_record" in action_result
        assert action_result["audit_record"]["reviewer"] == "chief.controller@company.com"
        assert len(action_result["audit_record"]["action_hash"]) == 64

    def test_static_ui_assets_delivery(self, dashboard_client) -> None:
        """Static assets index.html, style.css, and app.js must be cleanly served."""
        html = dashboard_client["get_raw"]("/").decode("utf-8")
        assert "CAN I CLOSE?" in html
        assert "CLOSEPILOT" in html
        assert "ontology-legend" in html

        css = dashboard_client["get_raw"]("/style.css").decode("utf-8")
        assert "verdict-blocked" in css
        assert "badge-fact" in css

        js = dashboard_client["get_raw"]("/app.js").decode("utf-8")
        assert "loadReadiness" in js
        assert "runSimulation" in js
