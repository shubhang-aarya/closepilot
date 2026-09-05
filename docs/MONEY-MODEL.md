# The money model

Every amount in ATTEST is an **integer number of paise**. Not a float, not a
Decimal, not rupees. The reason is not stylistic: the tolerance the solver works
to is derived from rounding behaviour, and a representation that itself rounds
would make that derivation meaningless.

## Where amounts come from

```
gross_paise        integer, as ingested
fee_paise          _round_half_up(gross × bps, 10_000)
tax_paise          _round_half_up(fee × tax_bps, 10_000)
net_paise          gross − fee − tax
```

`_round_half_up` is explicit because Python's `round` is banker's rounding, and
a fee model that rounds half-to-even disagrees with every payment gateway.

## Why the tolerance is 1 paise per order

It is derived, not chosen. Fee and tax each round half-up independently, so one
order carries at most one paise of error, and a k-order subset at most k. A
hand-picked constant would be wrong in both directions at once — too tight and
large bundles never match, too loose and small subsets collide inside the band.

```
tolerance_paise(k) = k
```

## The audit

`tests/test_invariants.py::test_no_deciding_path_computes_money_in_floating_point`
walks the AST of every function that decides — `verdict.check`, `subsetsum.solve`,
`policy.decide`, `ledger.post`, and the fee model — and fails on a float literal
or a true division. Ratios for display are permitted and are not decisions;
`incorrectly_auto_posted_paise / auto_posted_paise` is a rate that gets printed,
not an amount that moves.

## The one float that touches money, and which way it rounds

Expected loss is a probability multiplied by an exposure, so it cannot be
integer arithmetic:

```
loss = ceil(P(error) × cost_if_wrong)
```

The **direction** is a safety decision. Truncating down understates the expected
loss, which makes `loss < review_cost` more often true and auto-posting more
likely. It now rounds up, which errs toward checking.

Measured on the current panel the change flips no decision — the fraction is
lost on all 39 proven settlements and none of them sit within a paise of the
boundary. That is precisely when a rounding direction is cheap to get right, and
it was found by auditing rather than by a failure.

## What is not modelled

- **One currency.** Every rule set is single-currency; a mixed book needs one
  rule set per currency and nothing here does that.
- **No FX.** No conversion, no rate source, no timing of conversion.
- **No partial paise.** Sub-paise amounts cannot be represented and are not
  expected to arrive.
