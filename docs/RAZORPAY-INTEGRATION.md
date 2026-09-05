# Razorpay integration — audit

Written by reading `attest/adapters/razorpay.py` and `attest/webhooks.py` and
running every capability against the code, not by reading the architecture. No
row below says IMPLEMENTED unless a test exercises it.

The **Evidence** column states what actually backs the STATUS claim, and how
strong it is. `test_*` names a test that fails if the row's claim stops being
true. *read only* means someone read the code and believed it. *not verified*
means the row is an intention. A row whose evidence is *read only* is not a
weaker version of a tested row — it is an untested claim, and the column exists
so that difference cannot be skimmed past.

**Nothing here has ever run against a live Razorpay account.** `fetch` performs
a real authenticated HTTP request, and it has never been called with real
credentials because none exist in this repository. That distinction is the point
of the STATUS column: code that *would* perform a live operation is not the same
as a live integration.

## Capability matrix

| Capability | Status | Implementation | Evidence | Limitation |
|---|---|---|---|---|
| Settlement ingestion | IMPLEMENTED | `normalise` aggregates recon rows by `settlement_id` into `Settlement(id, settled_on, net_paise, utr)` | `test_001_settlement_total_is_not_inflated_by_a_retried_pull`, `test_integration_three_overlapping_pages_yield_three_records` — the second asserts the exact net over two overlapping pages | Net is `credit − debit` summed over the period's rows. A settlement spanning a period boundary is split across two pulls and neither half will balance. |
| Payment ingestion | IMPLEMENTED | rows where `type == "payment"` become `Order` | `test_001_distinct_ids_with_equal_amounts_both_survive` — two ₹10 payments a second apart are two orders, not one | Only settled payments appear in recon. A captured-but-unsettled payment is invisible to this adapter. |
| Refund ingestion | PARTIAL | refunds reduce the settlement total via `debit`; they are **not** modelled as records | `test_001_refund_dedup_uses_refund_id`, `test_001_dedup_is_scoped_to_record_type` — aggregate behaviour only; nothing tests a refund as evidence because it cannot be one | A refund cannot be cited as evidence. The engine sees a smaller credit and no reason for it, so a refunded settlement reads as unexplained rather than as refunded. |
| Fee ingestion | PARTIAL | `fee` and `tax` are read per row and folded into `gross = amount` | read only | Read but not retained per-order: `Order` has no fee field, and fees are re-derived from the rule set. If Razorpay's fee disagrees with the rule set the difference surfaces as a residual, not as a fee mismatch. |
| Bank statement ingestion | SIMULATED | `BankCredit` is **synthesised** from each settlement: `bank_{sid}`, same amount, a constructed NEFT narration | none, and none is possible — there is no source to test against | No bank statement is read. The credit always matches the settlement exactly by construction, so this adapter cannot exercise the case the engine exists for — a bank credit that does not correspond to one settlement. |
| Webhook ingestion | IMPLEMENTED | `Ingest.handle` → verify, de-duplicate, scope, report | `test_wh_valid_signature_is_accepted` and six sibling `test_wh_*` cases covering every terminal status | Six event types in `HANDLED`; anything else is recorded as `unsupported` rather than dropped. |
| Signature verification | IMPLEMENTED | HMAC-SHA256 over the **raw** body, `hmac.compare_digest`; **fails closed** — an absent secret yields `UNVERIFIABLE` and refuses ingestion | `test_wh_absent_secret_refuses_ingestion`, `test_wh_wrong_signature_is_rejected`, `test_wh_missing_signature_is_rejected` | Was fail-OPEN: `if self.secret and not verify(...)` meant an unset `RAZORPAY_WEBHOOK_SECRET` verified nothing, processed everything, and said so nowhere. Fixed; the test above fails if it regresses. |
| Idempotency (webhook) | IMPLEMENTED | keyed on event id **and** a hash of the payload | `test_wh_replayed_event_is_a_duplicate_not_a_second_effect`, `test_wh_same_id_different_body_is_a_contradiction` | In-process dict. A restart loses the log and a redelivery would be accepted again. Production needs a unique index on `(provider, event_id)`. |
| Idempotency (ingest) | IMPLEMENTED | de-duplicated by the strongest stable **source** identity for the record type — `payment_id` / `refund_id` / `entity_id` — never an amount, never a fabricated key. A row carrying no identity is kept; a row naming itself twice differently is rejected | ten `test_001_*` cases, including `test_001_rows_without_any_identity_are_kept` and `test_001_a_row_naming_itself_twice_differently_is_refused` | Within one `normalise` call. Two separate pulls of an overlapping period produce two Snapshots and nothing reconciles them. Was keyed on a row HASH where no id was present, which merged genuinely distinct identical rows. |
| Duplicate events | IMPLEMENTED | `DUPLICATE` for an identical body, `REPLAY_MISMATCH` for the same id with a different body | `test_wh_replayed_event_*`, `test_wh_same_id_different_body_*` | — |
| Incremental sync | NOT IMPLEMENTED | `fetch(year, month, day)` pulls a whole period every time | none — nothing to test | No cursor, no watermark, no "since". Re-pulling a month re-reads it entirely. |
| Pagination | PARTIAL | `count`/`skip` until a short page, capped at 100,000 rows with a warning | `test_integration_three_overlapping_pages_yield_three_records` covers the *consequence* of overlapping pages, on synthetic rows. The paging loop itself is **not verified**: never run against a real response | Never exercised against a real response. The stop condition assumes a short final page, which is the documented behaviour and is unverified here. |
| Replay | PARTIAL | webhook replay is detected; a recon **pull** has no replay concept | `test_wh_replayed_event_*`; `test_001_settlement_total_is_not_inflated_by_a_retried_pull` for the pull side | — |
| Error handling | PARTIAL | `NotConnected` for absent credentials; unreadable rows rejected with a reason | `test_003_*`, `test_the_adapter_refuses_to_fetch_without_credentials` | `urlopen` has **no** try/except: an HTTP 500, a timeout or a DNS failure propagates as a raw urllib exception. There is no retry and no backoff. |
| Malformed input | IMPLEMENTED | every unreadable record becomes an explicit `Rejection(index, reason, identity, record_type)` on the snapshot — not a counter. A count of skipped rows cannot be acted on; an index and a reason can | `test_003_rejection_retains_index_and_reason`, `test_003_rejections_are_records_not_a_counter`, `test_integration_valid_valid_malformed_valid` | A malformed **webhook body** is now rejected inside `Ingest.handle` and logged (`test_wh_malformed_body_is_rejected_on_the_record`) rather than raising out to the HTTP layer. |
| Authentication / secrets | IMPLEMENTED | `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` from the environment; `status()` returns the key id truncated to 8 characters | read only — no test asserts that a secret never reaches a snapshot, a log or the UI | No secret is written to a snapshot, a log or the UI. Not verified by a test; verified by reading. |
| Field normalisation | IMPLEMENTED | see the mapping below | `test_the_adapter_never_reports_a_fixture_as_live` | Unrecognised `method` values are dropped rather than guessed — a wrong method is a wrong fee (D16). |
| Integer-paise conversion | IMPLEMENTED | `parse_amount(raw, AMOUNT_UNIT)` with the unit **declared**, not inferred. Reads exactly or raises — never `int()`, `round()` or truncation as a fallback | `test_002_*`, eighteen cases including `test_002_unit_is_declared_not_inferred` and `test_integration_ten_fifty_traced_through_every_layer` | Razorpay quotes integer paise, so `10.50` there is fractional paise — malformed, not ten rupees fifty. The unit is stated in `AMOUNT_UNIT` because a reader that guesses will eventually guess wrong by a factor of a hundred. |

