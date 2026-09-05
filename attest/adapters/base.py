"""The adapter contract. §34.

    DataSource
       ├── RazorpayAdapter
       ├── CSVAdapter
       └── MockAdapter
             │
             ▼
         Normalizer
             │
             ▼
         ATTEST core

Two rules hold the seam together.

**Nothing below this line knows about a gateway.** The solver sees `Order`,
`Settlement`, `BankCredit` and nothing else, so swapping the source cannot change
a verdict.

**A source states its own provenance and freshness.** A snapshot that cannot say
where it came from or when is not usable as evidence, and §38 is right that
pretending data is live when it is not is the one thing an integration must never
do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from attest.model import BankCredit, Order, Settlement


@dataclass(frozen=True)
class Rejection:
    """One source record the adapter would not read, and why. ADAPTER-003.

    Kept rather than counted. A malformed row is a fact about the source, and
    an ingestion that reports "3 rows skipped" cannot be acted on — the reader
    needs the index to find it and the identity to ask the source about it.
    """

    index: int
    reason: str
    identity: str = ""
    record_type: str = ""

    def to_json(self) -> dict[str, object]:
        return {"index": self.index, "reason": self.reason,
                "identity": self.identity, "record_type": self.record_type}


@dataclass
class Snapshot:
    """Records plus the account of where they came from."""

    orders: list[Order] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    credits: list[BankCredit] = field(default_factory=list)

    source: str = "unknown"
    live: bool = False
    """False for anything not pulled from a real connected account. Never set
    true to make a demo look better — §39."""

    fetched_at: datetime | None = None
    coverage: str = ""
    """What window these records span, in the source's own terms."""

    warnings: list[str] = field(default_factory=list)
    """Things a reader must know before trusting a number derived from this —
    partial pages, rate limits, missing entity types."""

    rejected: list[Rejection] = field(default_factory=list)
    """Source records that could not be read exactly. Explicit, indexed and
    identified — never silently dropped, and never rounded into acceptance."""

    duplicates: int = 0
    """Source records discarded because a record with the same source identity
    was already read in this pull. ADAPTER-001."""

    #: Records the source carries that the engine can use as an ANCHOR rather
    #: than having to solve for. See `linked_fraction`.
    linked_orders: int = 0

    @property
    def linked_fraction(self) -> float:
        """Share of orders arriving with an explicit settlement reference.

        The single most important number about a source. Where it is high,
        reconciliation is a join; where it is zero, it is subset-sum over a large
        pool and most settlements are genuinely under-determined. The synthetic
        generator emits zero, which is why the engine abstains on 82% of it.
        """
        return self.linked_orders / max(len(self.orders), 1)

    def describe(self) -> str:
        when = self.fetched_at.isoformat(timespec="seconds") if self.fetched_at else "—"
        return (f"{self.source} · {'live' if self.live else 'not live'} · "
                f"{len(self.orders):,} orders · {len(self.settlements):,} settlements · "
                f"{self.linked_fraction:.0%} linked · fetched {when}")


class DataSource(Protocol):
    name: str

    def fetch(self, **kw: object) -> Snapshot:
        """Pull records and normalise them. Must never invent a record, and must
        raise rather than return a partial snapshot silently."""
        ...

    def status(self) -> dict[str, object]:
        """Connection state for the integrations screen. Must report honestly
        when not connected."""
        ...


class NotConnected(RuntimeError):
    """Raised instead of returning fabricated data.

    §39: never fake a production connection. An adapter without credentials has
    exactly one correct behaviour, and it is to say so.
    """
