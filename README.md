# ClosePilot

## Continuous AI Finance Controller

### Can I close?

**ClosePilot** is an audit-ready, continuous financial close controller built on top of the **ATTEST** mathematical verification kernel. It answers the single decisive question every financial controller and CFO asks at the end of a reporting period:

> **"Can I close?"**

If yes, it issues a cryptographically tamper-evident **Close Certificate**.
If not, it tells you exactly why: which active safety rules fired, which material balance-sheet exposures are at risk, which items will likely resolve naturally, and what specific actions a human controller must take to achieve close authorization.

The system supports two execution paths: an accelerated **native** kernel and a pure Python portable path.

---

## The problem

At period close, finance teams face hundreds or thousands of batched settlements, fees, taxes, and bank credits. In multi-order payment gateways like Razorpay, lump-sum credits do not arrive with explicit 1:1 order linkages:
1. **Combinatorial Ambiguity**: More than one subset of orders can sum to the exact net settlement amount. Naive automated systems or unconstrained AI agents will hallucinate or guess a match, posting revenues to the wrong customer ledger while the books appear to balance.
2. **Binary Guessing vs. Controlled Authorization**: Traditional tools force an all-or-nothing choice: either hold up the entire financial close indefinitely for minor timing differences, or blindly auto-post unverified batches into the general ledger.
3. **Lack of Cryptographic Auditability**: Auditors and regulators require proof of *why* an exception was carried forward, *what* the materiality boundary was, and *that* zero unverified material exposure leaked into closed financial books.

---

## The Solution: ClosePilot Architecture

ClosePilot orchestrates the end-to-end close workflow, using **ATTEST** as its trusted mathematical verification kernel underneath:

