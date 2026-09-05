/**
 * CLOSEPILOT — Controller Dashboard Client
 * 
 * Consumes deterministic ClosePilot APIs.
 * Enforces visual distinction between:
 * - FACT (Green/Slate)
 * - PREDICTION (Purple)
 * - RECOMMENDATION (Amber)
 * - HYPOTHETICAL SIMULATION (Dashed Orange)
 */

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  loadReadiness();
  loadWhyBlocked();
  loadMateriality();
  loadPredictions();
  loadReviewQueue();
  initSimulation();
  initEvidenceInspector();
  initModal();
});

// Tab Navigation
function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

      btn.classList.add("active");
      const target = btn.getAttribute("data-tab");
      const content = document.getElementById(target);
      if (content) content.classList.add("active");
    });
  });
}

// 1. Primary Verdict & Metric Ribbon (CAN I CLOSE?)
async function loadReadiness() {
  try {
    const res = await fetch("/api/closepilot/readiness");
    const data = await res.json();

    document.getElementById("period-name").textContent = `Period: ${data.period_id}`;

    const verdictCard = document.getElementById("verdict-card");
    const verdictTitle = document.getElementById("verdict-title");
    const verdictSubtitle = document.getElementById("verdict-subtitle");
    const impactText = document.getElementById("verdict-impact-text");

    // Clear previous verdict classes
    verdictCard.className = "verdict-card";

    if (data.decision === "READY_TO_CLOSE") {
      verdictCard.classList.add("verdict-ready");
      verdictTitle.textContent = "READY TO CLOSE";
      verdictSubtitle.textContent = "All financial invariants verified. Zero material unresolved exposure and zero active safety blockers.";
    } else if (data.decision === "READY_WITH_CARRY_FORWARD") {
      verdictCard.classList.add("verdict-carry-forward");
      verdictTitle.textContent = "READY WITH CARRY-FORWARD";
      verdictSubtitle.textContent = `${data.carry_forward_count} immaterial exception(s) authorized to carry forward (${data.carry_forward_exposure_rupees}). Zero active safety blockers.`;
    } else {
      verdictCard.classList.add("verdict-blocked");
      verdictTitle.textContent = "BLOCKED";
      verdictSubtitle.textContent = "Close authorization is BLOCKED by active safety rules and material unresolved exposure.";
    }

    impactText.textContent = data.close_impact || `Close authorization is BLOCKED by active safety rules and material unresolved exposure. [${data.active_blocker_rule_instances}] active blocker rule instances, [${data.unique_blocked_exceptions}] unique blocked exceptions, [${data.unique_blocked_settlements}] unique blocked settlements.`;

    // Metrics
    document.getElementById("metric-total-value").textContent = data.total_financial_value_rupees;
    document.getElementById("metric-reconciled-value").textContent = data.reconciled_value_rupees;
    const pct = data.total_financial_value_paise > 0 
      ? ((data.reconciled_value_paise / data.total_financial_value_paise) * 100).toFixed(1)
      : "100.0";
    document.getElementById("metric-reconciled-pct").textContent = `${pct}% Proven`;

    document.getElementById("metric-unresolved-exposure").textContent = data.net_unresolved_exposure_rupees || data.unresolved_exposure_rupees;
    document.getElementById("metric-exception-count").textContent = `${data.exception_count} exceptions`;

    document.getElementById("metric-materiality-threshold").textContent = data.materiality_threshold_rupees;
    if (document.getElementById("metric-material-exposure-subtext")) {
      document.getElementById("metric-material-exposure-subtext").textContent = `Material: ${data.material_exposure_rupees}`;
    }

    document.getElementById("metric-blocker-count").textContent = data.active_blocker_rule_instances !== undefined ? data.active_blocker_rule_instances : data.blocker_count;
    if (document.getElementById("metric-blocked-exceptions")) {
      document.getElementById("metric-blocked-exceptions").textContent = data.unique_blocked_exceptions !== undefined ? data.unique_blocked_exceptions : 0;
    }
    if (document.getElementById("metric-blocked-settlements")) {
      document.getElementById("metric-blocked-settlements").textContent = data.unique_blocked_settlements !== undefined ? data.unique_blocked_settlements : 0;
    }
    if (document.getElementById("metric-gross-exposure")) {
      document.getElementById("metric-gross-exposure").textContent = data.gross_contested_claim_exposure_rupees || "₹0.00";
    }
    if (document.getElementById("metric-predicted-resolves")) {
      document.getElementById("metric-predicted-resolves").textContent = data.likely_resolutions_count;
    }

  } catch (err) {
    console.error("Failed to load readiness:", err);
  }
}

