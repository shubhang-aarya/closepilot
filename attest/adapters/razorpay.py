"""Razorpay adapter. §33, §34, §39.

Written against the published API only. The endpoint and field names below are
from Razorpay's own documentation and are quoted rather than guessed:

    GET /v1/settlements/recon/combined?year=YYYY&month=MM[&day=DD][&count][&skip]

    entity_id, type, debit, credit, amount, currency, fee, tax, on_hold,
    settled, created_at, settled_at, settlement_id, description, notes,
    payment_id, settlement_utr, order_id, order_receipt, method, card_network,
    card_issuer, card_type, dispute_id

**This endpoint changes what ATTEST is doing, and the honest framing matters.**

FAILURES.md D8 concluded that the AI anchoring loop was a coin flip because the
settlement report carried no order-level reference, so every anchor was a guess.
That is true of the *synthetic* generator. It is not true of Razorpay: the recon
report carries `order_id` and `payment_id` on each settled transaction, and
`settlement_id` grouping them.

So against a real connected account, reconciliation is largely a **join**, and
the subset-sum machinery is the fallback for the cases where the join fails —
recon unavailable for a period, a bank credit that does not match any single
settlement, adjustments with no linked entity, or a merchant reconciling against
a bank statement rather than the gateway. Those are exactly the hard cases, and
they are the ones this engine was built for.

Saying that plainly is better than implying the hard path is always necessary.
The value is not that subset-sum is always needed; it is that when the join
fails, the alternative is a person in a spreadsheet.

**No credentials, no data.** `fetch` raises `NotConnected` rather than returning
anything. There is no demo mode inside this class.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from attest.adapters.base import NotConnected, Rejection, Snapshot
from attest.adapters.money import AmountError, Unit, parse_amount
from attest.model import BankCredit, Method, Order, Settlement

#: Razorpay's recon API quotes every amount in INTEGER PAISE. Declared rather
#: than inferred: `10.50` means ten and a half paise under this contract, not
#: ten rupees fifty, and a reader that guesses will eventually guess wrong by a
#: factor of a hundred.
AMOUNT_UNIT = Unit.PAISE

#: Strongest stable identity per record type, most specific first. Falls back
#: to the generic entity id, and to NOTHING at all — deliberately. `str(None)`
#: is the truthy string "None", so a fallback chain written carelessly gives
#: every unidentified row the SAME identity and deduplicates unrelated
#: payments into one. Identity is read, never coerced.
_ID_FIELDS = {
    "payment": ("payment_id", "entity_id"),
    "refund": ("refund_id", "entity_id"),
    "adjustment": ("entity_id",),
    "dispute": ("entity_id",),
}


class IdentityConflict(ValueError):
    """A row names itself twice, differently."""


def _identity(row: dict[str, object], kind: str) -> str:
    """The strongest stable identity the SOURCE provides, or nothing.

    On a Razorpay recon row the entity id of a payment IS its payment id, so
    the two fields disagreeing means the row is internally inconsistent. The
    reader must not resolve that by preferring one — picking `payment_id` would
    merge two records the source labelled as different entities, which loses
    money the same way double-counting invents it. Raised, not guessed.
    """
    found: list[str] = []
    for field in _ID_FIELDS.get(kind, ("entity_id",)):
        v = row.get(field)
        if isinstance(v, str) and v.strip():
            found.append(v.strip())
        elif isinstance(v, int) and not isinstance(v, bool):
            found.append(str(v))
    if len(set(found)) > 1:
        raise IdentityConflict(
            f"row names itself both {' and '.join(sorted(set(found)))}; the "
            f"source has not said which record this is")
    return found[0] if found else ""


BASE = "https://api.razorpay.com/v1"
RECON = "/settlements/recon/combined"
SETTLEMENTS = "/settlements"

#: Razorpay's `method` values mapped onto ATTEST's. Anything unrecognised is
#: reported as a warning rather than guessed into the nearest match — a wrong
#: method means a wrong fee, and a wrong fee means the truth stops balancing
#: (FAILURES.md D16).
METHOD_MAP: dict[str, Method] = {
    "upi": Method.UPI,
    "card": Method.CARD,
    "netbanking": Method.NETBANKING,
    "wallet": Method.WALLET,
    "emi": Method.CARD,
}


class RazorpayAdapter:
    """Reads settlements and their constituent transactions.

    Credentials come from the environment (`RAZORPAY_KEY_ID`,
    `RAZORPAY_KEY_SECRET`) and are never logged, echoed, or written into a
    snapshot.
    """

    name = "razorpay"

    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")

    @property
    def connected(self) -> bool:
        return bool(self.key_id and self.key_secret)

    def status(self) -> dict[str, object]:
        return {
            "provider": "razorpay",
            "connected": self.connected,
            "key_id": (self.key_id[:8] + "…") if self.key_id else None,
            "endpoints": [f"GET {BASE}{RECON}", f"GET {BASE}{SETTLEMENTS}"],
            "reads": ["settlements", "settled payments", "refunds",
                      "adjustments", "fees and tax"],
            "writes": [],
            "note": ("Read-only. ATTEST never posts, refunds, or modifies "
                     "anything through this connection — it has no write scope "
                     "and no endpoint in this adapter mutates state."),
        }

    # -- fetching ----------------------------------------------------------

    def fetch(self, year: int, month: int, day: int | None = None,
              page: int = 1000) -> Snapshot:
        """Pull one recon period and normalise it.

        Paginates with `count`/`skip` until a short page arrives. A partial pull
        is surfaced as a warning rather than silently truncated: a snapshot
        missing transactions makes settlements look CONTRADICTED for a reason
        that has nothing to do with the merchant's books.
        """
        if not self.connected:
            raise NotConnected(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are not set. This "
                "adapter does not fabricate data; connect an account or use the "
                "synthetic source, which is labelled as synthetic everywhere it "
                "appears.")

        items, skip, warnings = [], 0, []
        while True:
            batch = self._get(RECON, {"year": year, "month": month,
                                      **({"day": day} if day else {}),
                                      "count": page, "skip": skip})
            got = batch.get("items", [])
            items.extend(got)
            if len(got) < page:
                break
            skip += page
            if skip > 100_000:
                warnings.append(
                    f"stopped after {skip:,} rows; this period is larger than a "
                    f"single pull and the snapshot is incomplete")
                break

        return self.normalise(
            items, warnings, live=True,
            coverage=f"{year}-{month:02d}" + (f"-{day:02d}" if day else ""))

    def _get(self, path: str, params: dict[str, object]) -> dict[str, object]:
        import base64
        import json
        import urllib.parse
        import urllib.request

        url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    # -- normalisation -----------------------------------------------------

    def normalise(self, items: list[dict[str, object]], warnings: list[str],
                  coverage: str = "", live: bool = False) -> Snapshot:
        """Recon rows into ATTEST's model.

        Kept separate from `fetch` so it can be exercised against recorded
        fixtures without a live account — the transformation is where the bugs
        live, and it should be testable without credentials.

        `live` defaults to FALSE and only `fetch` sets it. A normaliser run over
        a fixture that reports itself as live is precisely the lie §39 forbids,
        and defaulting the other way would make it the easy mistake.
        """
        orders: list[Order] = []
        by_settlement: dict[str, dict[str, int]] = {}
        utrs: dict[str, str] = {}
        settled_on: dict[str, int] = {}
        linked = 0
        unknown_methods: set[str] = set()
        rejected: list[Rejection] = []

        # ADAPTER-001. Recon rows aggregate into a settlement total, so the same
        # row read twice DOUBLES that settlement. Razorpay pagination with an
        # overlapping `skip` window and a retried pull both produce exactly
        # that, and the result is a settlement net no bank credit matches — a
        # CONTRADICTED verdict caused by the reader rather than the books.
        #
        # Identity is the strongest STABLE one the source provides, chosen by
        # record type, never an amount and never a fabricated key:
        #
        #     payment     payment_id, else entity_id
        #     refund      refund_id,  else entity_id
        #     adjustment  entity_id
        #     anything    entity_id
        #
        # A row carrying no identity at all is kept: two genuinely distinct rows
        # can be identical in every field, and discarding one to be tidy would
        # lose money. Deduplication needs the source to assert sameness.
        seen: set[tuple[str, str]] = set()
        deduped: list[tuple[int, dict[str, object]]] = []
        duplicates = 0

        for i, it in enumerate(items):
            if not isinstance(it, dict):
                # ADAPTER-003. This raised AttributeError, losing the page.
                rejected.append(Rejection(
                    i, f"row is {type(it).__name__}, not an object"))
                continue
            kind = str(it.get("type") or "")
            try:
                ident = _identity(it, kind)
            except IdentityConflict as e:
                rejected.append(Rejection(i, str(e), "", kind))
                continue
            if ident:
                key = (kind, ident)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
            deduped.append((i, it))

        for i, it in deduped:
            sid = str(it.get("settlement_id") or "")
            kind = str(it.get("type") or "")

            try:
                credit = parse_amount(it.get("credit") or 0, AMOUNT_UNIT)
                debit = parse_amount(it.get("debit") or 0, AMOUNT_UNIT)
                fee = parse_amount(it.get("fee") or 0, AMOUNT_UNIT)
                tax = parse_amount(it.get("tax") or 0, AMOUNT_UNIT)
            except AmountError as e:
                rejected.append(Rejection(
                    i, f"settlement column: {e}",
                    str(it.get("entity_id") or ""), kind))
                continue

            if sid:
                agg = by_settlement.setdefault(sid, {"credit": 0, "debit": 0})
                agg["credit"] += credit
                agg["debit"] += debit
                if it.get("settlement_utr"):
                    utrs[sid] = str(it["settlement_utr"])
                if it.get("settled_at"):
                    settled_on[sid] = int(it["settled_at"])

            if kind != "payment":
                # Refunds, adjustments and disputes reduce a settlement rather
                # than composing it. They are carried on the settlement total
                # above; modelling them as negative orders would let the solver
                # "explain" a credit with a refund, which is not a thing.
                continue

            raw_method = str(it.get("method") or "").lower()
            method = METHOD_MAP.get(raw_method)
            if method is None:
                unknown_methods.add(raw_method or "(absent)")
                continue

            # ADAPTER-002. Read exactly or not at all. `int(10.5)` gave 10 —
            # money altered by the reader with nobody told. attest/adapters/
            # money.py declares the unit rather than inferring it, because
            # 10.50 is ambiguous without one and a reader that guesses will
            # eventually guess wrong by a factor of a hundred.
            raw_amount = it.get("amount")
            if raw_amount is None:
                raw_amount = credit + fee + tax
            try:
                gross = parse_amount(raw_amount, AMOUNT_UNIT)
            except AmountError as e:
                rejected.append(Rejection(
                    i, f"amount: {e}", str(it.get("entity_id") or ""), kind))
                continue
            oid = str(it.get("order_id") or it.get("entity_id") or "")
            pid = str(it.get("payment_id") or it.get("entity_id") or "") or None
            created = int(it.get("created_at") or 0)
            if sid:
                linked += 1

            orders.append(Order(
                order_id=oid,
                captured_on=datetime.fromtimestamp(created, timezone.utc).date(),
                gross_paise=gross, method=method,
                customer_name=str(it.get("description") or ""),
                payment_id=pid))

        settlements, credits = [], []
        for sid, agg in by_settlement.items():
            net = agg["credit"] - agg["debit"]
            when = datetime.fromtimestamp(settled_on.get(sid, 0), timezone.utc).date()
            settlements.append(Settlement(sid, when, net, utrs.get(sid)))
            credits.append(BankCredit(
                f"bank_{sid}", when, net,
                f"NEFT-{utrs.get(sid, '')}-RAZORPAY SOFTWARE PVT LTD-SETTLEMENT"))

        if duplicates:
            warnings.append(
                f"{duplicates} recon row(s) discarded: a record with the same "
                f"source identity was already read in this pull. Counting one "
                f"twice inflates a settlement total and produces a "
                f"CONTRADICTED verdict caused by the reader.")
        if rejected:
            warnings.append(
                f"{len(rejected)} source record(s) could not be read exactly "
                f"and were rejected rather than rounded. Each is listed with "
                f"its row index and reason in `snapshot.rejected`.")
        if unknown_methods:
            warnings.append(
                f"unrecognised payment methods dropped: {', '.join(sorted(unknown_methods))}. "
                f"A guessed method means a guessed fee, and a guessed fee makes the "
                f"truth stop balancing — see FAILURES.md D16.")
            warnings.append(
                "their credits remain in the settlement totals, deliberately: the "
                "money did settle, and removing it to make the books balance would "
                "hide a real gap. Those settlements will report CONTRADICTED with "
                "the exact unexplained amount, which is the honest outcome.")

        return Snapshot(
            orders=orders, settlements=settlements, credits=credits,
            source="razorpay", live=live, fetched_at=datetime.now(timezone.utc),
            coverage=coverage, warnings=warnings, linked_orders=linked,
            rejected=rejected, duplicates=duplicates)
