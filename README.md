# ClosePilot

## Continuous AI Finance Controller

### Can I close?

**ClosePilot** is an audit-ready, continuous financial close controller built on top of the **ATTEST** mathematical verification kernel. It answers the question every financial controller and CFO needs to answer at period close:

> **Can I safely close the books?**

When the answer is yes, ClosePilot can issue a tamper-evident **Close Certificate**. When the answer is no, it explains why: which safety rules fired, how much unresolved exposure remains, what is financially material, what is likely to resolve, and what requires human action.

### 🔗 Links

- **Live Demo:** https://closepilot-r5my.onrender.com
- **GitHub Repository:** https://github.com/shubhang-aarya/closepilot

The system supports an accelerated native verification path and a pure-Python portable path.

---

## The Problem

At period close, finance teams may have hundreds or thousands of batched settlements, fees, taxes, and bank credits. In multi-order payment systems such as Razorpay, a single settlement can represent many underlying transactions rather than a simple 1:1 match.

1. **Combinatorial ambiguity:** Multiple subsets of orders can sometimes sum to the same settlement amount. A naïve matcher can choose the wrong explanation even when the numbers appear to balance.
2. **Binary close decisions:** Teams need more than a list of mismatches. They need to know whether an unresolved amount is material, whether it can be carried forward, and what is actually blocking the close.
3. **Auditability:** A close decision must be explainable. Controllers need evidence for what was verified, what remained unresolved, which controls fired, and why the final verdict was reached.

---

## The Solution: ClosePilot Architecture

ClosePilot orchestrates the end-to-end close workflow, using **ATTEST** as the trusted mathematical verification kernel underneath:

```text
Financial Events (Gateway Settlements, Orders, Bank Credits)
              ↓
Financial Truth (Source Records & Financial Invariants)
              ↓
Reconciliation / Verification (ATTEST Proof Engine)
              ↓
Exception Registry (Timing, Ambiguity, Missing Data, etc.)
              ↓
Financial Exposure (Net Unresolved vs. Gross Contested Claims)
              ↓
Materiality (Policy Thresholds, Floors & Ceilings)
              ↓
Resolution Prediction (Expected T+1 / T+2 Clearing)
              ↓
AI Investigation (Evidence-Grounded Advisory Layer)
              ↓
Counterfactual Simulation (Non-Mutating What-If Analysis)
              ↓
Human Review (Prioritized Controller Queue)
              ↓
Close Controller
              ↓
    ┌─────────────────────────┬─────────────────────────┐
    ↓                         ↓                         ↓
READY_TO_CLOSE    READY_WITH_CARRY_FORWARD           BLOCKED
    └─────────────────────────┬─────────────────────────┘
                              ↓
              Tamper-Evident Close Certificate (SHA-256)
```

---

## Core Financial Semantics

ClosePilot keeps accounting definitions explicit and separate from diagnostic metrics.

### 1. Net vs. Gross Exposure

- **Net Unresolved Exposure (`net_unresolved_exposure_paise`)** is the amount that remains economically unresolved or unverified. This is the metric used for close readiness, materiality, and balance-sheet risk.
- ClosePilot enforces the conservation relationship:

  `verified value + net unresolved exposure = total period value`

- **Gross Contested Claim Exposure (`gross_contested_claim_exposure_paise`)** is a diagnostic ambiguity metric that aggregates candidate claims across competing hypotheses. Because those hypotheses may overlap, gross contested exposure can exceed the portfolio value. It is **not** treated as balance-sheet exposure.

### 2. Blockers vs. Affected Entities

ClosePilot distinguishes between a rule firing and the financial entity affected by it:

- **Active Blocker Rule Instances:** individual safety rule violations that fired.
- **Unique Blocked Exceptions:** distinct exception records affected by blockers.
- **Unique Blocked Settlements:** distinct settlement batches affected by blockers.

This prevents a dashboard count of rule firings from being mistaken for the number of underlying problems.

### 3. Close Readiness Verdicts

- **`READY_TO_CLOSE`** — no active blockers, no material unresolved exposure, and financial invariants pass.
- **`READY_WITH_CARRY_FORWARD`** — no active blockers and all remaining exposure is within policy materiality limits, with every carried-forward exception explicitly listed.
- **`BLOCKED`** — active safety blockers exist or unresolved exposure exceeds the materiality threshold.

### 4. Epistemic Separation

ClosePilot separates four types of information across the product:

- **`FACT`** — proven by the deterministic verification and ledger controls.
- **`PREDICTION`** — statistical forecast of likely resolution timing.
- **`RECOMMENDATION`** — advisory guidance for investigation or review prioritization.
- **`HYPOTHETICAL SIMULATION`** — a non-mutating what-if result.

---

## The AI Advisory Boundary

ClosePilot deliberately separates investigation from financial authority.

