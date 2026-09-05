# Architecture

    HYPOTHESIS  →  PROOF  →  POLICY  →  ACTION

Four stages, and the seams between them are the product. Each can refuse; a stage
that has not run is indistinguishable from one that refused; and nothing reaches
an action except through all four in order.

---

## The layers

| | | AI |
|---|---|---|
| **L0** blocking | candidate generation, calendar-inverted, escalating | no |
| **L1** | bank credit → settlement, by UTR from free text | no |
| **L2** | settlement → single order, exact within one paisa | no |
| **L3** | settlement → subset of orders, counting DP over the amount axis | no |
| **L4a** | 1:1 contention, Hungarian assignment | no |
| **L4b** | conflict explanation, CP-SAT unsat cores | no |
| **L5** | unstructured narration, model proposes / solver falsifies | **yes** |
| **L6** | calibration, cost-derived posting threshold | no |
| **L7** | exceptions, each with a reason code and a residual | no |

L5 is the only layer a model touches, and it is disabled — across 1,020
ambiguous cases it offered an answer on 63 and was right on 27, silent on 94% of
the work it exists for. D8 first measured this by hand at 0.521 and the
re-measurement in `benchmark/anchoring.json` came back worse, so the decision
held. It runs in investigation mode,
where its conclusion is discarded and only the record of what it proposed and why
it was refused is kept.

---

## The trusted kernel

The prover is large: blocking, a counting DP, constraint propagation, CP-SAT,
model-proposed hypotheses. The verifier is **35 lines**
(`attest/verdict.py::check`), shares no code with any of it, and recomputes every
value from source records rather than trusting a field on the proof.

> A bug anywhere in the prover can cost recall. It cannot post a wrong entry.

Same reason a proof assistant separates its kernel from its tactics. The kernel
is small enough to read in one sitting, and that is its entire specification.

**What the kernel cannot catch, and this matters.** It checks arithmetic. When
the arithmetic is correct but the *question* was wrong — a search space that
excluded the truth — the kernel accepts a proof that is internally consistent and
factually false. That is FAILURES.md D8, and the answer to it is not a better
kernel but `searchspace.py`.

---

## Search-space integrity

Every reduction declares its authority:

| reduction | deterministic | why |
|---|---|---|
| amount ceiling | **yes** | an order larger than the credit cannot be inside it |
| settlement calendar | no | T+2 is a convention; real settlements slip |
| already claimed | no | sound only if earlier proofs are — D4 showed that failing |

So the engine may say exactly one of two things, and never the first when it has
only earned the second:

```
unique — every exclusion was deterministic
unique within the validated candidate space; the space rests on
  settlement calendar, already claimed — conventions, not proofs
```

A COMPROMISED space blocks posting regardless of verdict.

---

## Coincidence risk

The counting DP already computes which sums are reachable, so measuring how
densely populated the neighbourhood of a credit is costs one extra pass — and it
separates a hard-won match from one the pool was always going to produce:

```
sparse     189 proofs   0 wrong
moderate    43 proofs   5 wrong
dense        4 proofs   0 wrong
```

Every false proof in the panel falls in one bucket. The risk model stratifies on
it, which is what took money wrongly auto-posted to zero.

---

## Rules are beliefs

`rules.py` holds what the engine *thinks* the gateway charges, separate from what
it does. Constants would make the failure invisible — the engine would check its
assumptions against themselves and agree every time. Measured cost of being
wrong: a ₹2 flat fee takes the share of true bundles that balance from 85% to 0%.

Every run records `rules / policy / solver / dataset / model` versions. The solver
version hashes the code that decides, so a change appears whether or not anyone
remembered to bump a number.

---

## Adapters

    DataSource ── RazorpayAdapter ── SyntheticAdapter ── (bank, csv)
                        │
                    Normalizer
                        │
                    ATTEST core

The solver sees `Order`, `Settlement`, `BankCredit` and nothing else, so swapping
the source cannot change a verdict. A snapshot states its own provenance,
freshness and `linked_fraction` — the share of orders arriving with a settlement
reference, which is the single most important number about a source. Razorpay
recon: 100%. Synthetic generator: 0%, which is why the engine abstains on 82% of
it.

---

## The action pipeline

    Agent → Intent → Evidence → Verification → Policy → Action

Enforced in `agents.py`, not drawn. `POST_ENTRY`, `MARK_RECONCILED`,
`TRIGGER_REFUND` and `MODIFY_RECORD` are **defined and granted to no agent** —
defined rather than absent, because an absence is silent and a refusal is
auditable. Enforced at grant time: constructing an agent with one raises.

The engine posts entries, after the kernel and the policy. No agent is in that
path, so there is no configuration in which one appears.

## Postability requires search-space provenance (CORE-001)

A PROVEN verdict is not sufficient to post. The finding must also be able to
answer what search space was proved, which candidate universe was considered,
which solver produced the proof, and whether the proof belongs to that universe
— and it fails closed on any of them.

`Finding.postable` previously returned `True` when no search space was recorded,
so a proof was postable *because* it omitted the evidence it would have been
judged on. Fixed; measured impact on legitimate proofs: none (52 postable before
and after, all six gates +0.0000). See `reports/CORE-001-postable-fails-open.md`.

## Where the Razorpay adapter stops

These are **boundaries, not bugs**. The adapter is hardened for the implemented
path and for fixtures; it is not a validated live integration, and nothing in
this repository should be read as claiming otherwise.

| Boundary | What that means |
|---|---|
| No live Razorpay account has been exercised | `fetch` performs a real authenticated HTTP request and has never been called with real credentials. Code that *would* perform a live operation is not a live integration, and the presence of `urlopen` is not evidence that anything was validated against it. |
| Bank statement ingestion is synthetic | `BankCredit` is constructed from each settlement, so the credit always matches by construction. The adapter therefore cannot exercise the one case the engine exists for: a credit that does not correspond to one settlement. |
| The pagination stop condition is unverified | `count`/`skip` until a short page is Razorpay's documented behaviour, read from documentation rather than from responses. `test_integration_three_overlapping_pages_yield_three_records` covers the *consequence* of overlapping pages on synthetic rows; the loop itself has never met a real response. |
| Fee ingestion has read-only evidence | `fee` and `tax` are read and folded into the `amount` fallback, then re-derived from the rule set. No test asserts the mapping. |
| Secret handling has read-only evidence | Credentials come from the environment and `status()` truncates the key id to eight characters. That no secret reaches a snapshot, a log or the UI was established by reading the code, not by a test. |
| Rejections do not outlive the process | `Snapshot.rejected` is correct and complete for one pull, and then it is gone. See the ADR on rejection persistence in `DECISIONS.md`. |

The distinction matters more than the list. A bug is behaviour that contradicts
what the system claims about itself; a boundary is a claim the system has
declined to make. Filing these as bugs would imply a plan to fix them before the
work is judged, and there isn't one — the honest position is that the evaluation
runs on generated data with a stated envelope, and the adapter is the seam where
that envelope ends.
