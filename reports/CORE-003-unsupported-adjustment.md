# CORE-003 — the kernel let a proof invent the money it could not explain

**Status:** FOUND → REPRODUCED → FIXED → REGRESSION TESTED.

**Found by:** an external red-team pass against `verdict.check`, asking what in
a `Proof` the kernel does *not* recompute.

---

## The defect

`verdict.check` exists so that a bug anywhere in the prover can cost recall but
cannot post a wrong entry. Its docstring says it "deliberately recomputes rather
than trusting any field on the proof". It recomputed two of the three terms:

```python
gross = sum(o.gross_paise for o in members)     # from source
net   = sum(o.net for o in members)             # from source
expected = net + proof.adjustment_paise         # from the PROOF
residual = settlement.net_paise - expected
```

`adjustment_paise` came from the artifact being checked, and it then appeared on
**both sides** of the arithmetic — in `expected`, and again in the equality
`net + proof.adjustment_paise == proof.net_paise`. Both sides move together, so
the equations are satisfied for *any* value. The adjustment was a free variable,
and the attacker chooses it.

That makes the residual test vacuous. Cite a subset of the real orders, set the
adjustment to exactly the amount missing, and the proof balances, clears
tolerance, and is accepted.

The invariant was already written down. `Proof.adjustment_paise` carries this
docstring, unchanged since the field was introduced:

> Refunds, chargebacks and settlement adjustments, signed. Non-zero values must
> be evidenced by a linked record, never inferred to close a gap.

The intent was stated and never enforced. `certificate.py` went further and
rendered non-zero adjustments as "evidenced by linked records" — a claim nothing
in the system checked.

## Reproduction

Held-out seed 555001, `setl_000013`. Truth is three orders.

```python
two  = list(true_ids)[:2]                    # drop one real order
net  = sum(orders[o].net for o in two)
gap  = settlement.net_paise - net            # 211535 paise = Rs 2,115.35

forged = Proof(settlement_id="setl_000013", order_ids=tuple(two),
               gross_paise=..., fee_paise=..., tax_paise=...,
               adjustment_paise=gap,                 # invented
               net_paise=net + gap,
               residual_paise=settlement.net_paise - (net + gap),  # 0
               tolerance_paise=tolerance_paise(2))

check(forged, settlement, orders)   # True
forged.balances                     # True
```

`ledger.post` credits `RECEIVABLES` with `gross_paise + adjustment_paise`, so
the invented ₹2,115.35 would have reached the books as receivable value with a
narration describing it as an adjustment.

**This was not one settlement.** Running the same construction across every
settlement on the panel whose truth carries more than one order: **240 of 240
forged adjustments were accepted.** The fixture was an illustration, not the
extent.

## Why it survived this long

Nothing legitimate ever sets the field. `pipeline.py`, `partition.py` and
`hypothesis.py` all construct proofs with `adjustment_paise=0`, and across three
seeds **0 of 2,507 real proofs** carry a non-zero adjustment. Every test that
exercised the kernel therefore exercised it with the attack surface set to zero.
The hole was reachable only by an artifact no honest path produces — which is
exactly the artifact a trusted kernel exists to reject.

## The fix

The kernel derives the adjustment the way it already derives gross and net —
from the source records — and refuses a proof that claims a different one:

```python
adjustment = evidenced_adjustment_paise(settlement, orders)
if proof.adjustment_paise != adjustment:
    return False  # money the source records do not account for
expected = net + adjustment
```

`evidenced_adjustment_paise` is a function rather than the literal `0` because
it is the **seam**. Nothing in the domain model records a refund, a chargeback
or a fee correction — `Settlement` carries an id, a date, a net and a UTR;
`Order` carries a gross, a method and a capture date — so the only adjustment
these sources can evidence today is zero. When an evidenced adjustment exists (a
Razorpay refund row, a linked reversal) it enters *there*, derived from a
record. The moment it is read from the proof instead, the field becomes a free
variable again.

The fix is the general invariant, not a rejection of the demonstrated case: it
does not mention `setl_000013`, does not special-case a value, and does not
forbid adjustments in principle. It requires them to have a source.

The kernel is 35 lines after the fix, 23 of them code. Every claim of its size
in the product and the submission documents was updated from 28; `api.py`'s
`kernel_measurement()` reads the number from the source, so the UI follows
automatically and a browser contract pins the two together.

## Regression test

`tests/test_invariants.py::test_a_proof_cannot_introduce_money_the_sources_do_not_account_for`

Three assertions, in order of generality:

1. **The general form.** For every settlement whose truth has ≥2 orders, drop
   one and name the gap. All must be refused, with a floor of >50 constructed
   attacks so the sweep cannot silently become vacuous.
2. **The demonstrated case.** `setl_000013`, two of three orders, and the gap
   pinned at 211535 paise — asserted as a value, so if the data moves the test
   says the attack moved rather than passing for the wrong reason.
3. **The fix bought safety, not silence.** The honest three-order proof over the
   same settlement still verifies, and `evidenced_adjustment_paise` returns 0.

Mutation-verified: with the guard removed and the kernel trusting the proof
again, the test reports `240 of 240 forged adjustments were accepted by the
kernel`.

## Related

- **CORE-001** — `postable` failed open when the search space was absent.
- **CORE-002** — condition 4 checked cardinality, not membership.

The shape recurs: each is a case where the artifact under inspection was
permitted to supply a term the inspection depended on. CORE-001 let it supply
the absence of a space, CORE-002 let it supply members that were never
candidates, CORE-003 let it supply money no record accounted for.
