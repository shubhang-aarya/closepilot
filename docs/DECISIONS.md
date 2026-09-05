# Decisions

An ADR log of decisions already made, each with what it cost. Reconstructed from
`FAILURES.md` and the commit history, not from memory.

---

### ADR-1 · Track 04, because ground truth is constructible
**Status** accepted

Fraud detection means inventing the patterns and then detecting them; precision
measures the author's imagination. Reconciliation lets orders be generated first
and settlements derived from them, so the mapping is known exactly.

**Consequence** every accuracy figure is defensible. No other candidate allowed
that claim.

---

### ADR-2 · Meet-in-the-middle, abandoned
**Status** superseded by ADR-3 · D2

MITM is viable to roughly n=45. Measured pools: p50 = 899. 2^449 per side.

**Consequence** the estimate had been invented rather than measured, and was
wrong by twenty-fold. Measure before optimising.

---

### ADR-3 · Counting DP over the amount axis
**Status** accepted

O(n·target) rather than O(2^(n/2)). The saturating counter also makes
PROVEN/AMBIGUOUS/CONTRADICTED a computed property rather than a threshold.

**Consequence** the bug forced a better architecture than the plan had.

---

### ADR-4 · Verdicts are counted, never scored
**Status** accepted

`97%` is not interpretable, cannot be audited, and invites a threshold. Solution
count is a fact about the model.

**Consequence** no confidence number anywhere in the product.

---

### ADR-5 · Cross-settlement propagation, built and disabled
**Status** rejected · D4

+3.2pp exact for +3.2pp WRONG. One false proof consumed orders it did not own and
manufactured eight more across four rounds.

**Consequence** a change that raises exact-set match by three points is not an
improvement if it raises false proofs by the same amount.

---

### ADR-6 · Rust is load-bearing, not a benchmark
**Status** accepted · D5

The ₹30,000 Python envelope silently skipped 14.8% of the portfolio — every large
bundle — before a single subset was examined.

**Consequence** the port is the difference between attempting 85% of the
portfolio and all of it. Opening the envelope also removed the last false proof.

---

### ADR-7 · Every claim is pooled across a fixed seed panel
**Status** accepted · D7

Precision 1.000 survived six days past the measurement that refuted it. Five
seeds give 0, 0, 1, 2, 2.

**Consequence** a number with two homes will disagree with itself.
`benchmark/results.json` is the only origin.

---

### ADR-8 · An anchor may select, never create uniqueness
**Status** accepted · D8

Anchoring *before* the search resolved 92 abstentions and got 32 wrong.
Uniqueness inside a restricted space is not uniqueness.

**Consequence** the corrected version is sound and *worse*. D8 measured 0.521
by hand; the re-measurement records 27 correct of 63 resolved, worse again —
which is the useful result: there is no signal to select on, because the generator
emits no order-level reference.

---

### ADR-9 · Risk is priced at the Wilson upper bound
**Status** accepted · D9

The point estimate 1/152 under-priced realised loss by 5.6× on held-out data.

**Consequence** auto-post fell 15.2% → 7.6%. Being wrong about your own error
rate is acceptable in exactly one direction.

---

### ADR-10 · Hungarian rejected for global selection
**Status** accepted · ADR-11 supersedes the packing

Hungarian solves one-to-one matching and cannot express "candidate A conflicts
with candidate B because both claim order #17". That is set packing.

---

### ADR-11 · CP-SAT packing rejected, unsat cores shipped
**Status** accepted · D12

+0.64pp exact for +0.32pp WRONG, a straight regression at n=1200, and the gain
not even consistent in sign.

**Consequence** the valuable output was the measurement that said not to ship it,
plus a by-product nobody set out to build.

---

### ADR-12 · Rules are beliefs, and versioned
**Status** accepted · D16

Constants let the engine check its assumptions against themselves. A ₹2 flat fee
takes the share of true bundles that balance from 85% to 0%.

**Consequence** "coverage collapsed" and "your fee schedule is wrong" are the
same observation, and only one is actionable.

---

### ADR-13 · Against a real gateway, reconciliation is largely a join
**Status** accepted · D17

