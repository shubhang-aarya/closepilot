# The golden dataset

One dataset. No demo-only code, no seeded exceptions, no fixture that exists to
make a screenshot work. Every state below is produced by the engine running on
generated data, and the demo operates on the real product.

```
seed              555001          held out from calibration
settlements       250
orders            2,328
dataset version   synthetic_n250_s555001
rules             rules_d4cb21a4b0ac
policy            policy_76b7dd4eabcc
solver            solver_000589bed531
```

The run id (`run_0013`) is a session label and increments per launch; the
**data** is a function of the seed and the size, so the same command produces
the same book, the same verdicts and the same numbers on any machine.

> One caveat, because it decides which column of numbers you see. Without the
> Rust extension the engine runs the numpy path, which has a narrower envelope
> and resolves less — "value accounted for" measures 23.6% against 66.7%. The
> safety gates hold on both. See `docs/REPRODUCE.md`.

## The eleven canonical states

| | state | why it exists | source | verdict | policy | action | lens | context |
|---|---|---|---|---|---|---|---|---|
| **A** | clean PROVEN settlement | one candidate set explains the credit exactly, and nothing else does | `setl_000022`, ₹109.08, UTR 365100201879 | PROVEN | AUTO-POST | entry written | Journal | the balanced entry |
| **B** | AMBIGUOUS with multiple valid explanations | four disjoint order sets satisfy the amount to the paisa | `setl_000225`, ₹23,922.07 | AMBIGUOUS | REVIEW | supply an order-level reference | Evidence | explanation A–D |
| **C** | CONTRADICTED settlement | no combination of candidates satisfies the amount at all | `setl_000166`, ₹1,817.31, UTR 107342563262 | CONTRADICTED | REVIEW | look for a fee correction, reversal or manual adjustment in that amount | Control | the settlement |
| **D** | search-space boundary | the two effective reductions are conventions, not facts — uniqueness is *inside a space the calendar chose* | 2,328 → 23 on `setl_000225` | — | — | — | Evidence | the reduction |
| **E** | advisory proposal, discarded | the advisor proposes a capture-batch anchor that would select one of four explanations; the engine keeps the verdict it reached without it | `setl_000225` investigation, step 1 | — | — | — | Investigate | the advisor step |
| **F** | the loop closing | advisor proposes · solver tests · engine proves · policy prices · ledger posts, on one settlement | `setl_000233`, ₹6,523.53, AUTO-POST | PROVEN | AUTO_POST | none — it posted | Investigate | the control loop |
| **G** | policy AUTO-POST | expected loss below the cost of checking, and a proof exists to price against | 17 of 250 | PROVEN | AUTO-POST | — | Policy | the decision |
| **H** | policy REVIEW | 233 of 250, including every ambiguous case | 233 of 250 | mixed | REVIEW | — | Policy | the decision |
| **I** | activity trail | eight events through the real ingest path, three signed correctly | 8 deliveries, 8 events | — | — | — | Activity | an event |
| **J** | Trust limitation | 2 of 8 claims are not MEASURED; 11 unknowns are stated | claim register | — | — | — | Trust | the claim |
| **K** | Razorpay adapter boundary | six frozen boundaries, including live validation NOT VERIFIED | `docs/RAZORPAY-INTEGRATION.md` | — | — | — | Trust | the unknown |

## The canonical cases

Five cases tell the whole story. Three would tell most of it; these five are the
smallest set where nothing important is left implicit.

### Case A — `setl_000022` · ₹109.08 · PROVEN · AUTO-POST

The system's happy path, and one of the 17 settlements in 250 that clear it. A
single order explains the credit exactly. The journal entry balances to the paisa
across four accounts — Bank, Payment gateway fees, Input GST (recoverable),
Trade receivables — because the fee and the tax on it are split from the single
charge the proof carries, and a merchant needs them apart.

**What it shows:** the whole chain succeeding, and how rare that is.

### Case B — `setl_000225` · ₹23,922.07 · AMBIGUOUS · REVIEW

Four disjoint sets of orders satisfy the amount exactly, within a tolerance of
**4 orders are in every explanation** — ₹12,630.27 is not in question. The
argument is 17 orders and ₹30,107.39.

**What it shows:** the product's actual thesis. Arithmetic cannot choose between
four exact answers, so the engine does not, and it says precisely how much is
agreed rather than refusing the whole settlement.

### Case C — `setl_000225` investigation · advisor → solver → engine

The model proposes a capture-batch anchor: three orders captured together on
2026-05-06, the densest batch in the window. The solver tests it against
uniqueness and returns **NON-DISCRIMINATIVE** — 4 of 4 valid explanations
contain that anchor, so it cannot choose between them. The model exhausts. The
engine **abstains**, and the verdict is unchanged.

**What it shows:** the AI is not on the decision path, demonstrated rather than
asserted. `verdict_changed: false`.

### Case D — the policy boundary

`expected loss ₹247.82` against `cost of checking ₹250.00` → AUTO-POST for
`setl_000233`, and the two-rupee margin is the point: the threshold is not a
round number someone chose, it is wherever the priced error crosses the cost of
a person looking. For every AMBIGUOUS case the boundary is not drawn at all:
**UNPRICED**, because no proof was established, so there is no error probability
to price. A threshold drawn there would be a number invented to fill a space.

**What it shows:** automation is gated on proof first and economics second, and
the system will decline to compute rather than fabricate a zero.

### Case E — the Razorpay boundary in Trust

Trust states **"Live account validation is NOT VERIFIED"** in those words, along
with five more frozen boundaries: synthetic bank statements, an unverified
pagination stop condition, read-only evidence for fee and secret handling, and
rejections that do not outlive the process.

**What it shows:** the system is specific about what it has not established, in
the lens an auditor reads.

## What the dataset deliberately does not contain

A live Razorpay pull. A real bank statement. A settlement spanning a period
boundary. Any record whose provenance is a person rather than a generator.
These are boundaries, recorded in `docs/RAZORPAY-INTEGRATION.md`, and the demo
does not pretend otherwise.