```
Financial Events (Gateway Settlements, Orders, Bank Credits)
              ↓
Financial Truth (Ground-Truth Invariants & Source Records)
              ↓
Reconciliation / Verification (ATTEST Proof Engine & Double-Entry Invariants)
              ↓
Exception Registry (Categorized Exceptions: Timing, Ambiguity, Missing Data)
              ↓
Exposure (Net Unresolved Exposure vs. Gross Contested Claims)
              ↓
Materiality (Bps Threshold, Bounded Floor & Ceiling Policies)
              ↓
Resolution Prediction (Local Statistical Clearing Forecasts: T+1, T+2)
              ↓
AI Investigation (Deterministic Local Advisory Engine & Root-Cause Citations)
              ↓
Counterfactual Simulation (Zero-Mutation What-If Projections)
              ↓
Human Review (Deterministic Multi-Dimensional Controller Queue & Audit Signatures)
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

ClosePilot maintains strict, uncompromised accounting definitions:

### 1. Exposure Semantics: Net vs. Gross
- **Net Unresolved Exposure (`net_unresolved_exposure_paise`)**: The exact balance-sheet amount that remains economically unresolved or unverified. This is the **only** metric used for close readiness, materiality compliance, and balance-sheet risk.
  Strict conservation law holds:
  $$\text{verified\_value} + \text{net\_unresolved\_exposure} = \text{total\_period\_value}$$
- **Gross Contested Claim Exposure (`gross_contested_claim_exposure_paise`)**: A diagnostic risk metric aggregating candidate order claims across all competing valid hypotheses for ambiguous settlements. Because multiple hypotheses can overlap on the same candidate orders, gross contested claims can legitimately exceed total portfolio value and is **never** treated as balance-sheet exposure.

### 2. Blocker Semantics: Rule Instances vs. Affected Entities
ClosePilot strictly distinguishes between rule firings and underlying entities:
- **Active Blocker Rule Instances**: The total count of distinct safety rule violations that fired (e.g., 534 instances).
- **Unique Blocked Exceptions**: The count of distinct exception entities affected by blockers (e.g., 199 exceptions).
- **Unique Blocked Settlements**: The count of distinct settlement batches affected by blockers (e.g., 219 settlements).

*Verdict Rule*: "Close authorization is BLOCKED by active safety rules and material unresolved exposure." Rule instances are never conflated with unique problem entities.

### 3. Close Readiness Verdicts
- `READY_TO_CLOSE`: Zero active blocker rule instances, zero material unresolved exposure, and 100% passing financial invariants.
- `READY_WITH_CARRY_FORWARD`: Zero active blocker rule instances; all unresolved exposure is strictly within policy materiality threshold and every carried-forward exception is explicitly enumerated.
- `BLOCKED`: Prevented by active safety blockers or unresolved exposure exceeding the materiality threshold.

### 4. Epistemic Separation
ClosePilot strictly separates four cognitive layers across all interfaces and APIs:
- **`FACT`**: Proven by the ATTEST deterministic kernel and verified ledger entries.
- **`PREDICTION`**: Deterministic local statistical forecasts of expected clearing horizons.
- **`RECOMMENDATION`**: Advisory guidance suggesting review queue prioritization and investigation remedies.
- **`HYPOTHETICAL SIMULATION`**: Non-mutating counterfactual projections evaluating "what-if" operational scenarios.

---

## The AI Advisory Boundary

ClosePilot maintains an unbreachable wall between advisory intelligence and financial truth:

| Role | Component | Authority |
|---|---|---|
| **Advisor** | AI Investigator & Resolution Predictor | Investigate, retrieve evidence, summarize, predict, recommend. **Strictly advisory.** Cannot create financial truth or mutate state. |
| **Verifier** | ATTEST Kernel | Mathematically reconstruct solutions, verify subset sums in integer paise, enforce double-entry invariants. |
| **Policy** | Materiality & Close Controller | Authorize period closure, evaluate blocker thresholds, determine carry-forward eligibility. |
| **Ledger** | Double-Entry Journal | Record final balanced financial postings with non-repudiation audit trails. |

> **AI Honesty Disclosure**: The ClosePilot AI Investigator is a **local, deterministic advisory heuristic engine**. It is **NOT** an external cloud LLM, **NOT** an autonomous financial posting agent, and **NOT** an accounting authority. It operates entirely locally and offline, guaranteeing data privacy and deterministic reproducibility.

---

## Verified Canonical Benchmark Results

The benchmark is executed on canonical seed `20260821` (250 settlements, 2,368 orders, period `2026-05-05` to `2026-07-31`). All numbers below are verified and read from authoritative execution:

| Metric | Canonical Value |
|---|---|
| **Processed Settlements** | 250 settlements |
| **Candidate Orders** | 2,368 orders |
| **Total Period Value** | ₹53,02,897.47 |
| **Verified Value** | ₹2,67,375.08 |
| **Exact Set Matches** | 50 (20.0 percent) |
| **Proof Precision** | 98.04 percent (50 proven / 51 claimed) |
| **False Proofs** | 1 (defended: `setl_000246` independently blocked by policy) |
| **Unsafe Auto-Resolutions** | **0** (Zero tolerance for incorrect balance postings) |
| **Net Unresolved Exposure** | **₹50,35,522.39** (94.96 percent of portfolio value) |
| **Gross Contested Claim Exposure** | **₹56,51,168.91** (106.57 percent diagnostic ambiguity risk) |
| **Active Blocker Rule Instances** | **534** rule instances |
| **Unique Blocked Exceptions** | **199** exceptions |
| **Unique Blocked Settlements** | **219** settlements |
| **Period Verdict** | **`BLOCKED`** |

<!-- generated: results -->
```
2 held-out seeds × 250 settlements
calibrated on [20260821, 314159, 271828], evaluated on [555001, 999983]

RESOLUTION
  exact set recovery           16.0%   complete truth recovered
  coverage                     16.8%   resolved outright
  ambiguity rate               82.4%   correctly refused

SAFETY
  proof precision              0.952   right when it claims sure
  false proof rate             0.80%   ← the number that moves money

ACCOUNTED FOR
  settled (undisputed)     ₹67,66,131.23   agreed by every explanation
  disputed                 ₹75,73,097.75
  accounted for                68.8%   of all processed value

MONEY
  processed              ₹1,02,04,411.89
  auto-posted               ₹2,52,431.44
  protected                ₹99,51,980.45   refused, deliberately
  wrongly auto-posted              ₹0.00

NORTH STAR
  safe resolution rate          6.6%   resolved without a human
```
<!-- /generated -->

<!-- generated: baselines -->
```
  matcher      coverage   decided   wrong   false proof       pair prec
------------------------------------------------------------------
  attest          16.0%        84       4          4.8%        95.9%
  exact_only       4.4%        22       0          0.0%       100.0%
  fuzzy            3.6%        30      12         40.0%        60.0%
  greedy           4.6%       462     439         95.0%        16.5%

  500 settlements over seeds [555001, 999983], identical datasets and identical scoring