## Normalised mapping

Only mappings that exist in the code.

| Razorpay recon field | ATTEST field | Consumer |
|---|---|---|
| `settlement_id` | `Settlement.settlement_id` | subject identity; grouping key for the credit total |
| `settlement_utr` | `Settlement.utr` | `exact_utr` evidence edge; the bank narration |
| `settled_at` | `Settlement.settled_on` | the settlement calendar that builds the candidate pool |
| `credit` − `debit` | `Settlement.net_paise` | the subset-sum target |
| `order_id` (falls back to `entity_id`) | `Order.order_id` | exact join; membership of the candidate universe |
| `payment_id` (falls back to `entity_id`) | `Order.payment_id` | exact join, the tie-break for identical amounts, and the de-duplication key for a payment row |
| `amount` (falls back to `credit + fee + tax`) | `Order.gross_paise` | the solver |
| `method` via `METHOD_MAP` | `Order.method` | the fee schedule, hence `net_paise` |
| `created_at` | `Order.captured_on` | blocking by capture date |
| `description` | `Order.customer_name` | evidence display only |
| `entity_id` | — | fallback de-duplication key; not retained |
| `fee`, `tax` | — | read for the `amount` fallback; fees are re-derived from the rule set |
| `refund_id` | — | de-duplication key for a refund row; not retained |
| `type` | — | routes payment rows to orders; everything else to the settlement total, and selects which field carries identity |

Fields present in the API and **not** consumed: `currency`, `on_hold`,
`settled`, `notes`, `order_receipt`, `card_network`, `card_issuer`, `card_type`,
`dispute_id`.

## Adversarial pass

Every case run against the code. Outcomes observed, not predicted.