// 2. Tab 1: Why can't I close?
async function loadWhyBlocked() {
  try {
    const res = await fetch("/api/closepilot/why-blocked");
    const data = await res.json();
    const container = document.getElementById("blockers-list");

    if (!data.blockers || data.blockers.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="padding: 24px; text-align: center; color: var(--fact-color);">
          ✓ No active blockers. All safety invariants pass.
        </div>`;
      return;
    }

    container.innerHTML = data.blockers.map(b => `
      <div class="blocker-item-card">
        <div class="blocker-header">
          <span class="blocker-kind">[${b.kind}]</span>
          <span class="blocker-ref">Ref: ${b.ref_id}</span>
        </div>
        <div class="blocker-reason">${b.reason}</div>
        <div class="blocker-remedy">
          <strong>Remedy:</strong> ${b.remedy}
        </div>
      </div>
    `).join("");

  } catch (err) {
    console.error("Failed to load blockers:", err);
  }
}

// 3. Tab 2: What is financially material?
async function loadMateriality() {
  try {
    const res = await fetch("/api/closepilot/materiality");
    const data = await res.json();

    const policyBox = document.getElementById("materiality-policy-box");
    policyBox.innerHTML = `
      <div style="display: flex; gap: 30px; flex-wrap: wrap; font-size: 13px;">
        <div><strong>Policy Version:</strong> ${data.policy_version}</div>
        <div><strong>Threshold:</strong> ${data.threshold_bps} bps (1.00%)</div>
        <div><strong>Effective Limit:</strong> <span class="text-amber">${data.effective_threshold_rupees}</span></div>
        <div><strong>Floor:</strong> ${data.floor_rupees}</div>
        <div><strong>Ceiling:</strong> ${data.ceiling_rupees}</div>
        <div><strong>Net Unresolved Exposure:</strong> ${data.net_unresolved_exposure_rupees || data.total_unresolved_rupees}</div>
      </div>
    `;

    const tableBody = document.getElementById("materiality-table-body");
    tableBody.innerHTML = data.exceptions.map(ex => `
      <tr>
        <td><strong>${ex.exception_id}</strong></td>
        <td>${ex.settlement_id}</td>
        <td><span class="font-mono">${ex.exposure_rupees}</span></td>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="background: var(--bg-main); width: 100px; height: 6px; border-radius: 3px; overflow: hidden;">
              <div style="background: ${ex.is_individually_material ? 'var(--blocked-color)' : 'var(--fact-color)'}; width: ${Math.min(100, ex.percentage_of_allowable)}%; height: 100%;"></div>
            </div>
            <span>${ex.percentage_of_allowable}%</span>
          </div>
        </td>
        <td>
          ${ex.is_individually_material 
            ? '<span class="badge badge-fact" style="color: var(--blocked-color); border-color: var(--blocked-border);">MATERIAL</span>' 
            : '<span class="badge badge-fact" style="color: var(--fact-color); border-color: var(--fact-border);">IMMATERIAL</span>'}
        </td>
      </tr>
    `).join("");

  } catch (err) {
    console.error("Failed to load materiality:", err);
  }
}

// 4. Tab 3: Simulate closing now
function initSimulation() {
  const scenarioBtns = document.querySelectorAll(".scenario-btn");
  scenarioBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      scenarioBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const scenario = btn.getAttribute("data-scenario");
      runSimulation(scenario);
    });
  });

  // Run initial simulation
  runSimulation("CLOSE_NOW");
}

async function runSimulation(scenarioType) {
  try {
    const res = await fetch("/api/closepilot/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_type: scenarioType }),
    });
    const data = await res.json();

    const actual = data.actual_state;
    const proj = data.hypothetical_state;

    // Actual
    document.getElementById("sim-actual-verdict").textContent = actual.decision;
    document.getElementById("sim-actual-verdict").style.color = actual.decision === "BLOCKED" ? "var(--blocked-color)" : "var(--fact-color)";
    const actExp = actual.net_unresolved_exposure_paise !== undefined ? actual.net_unresolved_exposure_paise : actual.unresolved_exposure_paise;
    document.getElementById("sim-actual-exposure").textContent = `₹${(actExp / 100).toFixed(2)}`;
    document.getElementById("sim-actual-blockers").textContent = actual.active_blocker_rule_instances !== undefined ? actual.active_blocker_rule_instances : actual.blocker_count;
    document.getElementById("sim-actual-cf").textContent = actual.carry_forward_count;

    // Projected
    const projVerdict = document.getElementById("sim-proj-verdict");
    projVerdict.textContent = proj.decision;
    if (proj.decision === "READY_TO_CLOSE") {
      projVerdict.style.color = "var(--ready-color)";
    } else if (proj.decision === "READY_WITH_CARRY_FORWARD") {
      projVerdict.style.color = "var(--carry-color)";
    } else {
      projVerdict.style.color = "var(--blocked-color)";
    }

    const projExp = proj.net_unresolved_exposure_paise !== undefined ? proj.net_unresolved_exposure_paise : proj.unresolved_exposure_paise;
    document.getElementById("sim-proj-exposure").textContent = `₹${(projExp / 100).toFixed(2)}`;
    document.getElementById("sim-proj-blockers").textContent = proj.active_blocker_rule_instances !== undefined ? proj.active_blocker_rule_instances : proj.blocker_count;
    document.getElementById("sim-proj-cf").textContent = proj.carry_forward_count;

    document.getElementById("simulation-notes-text").textContent = 
      `Scenario: ${data.scenario_name} — Simulated ${data.simulated_at}. Source financial truth remains strictly unmodified.`;

  } catch (err) {
    console.error("Simulation failed:", err);
  }
}

// 5. Tab 4: What will likely resolve?
async function loadPredictions() {
  try {
    const res = await fetch("/api/closepilot/predictions");
    const data = await res.json();
    const tableBody = document.getElementById("predictions-table-body");

    tableBody.innerHTML = data.predictions.map(p => `
      <tr>
        <td><strong>${p.exception_id}</strong></td>
        <td>
          <span class="badge badge-prediction">${(p.probability * 100).toFixed(0)}%</span>
        </td>
        <td>T+${p.expected_horizon_days}d</td>
        <td>${p.confidence}</td>
        <td><span class="badge badge-recommendation">${p.recommended_routing}</span></td>
        <td style="color: var(--text-secondary);">${p.rationale}</td>
      </tr>
    `).join("");

  } catch (err) {
    console.error("Failed to load predictions:", err);
  }
}

// 6. Tab 5: Show evidence & AI investigation
function initEvidenceInspector() {
  const btn = document.getElementById("btn-run-investigation");
  if (btn) {
    btn.addEventListener("click", () => {
      const select = document.getElementById("evidence-target-select");
      const targetId = select.value;
      runInvestigation(targetId);
    });
  }
}

async function runInvestigation(targetId) {
  const chainBox = document.getElementById("lineage-chain-box");
  const reportBox = document.getElementById("ai-report-box");

  chainBox.innerHTML = `Tracing causal lineage for ${targetId}...`;
  reportBox.innerHTML = `Invoking Advisory AI Investigator for ${targetId}...`;

  try {
    const res = await fetch(`/api/closepilot/evidence?id=${encodeURIComponent(targetId)}`);
    const data = await res.json();

    // Lineage Chain
    if (data.lineage_nodes && data.lineage_nodes.length > 0) {
      chainBox.innerHTML = data.lineage_nodes.map((n, i) => `
        <div style="margin-bottom: 10px; padding: 8px 12px; background: var(--bg-card); border-radius: 6px; border-left: 3px solid var(--fact-color);">
          <div style="font-size: 11px; color: var(--text-muted);">Stage ${i+1}: ${n.stage}</div>
          <div style="font-weight: 600;">${n.label}</div>
          <div style="font-size: 12px; color: var(--text-secondary);">${n.node_id}</div>
        </div>
      `).join("");
    } else {
      chainBox.innerHTML = `<div>No backward causal trace available for ${targetId}.</div>`;
    }

    // AI Report
    const ai = data.ai_investigation;
    if (ai) {
      reportBox.innerHTML = `
        <div style="margin-bottom: 12px;">
          <span class="badge ${ai.is_grounded ? 'badge-fact' : 'badge-recommendation'}">${ai.status}</span>
          <span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">Grounded: ${ai.is_grounded}</span>
        </div>
        <div style="font-weight: 600; margin-bottom: 8px;">Summary:</div>
        <p style="color: var(--text-primary); margin-bottom: 12px; font-size: 13px;">${ai.summary}</p>
        <div style="font-weight: 600; margin-bottom: 8px;">Discrepancy Explanation:</div>
        <p style="color: var(--text-secondary); margin-bottom: 12px; font-size: 13px;">${ai.discrepancy_explanation}</p>
        <div style="font-weight: 600; margin-bottom: 8px;">Grounded Citations:</div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;">
          ${ai.cited_evidence_refs.map(r => `<span class="badge badge-fact">${r}</span>`).join("")}
        </div>
        <div style="font-size: 11px; color: var(--text-muted);">Financial Truth Mutated: ${ai.financial_truth_mutated} (Strict Guarantee)</div>
      `;
    }

  } catch (err) {
    console.error("Investigation failed:", err);
  }
}

// 7. Tab 6: Human Review Queue & Audit Action Modal
async function loadReviewQueue() {
  try {
    const res = await fetch("/api/closepilot/review-queue");
    const data = await res.json();

    const container = document.getElementById("queue-items-container");
    container.innerHTML = data.items.map(item => `
      <div class="queue-item-card">
        <div class="queue-item-meta">
          <div class="queue-item-title">
            <span>${item.exception_id}</span>
            <span class="badge badge-fact">${item.severity}</span>
            <span class="badge badge-prediction">Score: ${item.priority_score}</span>
            <span class="badge ${item.current_status === 'ACTIONED' ? 'badge-fact' : 'badge-recommendation'}">${item.current_status}</span>
          </div>
          <div class="queue-item-desc">${item.settlement_id} — Exposure: ₹${(item.exposure / 100).toFixed(2)} (${item.reason})</div>
          <div class="queue-item-impact">Impact: ${item.close_impact} | Rec: ${item.recommended_action}</div>
        </div>
        <div class="queue-item-actions">
          <button class="btn btn-secondary" onclick="openActionModal('${item.exception_id}')">Review / Action</button>
        </div>
      </div>
    `).join("");

    // Audit log
    const auditContainer = document.getElementById("audit-log-container");
    if (data.audit_log && data.audit_log.length > 0) {
      auditContainer.innerHTML = data.audit_log.map(a => `
        <div style="padding: 10px; background: var(--bg-card); border-radius: 6px; margin-bottom: 8px; border-left: 3px solid var(--fact-color);">
          <div style="font-size: 11px; color: var(--text-muted); display: flex; justify-content: space-between;">
            <span>${a.action_type}</span>
            <span>${a.timestamp}</span>
          </div>
          <div style="font-weight: 600; font-size: 13px;">${a.exception_id} — Reviewed by: ${a.reviewer}</div>
          <div style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Justification: ${a.justification}</div>
          <div style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); margin-top: 4px;">Hash: ${a.action_hash.slice(0, 16)}...</div>
        </div>
      `).join("");
    }

  } catch (err) {
    console.error("Failed to load review queue:", err);
  }
}

function initModal() {
  const closeBtn = document.getElementById("btn-modal-close");
  const cancelBtn = document.getElementById("btn-modal-cancel");
  const submitBtn = document.getElementById("btn-modal-submit");

  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
  if (submitBtn) submitBtn.addEventListener("click", submitAction);
}

window.openActionModal = function(exceptionId) {
  document.getElementById("modal-exception-id").value = exceptionId;
  document.getElementById("modal-title").textContent = `Record Action for ${exceptionId}`;
  document.getElementById("action-modal").classList.remove("hidden");
};

function closeModal() {
  document.getElementById("action-modal").classList.add("hidden");
}

async function submitAction() {
  const exceptionId = document.getElementById("modal-exception-id").value;
  const actionType = document.getElementById("modal-action-type").value;
  const reviewer = document.getElementById("modal-reviewer").value;
  const justification = document.getElementById("modal-justification").value;

  if (!reviewer || !justification) {
    alert("Reviewer ID and Justification are required for auditable human actions.");
    return;
  }

  try {
    const res = await fetch("/api/closepilot/review-action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exception_id: exceptionId,
        action_type: actionType,
        reviewer: reviewer,
        justification: justification,
      }),
    });
    const result = await res.json();
    if (result.success) {
      closeModal();
      loadReviewQueue();
    } else {
      alert(`Action failed: ${result.error}`);
    }
  } catch (err) {
    alert(`Request error: ${err}`);
  }
}
