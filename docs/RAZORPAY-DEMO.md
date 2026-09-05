# Razorpay — what is real

Read this before the demo, so nothing in it has to be qualified while it runs.

ATTEST is architected around Razorpay's actual reconciliation primitives —
`payment_id`, `settlement_id`, `refund_id`, fee, tax, UTR, webhook, settlement
cycle — and it is explicit about which of those have been exercised against a
live account. **None have.** That is a boundary, stated here and stated in the
product's Trust lens, not a caveat discovered later.

## Status of every capability

| capability | status | what that means exactly |
|---|---|---|
| Recon row → settlement | **IMPLEMENTED** | rows aggregate by `settlement_id` into net, UTR, value date. 50 adapter tests. |
| Recon row → order | **IMPLEMENTED** | `type == "payment"` rows become orders with method, capture date, gross. |
| Deduplication by source identity | **IMPLEMENTED** | keyed on `payment_id` / `refund_id` / `entity_id` per record type — never an amount, never a fabricated key. |
| Integer-paise money | **IMPLEMENTED** | `parse_amount` reads exactly or refuses. No `int()`, no `round()`, no truncation. Unit declared, not inferred. |
| Explicit rejection records | **IMPLEMENTED** | index, reason, identity and record type per unreadable row. |
| Webhook signature | **IMPLEMENTED** | HMAC-SHA256 over raw bytes, constant-time compare, **fails closed** on an absent secret. |
| Webhook idempotency | **IMPLEMENTED** | keyed on event id **and** payload hash; same id with a different body is a contradiction, not a duplicate. |
| Fee and tax | **PARTIAL** | read per row and folded into the amount fallback, then re-derived from the rule set. Not retained per order. |
| Refunds and adjustments | **PARTIAL** | they reduce the settlement total; they are not modelled as citable records. |
| Pagination | **PARTIAL** | `count`/`skip` until a short page. The consequence of overlapping pages is tested on synthetic rows; **the loop has never met a real response.** |
| Bank statement | **SIMULATED** | `BankCredit` is constructed from each settlement, so every credit matches by construction. |
| Incremental sync | **NOT IMPLEMENTED** | `fetch` pulls a whole period. No cursor, no watermark. |
| Live account validation | **NOT VERIFIED** | `fetch` performs a real authenticated request and has never been called with real credentials. |

## The three words that matter

**IMPLEMENTED** — there is code, and a test fails if it stops working.

**SIMULATED** — the product constructs this rather than reading it. The bank
statement is the important one: because every synthetic credit matches its
settlement exactly, **the adapter cannot exercise the case the engine exists
for** — a credit that does not correspond to one settlement.

**NOT VERIFIED** — code exists that would do it, and it has never been run
against the real thing. The presence of `urlopen` is not evidence that anything
was validated against a response.

## What the demo shows, and what it does not

The demo runs on generated data. Every settlement, order, fee and UTR in it came
from `attest/generate/`, which was written before the matcher so it could not be
tuned to flatter the engine.

What that buys: ground truth. The false-proof rate is knowable because the
generator knows which orders really belong to which settlement, and a claim of
proof can be checked rather than believed.

What it costs: the numbers describe generated data. They are honest about a
population ATTEST created. **Trust says so, in the product, unprompted.**

## The strongest honest Razorpay story

Not "we integrated with Razorpay." It is:

> The reconciliation primitives are real. A settlement is a set of payments net
> of fees and tax, identified by a UTR on a value date, and it either has a
> unique explanation or it does not. ATTEST is built on exactly that model, it
> reads Razorpay's recon format, it fails closed on an unsigned webhook, and it
> refuses to read a fractional paise. What it has not done is meet a live
> account — and it tells you that itself, on the Trust lens, before you ask.

## Where to look during the demo

| claim | lens | what you will see |
|---|---|---|
| we read Razorpay's shape | Activity | eight deliveries, `payment.captured`, `refund.created`, statuses |
| money is exact | Journal | an entry balancing to the paisa across four accounts |
| the boundary is stated | Trust | "Live account validation is NOT VERIFIED", plus five more |
| the adapter is hardened | `tests/test_adapter.py` | 50 tests, each written against an observed defect |