| Attack | Outcome | Behaviour |
|---|---|---|
| fetch without credentials | REJECTED | `NotConnected`; no data fabricated |
| malformed payload (non-dict row) | HANDLED | `Rejection(0, "row is str, not an object")`; the rest of the page still reads — **was UNHANDLED** (`AttributeError` lost the page) |
| missing identifier | HANDLED | row is kept, not deduplicated: absent identity means the source has not asserted sameness |
| row naming itself twice, differently | REJECTED | `Rejection(… "row names itself both pay_1 and pay_2")`. Preferring one field would merge two records the source labelled as different — losing money the same way double-counting invents it |
| missing amount | HANDLED | falls back to `credit + fee + tax` |
| zero amount | HANDLED | order with `gross_paise = 0`; blocking's amount ceiling excludes it |
| negative adjustment | HANDLED | `debit` reduces the settlement total (net 1000 → 700); not modelled as an order |
| extreme amount (10¹⁵) | HANDLED | integer, no overflow; exceeds the solver envelope and reports INSUFFICIENT |
| unknown event type | HANDLED | not a payment, so it only affects the settlement total |
| unknown method | HANDLED | dropped with a warning; credit stays in the total, so the settlement reports CONTRADICTED with the exact gap |
| duplicate settlement rows | HANDLED | one order, `duplicates == 1` — **was UNHANDLED**, inflated the net from 1000 to 2000 |
| repeated refund | HANDLED | same de-duplication, keyed on `refund_id` |
| out-of-order rows | HANDLED | order is irrelevant; aggregation is commutative |
| partial / incomplete source | HANDLED | a settlement with no rows yields no settlement at all |
| float amount `10.5` | REJECTED | `Rejection(… "10.5 is a non-integral float")` — **was UNHANDLED**, `int(10.5)` became `10` silently |
| float amount `1024.0` | HANDLED | a float that is a whole number reads as 1024; the objection is to losing paise, not to the type |
| string amount `"10.50"` | REJECTED | under the declared PAISE contract that is ten and a half paise, which Razorpay cannot settle |
| NaN / ±Infinity amount | REJECTED | `"not a finite amount"`; never coerced |
| negative amount | REJECTED | direction is carried by `credit`/`debit`, not by a sign on the amount |
| null `created_at` | HANDLED | epoch 0; the date lands in 1970 and the settlement calendar excludes it |
| unreadable amount on a readable row | HANDLED, ASYMMETRIC | the order is dropped but its `credit` still counts toward the settlement, so the target stays as large as the source claimed and the gap surfaces. Shrinking it instead could let the surviving orders "prove" the smaller target — a read failure promoted to a PROVEN verdict |
| duplicate webhook (same body) | HANDLED | `DUPLICATE`, no second action |
| same id, different body | HANDLED | `REPLAY_MISMATCH`, neither acted on |
| invalid signature | REJECTED | `BAD_SIGNATURE`, not processed, not queued, not retried |
| missing signature | REJECTED | `BAD_SIGNATURE`; an unsigned body is not evidence of anything |
| malformed JSON webhook body | REJECTED | `BAD_SIGNATURE` with the reason recorded, logged inside `Ingest.handle` — **was UNHANDLED**, `JSONDecodeError` propagated to the HTTP layer |
| **no signing secret configured** | REJECTED | `UNVERIFIABLE`; ingestion refused rather than performed unverified — **was UNHANDLED and silent**, the verification branch simply never ran |

Six of these were defects found by running the pass rather than by reading the
code: ADAPTER-001 (de-duplication), ADAPTER-002 (float amounts), ADAPTER-003
(malformed rows), the fail-open webhook secret, the identity that `str(None)`
coerced to the shared truthy key `"None"`, and the malformed webhook body. All
six are fixed and each carries a named regression test.

The re-run above is a real execution against the current code, not a
transcription of the previous pass — its outcomes were printed by running every
case and reading what came back.

## Frozen boundaries

The rows below are **boundaries, not bugs** — claims this integration has
declined to make. They are frozen here so that no later reading of this file can
mistake an absent claim for an untested one, or an untested one for a broken
one.

- **No live Razorpay account has been exercised.** `fetch` performs a real
  authenticated request; it has never been called with real credentials.
- **Bank statement ingestion is synthetic.** Every credit matches its settlement
  by construction, so the adapter cannot exercise the case the engine exists for.
- **The pagination stop condition is unverified** against live API behaviour. It
  is read from documentation, not from responses.
- **Fee ingestion has read-only evidence.** Read and folded into the `amount`
  fallback; no test asserts it.
- **Secret handling has read-only evidence.** Verified by reading, not by a test.
- **Rejections do not outlive the process.** Correct for one pull, then gone.
  Deferred deliberately — see the rejection-persistence ADR in `DECISIONS.md`.

Never infer live validation from the existence of fetch code. The adapter is
hardened for the implemented and fixture path. It is not production-ready, and
this document does not say it is.

## What would be needed for a live integration

1. **A bank statement source.** The synthesised `BankCredit` makes every credit
   match its settlement exactly, which is the one thing this engine exists to
   handle when it does not.
2. **Refunds and adjustments as records**, so they can be cited as evidence
   rather than only reducing a total.
3. **Retry, backoff and error handling** around `_get`. `urlopen` still has no
   try/except: an HTTP 500, a timeout or a DNS failure propagates as a raw
   urllib exception.
4. **A durable event log** with a unique index on `(provider, event_id)`.
5. **Incremental sync** with a watermark.
6. **A durable rejection record.** `Snapshot.rejected` lives for the length of
   one pull. Rejections are the rows an operator must chase, and they should
   outlive the process that found them.
7. **A run against a real account**, after which most rows in this table should
   be re-audited — the difference between reading an API's documentation and
   reading its responses is where adapters actually fail.