| Role | Component | Authority |
|---|---|---|
| **Advisor** | AI Investigator & Resolution Predictor | Investigate, retrieve evidence, summarize, predict, recommend. **Advisory only.** |
| **Verifier** | ATTEST Kernel | Reconstruct candidate solutions, verify subset sums in integer paise, and enforce financial invariants. |
| **Policy** | Materiality & Close Controller | Apply safety rules, materiality thresholds, and close-readiness policy. |
| **Ledger** | Double-Entry Journal | Record final balanced postings with audit trails. |

> **AI Honesty Disclosure:** The current ClosePilot AI Investigator is a **local, deterministic advisory heuristic engine**. It is not an external cloud LLM, not an autonomous financial posting agent, and not an accounting authority. It operates locally and does not create or mutate financial truth.

---

## Verified Canonical Benchmark Results

The canonical benchmark uses seed **`20260821`** with **250 settlements** and **2,368 orders**, covering **2026-05-05 to 2026-07-31**.

| Metric | Canonical Value |
|---|---:|
| **Processed Settlements** | 250 |
| **Candidate Orders** | 2,368 |
| **Total Period Value** | ₹53,02,897.47 |
| **Verified Value** | ₹2,67,375.08 |
| **Exact Set Matches** | 50 (20.0%) |
| **Proof Precision** | 98.04% (50 proven / 51 claimed) |
| **False Proofs** | 1 — `setl_000246`, independently blocked by policy |
| **Unsafe Auto-Resolutions** | **0** |
| **Net Unresolved Exposure** | **₹50,35,522.39 (94.96%)** |
| **Gross Contested Claim Exposure** | **₹56,51,168.91 (106.57%)** |
| **Active Blocker Rule Instances** | **534** |
| **Unique Blocked Exceptions** | **199** |
| **Unique Blocked Settlements** | **219** |
| **Period Verdict** | **`BLOCKED`** |

The benchmark is intentionally safety-focused: the system is rewarded for being correct when it claims certainty and for refusing cases that cannot be safely proven.

---

## Six Primary Controller Workflows

1. **Why can't I close?** — Explains active blockers, unresolved exposure, contradictory evidence, and remediation actions.
2. **What is financially material?** — Compares net unresolved exposure with the effective materiality threshold.
3. **Simulate closing now** — Runs non-mutating counterfactual scenarios such as waiting for predicted resolutions or carrying forward immaterial residuals.
4. **What will likely resolve?** — Shows deterministic predictions for exceptions likely to clear in T+1 or T+2 windows.
5. **Show evidence** — Traces the close decision back through verdict, materiality, exposure, exceptions, settlements, and source records.
6. **Review exceptions** — Prioritizes the human review queue using financial impact, safety, and urgency.

---

## Tamper-Evident Close Certificate

When a close decision is evaluated, ClosePilot can generate a **Close Certificate** with a deterministic SHA-256 evidence hash covering decision-relevant fields such as:

- period boundaries
- close verdict
- verified value
- net unresolved exposure
- gross contested claim exposure
- materiality bounds
- blocker rule instances and affected entities
- carry-forward items
- invariant results

Non-deterministic metadata such as timestamps and certificate IDs are excluded from the evidence hash, so identical financial states produce identical decision digests.

---

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/shubhang-aarya/closepilot.git
cd closepilot
```

### 2. Set up the environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

### 3. Run the test suite

```bash
# Close-readiness tests
python3 -m pytest tests/test_close_readiness.py -q

# Benchmark integrity / exposure semantics
python3 -m pytest tests/test_benchmark_integrity.py -q

# Run the non-holdout suite
python3 -m pytest tests -q -k "not holdout"
```

### 4. Run the canonical benchmark

```bash
python3 -m attest 250

# Or run the benchmark evaluation with close readiness and certificate issuance
python3 scripts/benchmark_evaluation.py 250
```

### 5. Launch the ClosePilot dashboard

```bash
python3 -m closepilot
```

Open:

**http://127.0.0.1:8430**

---

## Deployment

### Live Demo

**https://closepilot-r5my.onrender.com**

The hosted deployment runs the **ClosePilot controller dashboard**. The underlying ATTEST kernel remains the trusted verification layer beneath the product.

### Docker

```bash
docker build -t closepilot .
docker run -p 8430:8430 closepilot
```

For managed platforms such as Render, the application reads the platform-provided `PORT` environment variable and binds to the required host/port.

### Health Check

```bash
curl https://closepilot-r5my.onrender.com/health
```

Expected response:

```json
{"status":"ok"}
```

---

## Evaluation Methodology & Limitations

1. **Synthetic benchmark data:** Evaluation uses synthetic datasets with known ground truth so false-proof behavior can be measured precisely.
2. **No live gateway posting:** The project is designed for verifiable settlement reconciliation and close control. It does not use live Razorpay credentials or post to a production ledger.
3. **Local AI heuristics:** The AI Investigator is an offline deterministic advisory engine. It does not call an external cloud LLM API.
4. **Holdout isolation:** Evaluation holdout data is kept separate from the runtime decision path and is not used to make financial decisions.

---

## Core Principle

> **Reconciliation tells you what doesn't match. ClosePilot tells you whether the books are safe to close.**