Razorpay's recon report carries `order_id`, `payment_id` and `settlement_id` on
the same row — the evidence D8 concluded was missing.

**Consequence** the honest framing is that the solver is the fallback for where
the join fails: recon unavailable, bank-statement reconciliation, adjustments with
no linked entity. Those are the hard cases and the reason the engine exists.

---

### ADR-14 · No agent holds a write capability
**Status** accepted · D19

Defined and granted to none, enforced at construction. An absence is silent; a
refusal is auditable.

---

### ADR-15 · Gates fail on safety, never on accuracy
**Status** accepted · D20

Verified by re-enabling ADR-5: exact recovery improves two points while the build
fails.

**Consequence** a symmetric gate would have argued for shipping ADR-5, ADR-8 and
ADR-11.

## Postability requires search-space provenance (CORE-001)

A PROVEN verdict is not sufficient to post. The finding must also be able to
answer what search space was proved, which candidate universe was considered,
which solver produced the proof, and whether the proof belongs to that universe
— and it fails closed on any of them.

`Finding.postable` previously returned `True` when no search space was recorded,
so a proof was postable *because* it omitted the evidence it would have been
judged on. Fixed; measured impact on legitimate proofs: none (52 postable before
and after, all six gates +0.0000). See `reports/CORE-001-postable-fails-open.md`.

## Rejection persistence is deferred to productization

**Decision: `Snapshot.rejected` stays in-process for now. Persistence is a
post-hackathon requirement, recorded here rather than built.**

### Why it matters

A rejection is a row an operator has to chase. It names a real record that
Razorpay sent and ATTEST refused to read — a fractional paise amount, a row that
identifies itself twice, a payload that isn't an object. Every one of those is a
question for whoever owns the source data, and the answer changes money.

The current representation is right: index, reason, identity, record type, which
is enough to find the row and enough to ask about it. What is missing is
duration. The list is built during `normalise`, carried on the snapshot, and
dies when the process does. An operator who runs a pull, sees "3 records could
not be read exactly", and closes the terminal has lost the only record that
those three rows existed. Worse, the *next* pull re-reads them, re-rejects them,
and reports the same count — so a persistent source defect is indistinguishable
from a transient one, and nothing accumulates toward "this has been broken for
eleven days."

### Why it is not required for the current evaluation

The evaluation never reads a rejection. It runs on generated data where every
row is well-formed by construction, so the rejection path is exercised only by
tests, which assert on the in-memory list directly. No metric, no gate and no
claim in the register depends on a rejection surviving a process boundary.
Building storage now would add a schema, a migration path and a retention
question to a system whose evaluated behaviour would not change by a single
verdict — and the six gates moving +0.0000 across the adapter hardening is the
evidence for that.

There is also a specific reason not to guess at it early. Rejection storage is
an operational surface: it needs a retention policy, a resolution state, and an
opinion about whether a rejection that later reads cleanly is deleted or
retained as history. Those are product decisions, and inventing answers to them
before anyone has run a real pull is how a schema gets built around assumptions
that the first live account immediately contradicts.

### What the future interface must preserve

Whatever replaces the in-process list has to keep the properties the current one
already has, because they were each the fix for something:

1. **The row index within its pull**, and enough about the pull — source,
   period, page — to find the row again. A reason without a location is not
   actionable.
2. **The source's own identity for the record**, never a fabricated one. An
   identity ATTEST invented cannot be used to ask Razorpay about the row.
3. **The verbatim reason**, not a category. "amount: '10.50' in paise is 10.50
   paise, which is not a whole number" tells an operator what to do; a
   `MALFORMED_AMOUNT` enum does not.
4. **Rejections as records, never a count.** ADAPTER-003 was exactly this
   mistake: a counter is a number you cannot act on.
5. **Identity across pulls**, which is the property the in-process version does
   not have and the reason to build this at all — the same row rejected on
   Monday and Thursday must be recognisable as one problem.
6. **No silent promotion.** A rejected row must never become readable because a
   later version of the parser was more permissive; if the parser changes, the
   old rejection stands as a record of what the old one refused.
