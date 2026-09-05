"""Adapter hardening. ADAPTER-001, ADAPTER-002, ADAPTER-003 and the webhook
boundary.

Every test here exists because an attack found something. The reader is the
part of ATTEST with no proof obligation attached to it — the solver's verdicts
are checked by an independent kernel, but nothing checks that the numbers the
solver was handed are the numbers the gateway sent. A settlement counted twice,
an amount truncated by a hundredth, a row dropped in silence: each produces a
CONTRADICTED verdict that is entirely the reader's fault, and none of them are
visible downstream.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from attest.adapters.money import AmountError, Unit, parse_amount
from attest.adapters.razorpay import RazorpayAdapter
from attest.webhooks import EventStatus, Ingest

SECRET = "whsec_test"


def rows(*items):
    return list(items)


def payment(entity_id, sid, amount, **kw):
    row = {"entity_id": entity_id, "type": "payment", "settlement_id": sid,
           "amount": amount, "credit": amount, "debit": 0, "fee": 0, "tax": 0,
           "method": "upi", "payment_id": entity_id}
    row.update(kw)
    return row


def norm(items, **kw):
    return RazorpayAdapter().normalise(items, [], **kw)


# --------------------------------------------------------------------------
# ADAPTER-001 — deduplication by source identity
# --------------------------------------------------------------------------

def test_001_identical_row_twice_is_counted_once():
    """The original defect: 1000 read twice became 2000."""
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_1", "setl_1", 1000)))
    assert s.duplicates == 1
    assert sum(o.gross_paise for o in s.orders) == 1000


def test_001_overlapping_pages_do_not_double_a_settlement():
    page_a = rows(payment("pay_1", "setl_1", 1000), payment("pay_2", "setl_1", 2000))
    page_b = rows(payment("pay_2", "setl_1", 2000), payment("pay_3", "setl_1", 3000))
    s = norm(page_a + page_b)
    assert [o.order_id for o in s.orders].count("pay_2") == 1
    assert sum(o.gross_paise for o in s.orders) == 6000


def test_001_distinct_ids_with_equal_amounts_both_survive():
    """Dedup must key on identity, never on amount. Two customers paying ₹10
    within a second of each other is the normal case, not a duplicate."""
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_2", "setl_1", 1000)))
    assert s.duplicates == 0
    assert len(s.orders) == 2


def test_001_dedup_is_scoped_to_record_type():
    """A refund and a payment may legitimately share an entity id."""
    s = norm(rows(payment("ent_1", "setl_1", 1000),
                  {"entity_id": "ent_1", "type": "refund", "settlement_id": "setl_1",
                   "credit": 0, "debit": 500, "fee": 0, "tax": 0}))
    assert s.duplicates == 0


def test_001_refund_dedup_uses_refund_id():
    """A refund row carrying only a refund id is still identified."""
    r = {"refund_id": "rfnd_1", "type": "refund", "settlement_id": "setl_1",
         "credit": 0, "debit": 500, "fee": 0, "tax": 0}
    s = norm(rows(dict(r), dict(r)))
    assert s.duplicates == 1
    assert s.settlements[0].net_paise == -500


def test_001_a_row_naming_itself_twice_differently_is_refused():
    """On a recon row the entity id of a refund IS its refund id. Disagreement
    means the source has not said which record this is, and preferring one
    field would merge two records it labelled as different — losing money the
    same way double-counting invents it."""
    s = norm(rows({"entity_id": "ent_x", "refund_id": "rfnd_1", "type": "refund",
                   "settlement_id": "setl_1", "credit": 0, "debit": 500,
                   "fee": 0, "tax": 0}))
    assert s.duplicates == 0
    assert "names itself both" in s.rejected[0].reason
    assert not s.settlements


def test_001_rows_without_any_identity_are_kept():
    """No identity means the source has not asserted sameness. Two genuinely
    distinct rows can be identical in every field; discarding one to look tidy
    loses money that nobody will ever notice is gone."""
    anon = {"type": "payment", "settlement_id": "setl_1", "amount": 1000,
            "credit": 1000, "debit": 0, "fee": 0, "tax": 0, "method": "upi"}
    s = norm(rows(dict(anon), dict(anon)))
    assert s.duplicates == 0
    assert len(s.orders) == 2


def test_001_no_identity_is_never_fabricated():
    anon = {"type": "payment", "settlement_id": "setl_1", "amount": 1000,
            "credit": 1000, "debit": 0, "fee": 0, "tax": 0, "method": "upi"}
    s = norm(rows(dict(anon)))
    assert all(not o.order_id.startswith("row_") for o in s.orders)


def test_001_duplicate_count_is_reported_not_swallowed():
    s = norm(rows(payment("pay_1", "setl_1", 1000), payment("pay_1", "setl_1", 1000)))
    assert s.duplicates == 1
    assert any("same source identity" in w for w in s.warnings)


def test_001_settlement_total_is_not_inflated_by_a_retried_pull():
    page = rows(payment("pay_1", "setl_1", 1000), payment("pay_2", "setl_1", 2000))
    once, twice = norm(page), norm(page + page)
    assert once.settlements[0].net_paise == twice.settlements[0].net_paise


def test_001_dedup_keeps_the_first_occurrence():
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_1", "setl_1", 9999)))
    assert sum(o.gross_paise for o in s.orders) == 1000


# --------------------------------------------------------------------------
# ADAPTER-002 — money is read exactly or refused
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expect", [(10, 10), (10.0, 10), ("10", 10), ("10.00", 10)])
def test_002_whole_paise_read_exactly(raw, expect):
    assert parse_amount(raw, Unit.PAISE) == expect


@pytest.mark.parametrize("raw", [
    "10.50", 10.5, "10.001", float("nan"), float("inf"), float("-inf"),
    -1, "-1", None, "", "  ", "abc", "1e", True, [10], {"v": 10},
])
def test_002_inexact_or_unreadable_is_refused(raw):
    """Never int(), round() or truncate() as a fallback. 10.50 paise is not a
    quantity Razorpay can settle; guessing it means 10 is how money vanishes."""
    with pytest.raises(AmountError):
        parse_amount(raw, Unit.PAISE)


def test_002_very_large_amount_survives_exactly():
    big = 10 ** 15 + 7
    assert parse_amount(str(big), Unit.PAISE) == big


def test_002_unit_is_declared_not_inferred():
    """The same literal is two different amounts under two contracts. A reader
    that infers will one day be wrong by a factor of a hundred."""
    assert parse_amount("10.50", Unit.RUPEES) == 1050
    with pytest.raises(AmountError):
        parse_amount("10.50", Unit.PAISE)


def test_002_fractional_amount_is_rejected_with_its_row_recorded():
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_2", "setl_1", 10.5)))
    assert len(s.orders) == 1
    assert [r.index for r in s.rejected] == [1]
    assert "pay_2" in s.rejected[0].identity


def test_002_rejected_amount_never_reaches_a_settlement_total():
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_2", "setl_1", 10.5)))
    assert s.settlements[0].net_paise == 1000


# --------------------------------------------------------------------------
# ADAPTER-003 — malformed rows are rejected explicitly, not counted
# --------------------------------------------------------------------------

def test_003_malformed_row_does_not_kill_the_page():
    s = norm(rows(payment("pay_1", "setl_1", 1000), "not a row",
                  payment("pay_3", "setl_1", 3000)))
    assert len(s.orders) == 2


def test_003_rejection_retains_index_and_reason():
    s = norm(rows(payment("pay_1", "setl_1", 1000), None))
    assert s.rejected[0].index == 1
    assert "NoneType" in s.rejected[0].reason


def test_003_rejections_are_records_not_a_counter():
    s = norm(rows("x", payment("pay_1", "setl_1", 10.5)))
    assert [(r.index, bool(r.reason)) for r in s.rejected] == [(0, True), (1, True)]
    assert s.rejected[1].record_type == "payment"


# --------------------------------------------------------------------------
# Webhook boundary — fail closed
# --------------------------------------------------------------------------

def body(**kw):
    d = {"id": "evt_1", "event": "refund.created"}
    d.update(kw)
    return json.dumps(d).encode()


def sign(b, secret=SECRET):
    return hmac.new(secret.encode(), b, hashlib.sha256).hexdigest()


def test_wh_valid_signature_is_accepted():
    b = body()
    assert Ingest(secret=SECRET).handle("razorpay", b, sign(b), {}, set()).status \
        is EventStatus.ACCEPTED


def test_wh_absent_secret_refuses_ingestion():
    """The defect: `if self.secret and not verify(...)` verified nothing when
    the secret was unset, processed everything, and said so nowhere."""
    b = body()
    ev = Ingest(secret="").handle("razorpay", b, sign(b), {}, set())
    assert ev.status is EventStatus.UNVERIFIABLE
    assert "no signing secret" in ev.detail


def test_wh_absent_secret_rejects_even_a_well_formed_event():
    b = body()
    ing = Ingest(secret="")
    ing.handle("razorpay", b, sign(b), {}, set())
    assert all(e.status is EventStatus.UNVERIFIABLE for e in ing.log.events)


def test_wh_wrong_signature_is_rejected():
    b = body()
    assert Ingest(secret=SECRET).handle("razorpay", b, sign(b, "other"), {}, set()).status \
        is EventStatus.BAD_SIGNATURE


def test_wh_missing_signature_is_rejected():
    assert Ingest(secret=SECRET).handle("razorpay", body(), "", {}, set()).status \
        is EventStatus.BAD_SIGNATURE


def test_wh_replayed_event_is_a_duplicate_not_a_second_effect():
    b, ing = body(), Ingest(secret=SECRET)
    ing.handle("razorpay", b, sign(b), {}, set())
    assert ing.handle("razorpay", b, sign(b), {}, set()).status is EventStatus.DUPLICATE


def test_wh_same_id_different_body_is_a_contradiction():
    ing = Ingest(secret=SECRET)
    a, c = body(), body(event="refund.processed")
    ing.handle("razorpay", a, sign(a), {}, set())
    assert ing.handle("razorpay", c, sign(c), {}, set()).status \
        is EventStatus.REPLAY_MISMATCH


def test_wh_malformed_body_is_rejected_on_the_record():
    b = b"{not json"
    ing = Ingest(secret=SECRET)
    ev = ing.handle("razorpay", b, sign(b), {}, set())
    assert ev.status is EventStatus.BAD_SIGNATURE
    assert ing.log.events, "an event that arrived and was refused must be logged"


# --------------------------------------------------------------------------
# Integration — the three paths that matter end to end
# --------------------------------------------------------------------------

def test_integration_three_overlapping_pages_yield_three_records():
    """A/B overlap and B/C overlap. The union is A, B, C — not five rows."""
    a = payment("pay_A", "setl_1", 1000)
    b = payment("pay_B", "setl_1", 2000)
    c = payment("pay_C", "setl_1", 3000)
    s = norm([a, b] + [b, c])
    assert sorted(o.order_id for o in s.orders) == ["pay_A", "pay_B", "pay_C"]
    assert s.settlements[0].net_paise == 6000
    assert s.duplicates == 1


def test_integration_ten_fifty_traced_through_every_layer():
    """`10.50` under Razorpay's integer-paise contract is fractional paise.
    It must be refused at the parser, refused at the adapter, absent from the
    orders, absent from the settlement total, and visible as a rejection."""
    with pytest.raises(AmountError):
        parse_amount("10.50", Unit.PAISE)
    s = norm(rows(payment("pay_ok", "setl_1", 1000),
                  payment("pay_bad", "setl_1", "10.50")))
    assert [o.order_id for o in s.orders] == ["pay_ok"]
    assert s.settlements[0].net_paise == 1000
    assert len(s.rejected) == 1 and s.rejected[0].index == 1
    assert any("rejected rather than rounded" in w for w in s.warnings)


def test_integration_valid_valid_malformed_valid():
    s = norm(rows(payment("pay_1", "setl_1", 1000),
                  payment("pay_2", "setl_1", 2000),
                  {"entity_id": "pay_3", "type": "payment", "settlement_id": "setl_1",
                   "amount": "oops", "credit": 0, "debit": 0, "fee": 0, "tax": 0,
                   "method": "upi", "payment_id": "pay_3"},
                  payment("pay_4", "setl_1", 4000)))
    assert sorted(o.order_id for o in s.orders) == ["pay_1", "pay_2", "pay_4"]
    assert [r.index for r in s.rejected] == [2]
    assert s.settlements[0].net_paise == 7000


def test_a_rejected_order_never_shrinks_the_settlement_target():
    """The asymmetry that keeps a rejection fail-CLOSED.

    A row whose `amount` cannot be read still contributes its readable
    `credit` to the settlement total. The order is gone, the target is not —
    so the settlement becomes unexplainable and reports the gap.

    Dropping the credit as well would shrink the target until the surviving
    orders could explain it exactly, turning a read failure into a PROVEN
    verdict. That is the one outcome a reader must never produce.
    """
    row = {"entity_id": "pay_1", "payment_id": "pay_1", "type": "payment",
           "settlement_id": "setl_1", "amount": 10.5, "credit": 1000,
           "debit": 0, "fee": 0, "tax": 0, "method": "upi"}
    s = norm([row])
    assert not s.orders, "the unreadable order must not reach the solver"
    assert s.settlements[0].net_paise == 1000, (
        "the target must stay as large as the source claimed")
    assert s.rejected[0].index == 0