```
<!-- /generated -->

---

## Six Primary Controller Workflows

ClosePilot empowers finance teams with six dedicated interactive workflows:

1. **Why can't I close?**: Explains active blocker rule instances, contradictory proofs, and missing transaction records with remediation actions.
2. **What is financially material?**: Evaluates net unresolved exposure against the effective materiality threshold (bps, floor, and ceiling).
3. **Simulate closing now**: Runs non-mutating counterfactual simulations (e.g., waiving blockers, waiting T+2 for predicted resolves, carrying forward immaterial residuals) without modifying source financial records.
4. **What will likely resolve?**: Displays deterministic statistical predictions of which exceptions are expected to clear naturally within T+1 or T+2 windows.
5. **Show evidence**: Displays complete causal lineage chains tracing backward from close verdicts through materiality, exposure, exceptions, and settlements to raw bank credit lines, alongside grounded AI investigation summaries.
6. **Review exceptions**: Prioritizes outstanding discrepancies in a deterministic Human Review Queue scored by Financial Impact + Safety + Urgency, requiring cryptographic sign-off for controller overrides.

---

## Tamper-Evident Close Certificate

Upon close evaluation, ClosePilot generates an audit-ready, tamper-evident **Close Certificate** (`CloseCertificate`):
- **Deterministic SHA-256 Digest**: `evidence_hash` cryptographically seals all decision-relevant fields: period boundaries, authoritative verdict, verified value, net unresolved exposure, gross contested claim exposure, materiality bounds, active blocker rule instances, unique blocked entities, carry-forward schedule, and invariant results.
- **Audit Reproduction**: Any tampering with decision-relevant inputs invalidates the certificate digest. Non-deterministic issuance metadata (timestamps, certificate ID) is excluded from the evidence hash so that identical financial states yield identical cryptographic digests.

---

## Quickstart & Reproduction Commands

### Reproduce the demo

| Execution Path | Build | Results |
|---|---|---|
| **Native kernel** | `maturin develop --release` | 39 proven, 210 ambiguous, 0 insufficient |
| **Portable** | None (pure Python) | 39 proven, 174 ambiguous, 37 insufficient |

The optional native kernel accelerates execution. On a clean Python environment without the Rust toolchain, 37 settlements exceed the portable envelope and are reported as 37 insufficient. The canonical case `setl_000225` is identical on both paths.

### 1. Environment Setup
```bash
# Clone and enter the repository
git clone https://github.com/kunalKumar-13/attest && cd attest

# Setup virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
```

### 2. Run Test Suite
```bash
# Run close-readiness tests (91/91 passing)
python3 -m pytest tests/test_close_readiness.py -q

# Run benchmark integrity & exposure semantics tests (11/11 passing)
python3 -m pytest tests/test_benchmark_integrity.py -q

# Run all non-holdout test suites
python3 -m pytest tests -q -k "not holdout"
```

### 3. Run Canonical Benchmark
```bash
# Execute the canonical 250-settlement ATTEST kernel benchmark
python3 -m attest 250

# Or execute full benchmark evaluation with close readiness & certificate issuance
python3 scripts/benchmark_evaluation.py 250
```

### 4. Launch ClosePilot Controller Dashboard
```bash
# Launch the ClosePilot HTTP Dashboard (runs on stdlib ThreadingHTTPServer)
python3 -m closepilot

# Or explicitly via dashboard module:
python3 -m closepilot.dashboard
```
Open your browser at **`http://127.0.0.1:8430`** to access the interactive controller dashboard.

---

## Evaluation Methodology & Limitations

1. **Synthetic Benchmark Data**: Evaluation utilizes synthetically generated datasets with known ground truth to measure false-proof rates with mathematical precision. The hazard taxonomy was frozen prior to matcher authoring to prevent overfitting.
2. **No Live Gateway Posting**: The system is designed for verifiable settlement reconciliation. While real Razorpay webhook and CSV payload schemas are supported, no live gateway credentials are contacted.
3. **Local Heuristics**: The AI Investigator is an offline deterministic expert system that retrieves grounded lineage citations; it does not invoke external cloud LLM APIs.
4. **Holdout Isolation**: Evaluation holdout seed `900913` is strictly isolated and preserved for final submission audit.
