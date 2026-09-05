"""The financial period — a named grouping over existing settlements.

A reconciliation engine answers what composed an individual credit. A controller
answers whether a bounded interval of financial activity can close.

The period is a pure grouping over existing settlements. It does no solving,
no matching, and introduces no new financial truth: it only identifies which
settlement outcomes belong to this accounting interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attest.exceptions import Exception_
    from attest.model import Settlement
    from attest.verdict import Finding


@dataclass(frozen=True, slots=True)
class Period:
    """A named grouping of settlements evaluated together for close.

    Settlements are identified by their canonical ID strings. An optional date
    interval records the calendar window the grouping represents.
    """

    period_id: str
    settlement_ids: tuple[str, ...]
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(
                f"Period end {self.end} precedes start {self.start}; "
                f"a period that ends before it begins contains nothing "
                f"and cannot be evaluated."
            )

    def contains(self, settlement_id: str) -> bool:
        return settlement_id in self.settlement_ids

    def filter_settlements(self, settlements: list[Settlement]) -> list[Settlement]:
        target = set(self.settlement_ids)
        return [s for s in settlements if s.settlement_id in target]

    def filter_findings(self, findings: list[Finding]) -> list[Finding]:
        target = set(self.settlement_ids)
        return [f for f in findings if f.settlement_id in target]

    def filter_exceptions(self, exceptions: list[Exception_]) -> list[Exception_]:
        target = set(self.settlement_ids)
        return [e for e in exceptions if e.settlement_id in target]

    @classmethod
    def from_settlements(
        cls,
        period_id: str,
        settlements: list[Settlement] | tuple[Settlement, ...],
        start: date | None = None,
        end: date | None = None,
    ) -> Period:
        return cls(
            period_id=period_id,
            settlement_ids=tuple(s.settlement_id for s in settlements),
            start=start,
            end=end,
        )

    @classmethod
    def from_date_range(
        cls,
        period_id: str,
        settlements: list[Settlement],
        start: date,
        end: date,
    ) -> Period:
        in_range = [
            s.settlement_id
            for s in settlements
            if start <= s.settled_on <= end
        ]
        return cls(
            period_id=period_id,
            settlement_ids=tuple(in_range),
            start=start,
            end=end,
        )
