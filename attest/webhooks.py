"""Event ingestion. §35, §36, §40.

A settlement is not a thing that happens once. A refund lands two days later, a
chargeback three weeks later, an adjustment whenever someone in operations
decides. So the engine has to accept events over time and work out what they
change — and the §35 requirement is the whole design:

    do not rerun the entire world for every event.

Two properties carry the weight.

**Idempotency (§36).** Gateways retry. A webhook delivered twice must not be
processed twice, and the guard cannot be the event id alone: a provider that
reuses an id with different content, or a replay with a mutated body, is a
different problem that an id check waves through. Both the id and a hash of the
payload are recorded, and a repeat of either is refused with the reason stated.

**Blast radius.** An event names entities; entities belong to settlements; only
those settlements are re-verified. A payment captured today cannot change a
settlement from last month, and re-deciding one anyway would burn the run's
determinism for nothing.

Signature verification is HMAC-SHA256 over the raw body, compared in constant
time. An event that fails it is not processed, not stored as pending, and not
retried — it is rejected, because a body that does not verify is not evidence of
anything.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REPLAY_MISMATCH = "replay_mismatch"
    """Same event id, different body. Not a duplicate — a contradiction, and the
    one case where silently ignoring the second delivery would lose data."""
    BAD_SIGNATURE = "bad_signature"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"
    """No signing secret is configured, so authenticity cannot be established.

    Fails CLOSED. A financial webhook boundary that processes an unverified
    event because someone forgot an environment variable is a boundary in name
    only, and the failure is silent — which is the worst combination."""


#: Event types this engine knows how to act on. Anything else is stored and
#: reported as unsupported rather than dropped — an unknown event is information
#: about the integration, not noise.
HANDLED = {
    "payment.captured", "payment.failed",
    "refund.created", "refund.processed",
    "settlement.processed", "payment.dispute.created",
}


@dataclass(frozen=True)
class Event:
    provider: str
    event_id: str
    kind: str
    payload: dict[str, object]
    received_at: datetime
    payload_hash: str
    status: EventStatus = EventStatus.ACCEPTED
    processed_at: datetime | None = None
    affected: tuple[str, ...] = ()
    detail: str = ""

    def to_json(self) -> dict[str, object]:
        return {"provider": self.provider, "event_id": self.event_id,
                "kind": self.kind, "status": self.status.value,
                "received_at": self.received_at.isoformat(timespec="seconds"),
                "processed_at": self.processed_at.isoformat(timespec="seconds")
                if self.processed_at else None,
                "payload_hash": self.payload_hash[:16],
                "affected": list(self.affected), "detail": self.detail}


def verify(body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 over the raw body, compared in constant time.

    The RAW bytes, not a re-serialised dict: any normalisation on the way in
    changes the digest and turns a valid event into a rejected one, which is a
    bug that only appears in production with a real gateway.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@dataclass
class EventLog:
    """Idempotent store. §36.

    In-process here; a deployment puts this in a table with a unique index on
    (provider, event_id) and lets the database enforce what this class enforces
    in memory. The semantics are what matter and they are stated here.
    """

    seen: dict[tuple[str, str], str] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def record(self, provider: str, event_id: str, kind: str,
               payload: dict[str, object]) -> Event:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode()).hexdigest()
        key = (provider, event_id)
        now = datetime.now(timezone.utc)

        if key in self.seen:
            same = self.seen[key] == digest
            ev = Event(
                provider, event_id, kind, payload, now, digest,
                EventStatus.DUPLICATE if same else EventStatus.REPLAY_MISMATCH,
                detail=("already processed; ignored" if same else
                        "same event id with a different body — the second "
                        "delivery contradicts the first and neither can be "
                        "trusted without operator review"))
            self.events.append(ev)
            return ev

        if kind not in HANDLED:
            ev = Event(provider, event_id, kind, payload, now, digest,
                       EventStatus.UNSUPPORTED,
                       detail=f"{kind} is not acted on; stored for the record")
            self.seen[key] = digest
            self.events.append(ev)
            return ev

        self.seen[key] = digest
        ev = Event(provider, event_id, kind, payload, now, digest,
                   EventStatus.ACCEPTED, processed_at=now)
        self.events.append(ev)
        return ev

    def replace_last(self, ev: Event) -> None:
        if self.events:
            self.events[-1] = ev


# --------------------------------------------------------------------------
# Blast radius
# --------------------------------------------------------------------------


def entities(payload: dict[str, object]) -> set[str]:
    """Every id an event mentions, at any depth.

    Razorpay nests the entity under `payload.<type>.entity`, and the shape varies
    by event. Walking for known key names is more robust than encoding a path per
    event type, and an id the walk misses costs a re-verification, never a wrong
    answer.
    """
    found: set[str] = set()
    keys = {"id", "order_id", "payment_id", "refund_id", "settlement_id",
            "entity_id", "invoice_id"}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keys and isinstance(v, str) and v:
                    found.add(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(payload)
    return found


def affected_settlements(payload: dict[str, object],
                         order_to_settlement: dict[str, str],
                         known_settlements: set[str]) -> set[str]:
    """Which settlements this event can possibly change.

    Only these are re-verified. An event that names nothing the engine holds
    affects nothing — which is the common case for a payment captured today
    against a book that has not settled it yet, and re-deciding the world for it
    would be pure waste.
    """
    ids = entities(payload)
    out = {i for i in ids if i in known_settlements}
    out |= {order_to_settlement[i] for i in ids if i in order_to_settlement}
    return out


@dataclass
class Ingest:
    """One event, end to end: verify, deduplicate, scope, report."""

    log: EventLog = field(default_factory=EventLog)
    secret: str = ""

    def handle(self, provider: str, body: bytes, signature: str,
               order_to_settlement: dict[str, str],
               known_settlements: set[str]) -> Event:
        now = datetime.now(timezone.utc)

        # Fail closed on an absent secret. This used to read `if self.secret
        # and not verify(...)`, so a deployment that never set the secret
        # verified nothing, processed everything, and said so nowhere.
        if not self.secret:
            ev = Event(provider, "-", "-", {}, now,
                       hashlib.sha256(body).hexdigest(),
                       EventStatus.UNVERIFIABLE,
                       detail=("no signing secret is configured, so this "
                               "event's authenticity cannot be established; "
                               "ingestion is refused rather than performed "
                               "unverified"))
            self.log.events.append(ev)
            return ev

        if not signature:
            ev = Event(provider, "-", "-", {}, now,
                       hashlib.sha256(body).hexdigest(),
                       EventStatus.BAD_SIGNATURE,
                       detail="no signature was supplied; an unsigned body is "
                              "not evidence of anything")
            self.log.events.append(ev)
            return ev

        if not verify(body, signature, self.secret):
            ev = Event(provider, "-", "-", {}, now,
                       hashlib.sha256(body).hexdigest(),
                       EventStatus.BAD_SIGNATURE,
                       detail=("signature did not verify; not processed, not "
                               "queued, not retried — a body that does not "
                               "verify is not evidence of anything"))
            self.log.events.append(ev)
            return ev

        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("body is not an object")
        except (ValueError, UnicodeDecodeError) as e:
            # A malformed body used to raise out of the ingest and was caught
            # only by the HTTP layer. Rejected here, on the record, so the log
            # shows that something arrived and was refused.
            ev = Event(provider, "-", "-", {}, now,
                       hashlib.sha256(body).hexdigest(),
                       EventStatus.BAD_SIGNATURE,
                       detail=f"signature verified but the body is not usable "
                              f"JSON: {e}")
            self.log.events.append(ev)
            return ev
        kind = str(payload.get("event") or "unknown")
        event_id = str(payload.get("id") or hashlib.sha256(body).hexdigest()[:24])

        ev = self.log.record(provider, event_id, kind, payload)
        if ev.status is not EventStatus.ACCEPTED:
            return ev

        hit = affected_settlements(payload, order_to_settlement, known_settlements)
        ev = Event(**{**ev.__dict__, "affected": tuple(sorted(hit)),
                      "detail": (f"{len(hit)} settlement"
                                 f"{'' if len(hit) == 1 else 's'} "
                                 f"require{'s' if len(hit) == 1 else ''} "
                                 f"re-verification"
                                 if hit else
                                 "names nothing this book holds; no settlement "
                                 "changes and nothing is re-run")})
        self.log.replace_last(ev)
        return ev
